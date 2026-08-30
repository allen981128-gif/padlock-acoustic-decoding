from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


EPSILON = 1e-12


def _linear_to_db(value: float) -> float:
    if value <= EPSILON:
        return float("-inf")
    return 20.0 * math.log10(value)


def _format_db(value: float) -> str:
    if not math.isfinite(value):
        return "−∞ dBFS"
    return f"{value:.1f} dBFS"


def _rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(finite, dtype=np.float64))))


def _peak(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    finite = samples[np.isfinite(samples)]
    if finite.size == 0:
        return 0.0
    return float(np.max(np.abs(finite)))


@dataclass(frozen=True)
class TimelineMarker:
    time_s: float
    name: str
    step: int = 0


@dataclass
class LoadedSignal:
    wav_path: Path
    run_dir: Path
    samples: np.ndarray
    sample_rate: int
    markers: list[TimelineMarker]
    action_start_s: float | None
    action_end_s: float | None
    metadata: dict
    quality: dict

    @property
    def duration_s(self) -> float:
        if self.sample_rate <= 0:
            return 0.0
        return float(self.samples.size / self.sample_rate)


class SignalCanvas(QWidget):
    selection_changed = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(390)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._samples = np.empty(0, dtype=np.float32)
        self._sample_rate = 1
        self._markers: list[TimelineMarker] = []
        self._action_start_s: float | None = None
        self._action_end_s: float | None = None
        self._view_start_s = 0.0
        self._view_end_s = 1.0
        self._selection_start_s: float | None = None
        self._selection_end_s: float | None = None
        self._drag_mode = ""
        self._drag_origin = QPoint()
        self._drag_view_start_s = 0.0
        self._drag_view_end_s = 1.0
        self._display_mode = "waveform"
        self._auto_scale = True
        self._spectrogram: QImage | None = None

    @property
    def duration_s(self) -> float:
        if self._sample_rate <= 0:
            return 0.0
        return float(self._samples.size / self._sample_rate)

    @property
    def selection(self) -> tuple[float, float] | None:
        if self._selection_start_s is None or self._selection_end_s is None:
            return None
        start = min(self._selection_start_s, self._selection_end_s)
        end = max(self._selection_start_s, self._selection_end_s)
        if end - start < 0.001:
            return None
        return start, end

    def set_signal(
        self,
        samples: np.ndarray,
        sample_rate: int,
        markers: list[TimelineMarker],
        action_start_s: float | None,
        action_end_s: float | None,
    ) -> None:
        self._samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        self._sample_rate = max(1, int(sample_rate))
        self._markers = list(markers)
        self._action_start_s = action_start_s
        self._action_end_s = action_end_s
        self._spectrogram = None
        self._selection_start_s = None
        self._selection_end_s = None
        self.reset_view()

    def clear(self) -> None:
        self._samples = np.empty(0, dtype=np.float32)
        self._markers = []
        self._action_start_s = None
        self._action_end_s = None
        self._spectrogram = None
        self._selection_start_s = None
        self._selection_end_s = None
        self._view_start_s = 0.0
        self._view_end_s = 1.0
        self.update()

    def set_display_mode(self, mode: str) -> None:
        self._display_mode = mode
        if mode == "spectrogram" and self._spectrogram is None:
            self._spectrogram = self._create_spectrogram()
        self.update()

    def set_auto_scale(self, enabled: bool) -> None:
        self._auto_scale = enabled
        self.update()

    def reset_view(self) -> None:
        duration = max(self.duration_s, 0.01)
        self._view_start_s = 0.0
        self._view_end_s = duration
        self.update()

    def clear_selection(self) -> None:
        self._selection_start_s = None
        self._selection_end_s = None
        self.selection_changed.emit(0.0, 0.0)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#080d14"))

        plot = QRectF(58.0, 20.0, max(20.0, self.width() - 76.0), max(20.0, self.height() - 54.0))
        painter.fillRect(plot, QColor("#0b111a"))

        if self._samples.size == 0:
            painter.setPen(QColor("#74849a"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Load a recorded WAV file to inspect its signal")
            painter.end()
            return

        if self._display_mode == "spectrogram":
            self._draw_spectrogram(painter, plot)
            self._draw_action_region(painter, plot)
            self._draw_grid(painter, plot)
        else:
            self._draw_action_region(painter, plot)
            self._draw_grid(painter, plot)
            self._draw_waveform(painter, plot)

        self._draw_selection(painter, plot)
        self._draw_markers(painter, plot)
        self._draw_axes(painter, plot)
        painter.end()

    def _draw_grid(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QPen(QColor("#1b2735"), 1))
        for index in range(1, 5):
            x = plot.left() + plot.width() * index / 5.0
            painter.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))
        for index in range(1, 4):
            y = plot.top() + plot.height() * index / 4.0
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

    def _draw_action_region(self, painter: QPainter, plot: QRectF) -> None:
        if self._action_start_s is None or self._action_end_s is None:
            return
        start = max(self._view_start_s, self._action_start_s)
        end = min(self._view_end_s, self._action_end_s)
        if end <= start:
            return
        left = self._time_to_x(start, plot)
        right = self._time_to_x(end, plot)
        painter.fillRect(
            QRectF(left, plot.top(), max(1.0, right - left), plot.height()),
            QColor(37, 99, 235, 28),
        )

    def _draw_waveform(self, painter: QPainter, plot: QRectF) -> None:
        start_index = max(0, int(self._view_start_s * self._sample_rate))
        end_index = min(self._samples.size, int(math.ceil(self._view_end_s * self._sample_rate)))
        visible = self._samples[start_index:end_index]
        if visible.size == 0:
            return

        finite = visible[np.isfinite(visible)]
        visible_peak = float(np.max(np.abs(finite))) if finite.size else 0.0
        if self._auto_scale:
            amplitude_limit = max(visible_peak * 1.12, 0.002)
            amplitude_limit = min(amplitude_limit, 1.0)
        else:
            amplitude_limit = 1.0

        center_y = plot.center().y()
        painter.setPen(QPen(QColor("#35465b"), 1))
        painter.drawLine(int(plot.left()), int(center_y), int(plot.right()), int(center_y))

        width = max(1, int(plot.width()))
        sample_edges = np.linspace(0, visible.size, width + 1, dtype=np.int64)
        painter.setPen(QPen(QColor("#79c8ff"), 1))

        scale = plot.height() * 0.48 / amplitude_limit
        for pixel in range(width):
            left_index = int(sample_edges[pixel])
            right_index = int(sample_edges[pixel + 1])
            if right_index <= left_index:
                right_index = min(visible.size, left_index + 1)
            segment = visible[left_index:right_index]
            if segment.size == 0:
                continue
            finite_segment = segment[np.isfinite(segment)]
            if finite_segment.size == 0:
                continue
            minimum = float(np.min(finite_segment))
            maximum = float(np.max(finite_segment))
            y_top = center_y - maximum * scale
            y_bottom = center_y - minimum * scale
            x = plot.left() + pixel
            painter.drawLine(int(x), int(y_top), int(x), int(y_bottom))

        painter.setPen(QColor("#8595aa"))
        painter.drawText(5, int(plot.top()) + 5, 48, 18, Qt.AlignmentFlag.AlignRight, f"{amplitude_limit:.3f}")
        painter.drawText(5, int(center_y) - 8, 48, 18, Qt.AlignmentFlag.AlignRight, "0")
        painter.drawText(5, int(plot.bottom()) - 17, 48, 18, Qt.AlignmentFlag.AlignRight, f"−{amplitude_limit:.3f}")
        painter.save()
        painter.translate(14, plot.center().y() + 42)
        painter.rotate(-90)
        painter.drawText(0, 0, "Amplitude (FS)")
        painter.restore()

    def _draw_spectrogram(self, painter: QPainter, plot: QRectF) -> None:
        image = self._spectrogram
        if image is None or image.isNull():
            painter.setPen(QColor("#74849a"))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "Spectrogram unavailable")
            return

        duration = max(self.duration_s, 0.001)
        source_left = max(0.0, min(1.0, self._view_start_s / duration)) * image.width()
        source_right = max(0.0, min(1.0, self._view_end_s / duration)) * image.width()
        source = QRectF(source_left, 0.0, max(1.0, source_right - source_left), float(image.height()))
        painter.drawImage(plot, image, source)

        nyquist = self._sample_rate / 2.0
        painter.setPen(QColor("#8595aa"))
        painter.drawText(4, int(plot.top()) + 5, 49, 18, Qt.AlignmentFlag.AlignRight, f"{nyquist / 1000.0:.1f}k")
        painter.drawText(4, int(plot.center().y()) - 8, 49, 18, Qt.AlignmentFlag.AlignRight, f"{nyquist / 2000.0:.1f}k")
        painter.drawText(4, int(plot.bottom()) - 17, 49, 18, Qt.AlignmentFlag.AlignRight, "0")
        painter.save()
        painter.translate(14, plot.center().y() + 34)
        painter.rotate(-90)
        painter.drawText(0, 0, "Frequency (Hz)")
        painter.restore()

    def _draw_selection(self, painter: QPainter, plot: QRectF) -> None:
        selection = self.selection
        if selection is None:
            return
        start, end = selection
        visible_start = max(start, self._view_start_s)
        visible_end = min(end, self._view_end_s)
        if visible_end <= visible_start:
            return
        left = self._time_to_x(visible_start, plot)
        right = self._time_to_x(visible_end, plot)
        painter.fillRect(
            QRectF(left, plot.top(), max(1.0, right - left), plot.height()),
            QColor(245, 190, 70, 35),
        )
        painter.setPen(QPen(QColor("#f2c66d"), 1))
        painter.drawLine(int(left), int(plot.top()), int(left), int(plot.bottom()))
        painter.drawLine(int(right), int(plot.top()), int(right), int(plot.bottom()))

    def _draw_markers(self, painter: QPainter, plot: QRectF) -> None:
        colours = {
            "SCAN_START": QColor("#60a5fa"),
            "SCAN_END": QColor("#60a5fa"),
            "PROBE_START": QColor("#a78bfa"),
            "PROBE_END": QColor("#a78bfa"),
            "PROBE_SEGMENT": QColor("#c4b5fd"),
            "WIDE_PROBE_START": QColor("#fb7185"),
            "WIDE_PROBE_END": QColor("#fb7185"),
            "WIDE_PROBE_SEGMENT": QColor("#fda4af"),
            "DIGIT_BOUNDARY": QColor("#7dd3fc"),
        }
        label_level = 0
        for marker in self._markers:
            if not (self._view_start_s <= marker.time_s <= self._view_end_s):
                continue
            colour = colours.get(marker.name, QColor("#8fa0b6"))
            x = self._time_to_x(marker.time_s, plot)
            painter.setPen(QPen(colour, 1))
            painter.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))
            text = marker.name.replace("_", " ")
            if marker.step:
                text = f"{text} · {marker.step}"
            painter.setPen(colour)
            y = int(plot.top()) + 4 + (label_level % 3) * 16
            painter.drawText(int(x) + 4, y, 170, 15, Qt.AlignmentFlag.AlignLeft, text)
            label_level += 1

    def _draw_axes(self, painter: QPainter, plot: QRectF) -> None:
        painter.setPen(QPen(QColor("#405168"), 1))
        painter.drawRect(plot)
        painter.setPen(QColor("#8595aa"))
        span = max(0.001, self._view_end_s - self._view_start_s)
        for index in range(6):
            fraction = index / 5.0
            x = plot.left() + plot.width() * fraction
            value = self._view_start_s + span * fraction
            painter.drawText(int(x) - 34, int(plot.bottom()) + 7, 68, 18, Qt.AlignmentFlag.AlignHCenter, f"{value:.3f}")
        painter.drawText(int(plot.center().x()) - 45, int(plot.bottom()) + 25, 90, 18, Qt.AlignmentFlag.AlignHCenter, "Time (s)")

    def _time_to_x(self, time_s: float, plot: QRectF) -> float:
        span = max(0.001, self._view_end_s - self._view_start_s)
        fraction = (time_s - self._view_start_s) / span
        return plot.left() + fraction * plot.width()

    def _x_to_time(self, x: float) -> float:
        plot_left = 58.0
        plot_width = max(20.0, self.width() - 76.0)
        fraction = (x - plot_left) / plot_width
        fraction = max(0.0, min(1.0, fraction))
        return self._view_start_s + fraction * (self._view_end_s - self._view_start_s)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        if self._samples.size == 0:
            return
        current_span = self._view_end_s - self._view_start_s
        duration = max(self.duration_s, 0.01)
        factor = 0.78 if event.angleDelta().y() > 0 else 1.28
        new_span = max(0.02, min(duration, current_span * factor))
        centre = self._x_to_time(event.position().x())
        ratio = (centre - self._view_start_s) / max(current_span, 0.001)
        start = centre - new_span * ratio
        end = start + new_span
        if start < 0.0:
            end -= start
            start = 0.0
        if end > duration:
            start -= end - duration
            end = duration
        self._view_start_s = max(0.0, start)
        self._view_end_s = min(duration, end)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._samples.size == 0:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            time_s = self._x_to_time(event.position().x())
            self._selection_start_s = time_s
            self._selection_end_s = time_s
            self._drag_mode = "select"
            self.update()
            event.accept()
            return
        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton}:
            self._drag_mode = "pan"
            self._drag_origin = event.position().toPoint()
            self._drag_view_start_s = self._view_start_s
            self._drag_view_end_s = self._view_end_s
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_mode == "select":
            self._selection_end_s = self._x_to_time(event.position().x())
            selection = self.selection
            if selection is not None:
                self.selection_changed.emit(*selection)
            self.update()
            event.accept()
            return
        if self._drag_mode == "pan":
            plot_width = max(20.0, self.width() - 76.0)
            span = self._drag_view_end_s - self._drag_view_start_s
            delta_s = -(event.position().x() - self._drag_origin.x()) / plot_width * span
            duration = max(self.duration_s, span)
            start = self._drag_view_start_s + delta_s
            end = self._drag_view_end_s + delta_s
            if start < 0.0:
                end -= start
                start = 0.0
            if end > duration:
                start -= end - duration
                end = duration
            self._view_start_s = max(0.0, start)
            self._view_end_s = min(duration, end)
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._drag_mode == "select":
            selection = self.selection
            if selection is None:
                self.clear_selection()
            else:
                self.selection_changed.emit(*selection)
        if self._drag_mode == "pan":
            self.unsetCursor()
        self._drag_mode = ""
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        self.reset_view()
        event.accept()

    def _create_spectrogram(self) -> QImage | None:
        samples = self._samples
        if samples.size < 64:
            return None
        n_fft = 1024 if samples.size >= 1024 else 2 ** int(math.floor(math.log2(samples.size)))
        n_fft = max(64, n_fft)
        hop = max(16, n_fft // 4)
        frame_count = 1 + max(0, (samples.size - n_fft) // hop)
        if frame_count <= 0:
            padded = np.pad(samples, (0, n_fft - samples.size))
            frames = padded.reshape(1, -1)
        else:
            shape = (frame_count, n_fft)
            strides = (samples.strides[0] * hop, samples.strides[0])
            frames = np.lib.stride_tricks.as_strided(samples, shape=shape, strides=strides).copy()

        window = np.hanning(n_fft).astype(np.float32)
        spectrum = np.fft.rfft(frames * window, axis=1)
        power_db = 20.0 * np.log10(np.abs(spectrum) + 1e-9)
        finite = power_db[np.isfinite(power_db)]
        if finite.size == 0:
            return None
        low = float(np.percentile(finite, 8.0))
        high = float(np.percentile(finite, 99.5))
        if high - low < 1.0:
            high = low + 1.0
        normalised = np.clip((power_db - low) / (high - low), 0.0, 1.0)
        pixels = np.ascontiguousarray(np.flipud((normalised.T * 255.0).astype(np.uint8)))
        height, width = pixels.shape
        image = QImage(pixels.data, width, height, pixels.strides[0], QImage.Format.Format_Indexed8)
        colour_table: list[int] = []
        for value in range(256):
            fraction = value / 255.0
            if fraction < 0.45:
                local = fraction / 0.45
                red = int(8 + 20 * local)
                green = int(13 + 70 * local)
                blue = int(20 + 120 * local)
            elif fraction < 0.8:
                local = (fraction - 0.45) / 0.35
                red = int(28 + 55 * local)
                green = int(83 + 130 * local)
                blue = int(140 + 90 * local)
            else:
                local = (fraction - 0.8) / 0.2
                red = int(83 + 172 * local)
                green = int(213 + 42 * local)
                blue = int(230 + 25 * local)
            colour_table.append(QColor(red, green, blue).rgb())
        image.setColorTable(colour_table)
        return image.copy()


class SignalReviewPanel(QWidget):
    def __init__(
        self,
        dataset_provider: Callable[[], Path],
        log: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset_provider = dataset_provider
        self._log = log
        self._loaded: LoadedSignal | None = None
        self._run_paths: list[Path] = []
        self._latest_run_hint: Path | None = None
        self._playback_token = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        toolbar = QFrame()
        toolbar.setObjectName("Card")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 13, 16, 13)
        toolbar_layout.setSpacing(9)
        self.dataset_label = QLabel("Dataset: —")
        self.dataset_label.setObjectName("SectionHint")
        self.dataset_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.refresh_button = QPushButton("List recent runs")
        self.latest_button = QPushButton("Load latest run")
        self.load_wav_button = QPushButton("Load WAV")
        self.open_run_button = QPushButton("Open run folder")
        toolbar_layout.addWidget(self.dataset_label, 1)
        toolbar_layout.addWidget(self.refresh_button)
        toolbar_layout.addWidget(self.latest_button)
        toolbar_layout.addWidget(self.load_wav_button)
        toolbar_layout.addWidget(self.open_run_button)
        layout.addWidget(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(3)

        list_card = QFrame()
        list_card.setObjectName("Card")
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(14, 14, 14, 14)
        list_layout.setSpacing(9)
        heading = QLabel("Recorded runs")
        heading.setObjectName("SectionTitle")
        list_layout.addWidget(heading)
        self.run_table = QTableWidget(0, 5)
        self.run_table.setHorizontalHeaderLabels(["Status", "Session", "Run", "Wheel", "Modified"])
        self.run_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.run_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.run_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.run_table.setAlternatingRowColors(True)
        self.run_table.verticalHeader().setVisible(False)
        self.run_table.verticalHeader().setDefaultSectionSize(31)
        header = self.run_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        list_layout.addWidget(self.run_table, 1)
        splitter.addWidget(list_card)

        viewer = QWidget()
        viewer_layout = QVBoxLayout(viewer)
        viewer_layout.setContentsMargins(10, 0, 0, 0)
        viewer_layout.setSpacing(12)

        viewer_card = QFrame()
        viewer_card.setObjectName("Card")
        viewer_card_layout = QVBoxLayout(viewer_card)
        viewer_card_layout.setContentsMargins(15, 14, 15, 15)
        viewer_card_layout.setSpacing(9)

        control_row = QHBoxLayout()
        self.file_title = QLabel("No recording loaded")
        self.file_title.setObjectName("SectionTitle")
        self.display_combo = QComboBox()
        self.display_combo.addItem("Waveform", "waveform")
        self.display_combo.addItem("Spectrogram", "spectrogram")
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("Auto amplitude", True)
        self.scale_combo.addItem("Full scale ±1", False)
        self.reset_view_button = QPushButton("Reset view")
        self.clear_selection_button = QPushButton("Clear selection")
        control_row.addWidget(self.file_title, 1)
        control_row.addWidget(self.display_combo)
        control_row.addWidget(self.scale_combo)
        control_row.addWidget(self.reset_view_button)
        control_row.addWidget(self.clear_selection_button)
        viewer_card_layout.addLayout(control_row)

        self.canvas = SignalCanvas()
        viewer_card_layout.addWidget(self.canvas, 1)

        help_label = QLabel(
            "Mouse wheel: zoom · Right/middle drag: pan · Left drag: measure a region · Double-click: reset"
        )
        help_label.setObjectName("SectionHint")
        viewer_card_layout.addWidget(help_label)
        viewer_layout.addWidget(viewer_card, 1)

        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(9)
        metrics_grid.setVerticalSpacing(9)
        self.metric_values: dict[str, QLabel] = {}
        metric_definitions = [
            ("Peak", "peak"),
            ("Whole RMS", "whole_rms"),
            ("Action RMS", "action_rms"),
            ("Background RMS", "noise_rms"),
            ("SNR", "snr"),
            ("Clipping", "clipping"),
        ]
        for index, (label, key) in enumerate(metric_definitions):
            card = QFrame()
            card.setObjectName("MetricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(2)
            name = QLabel(label.upper())
            name.setObjectName("MetricLabel")
            value = QLabel("—")
            value.setObjectName("StatusValue")
            value.setWordWrap(True)
            card_layout.addWidget(name)
            card_layout.addWidget(value)
            self.metric_values[key] = value
            metrics_grid.addWidget(card, index // 3, index % 3)
        viewer_layout.addLayout(metrics_grid)

        action_card = QFrame()
        action_card.setObjectName("Card")
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(14, 11, 14, 11)
        action_layout.setSpacing(9)
        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("Primary")
        self.stop_button = QPushButton("Stop")
        self.preview_gain_combo = QComboBox()
        for gain in (0, 6, 12, 18):
            self.preview_gain_combo.addItem(f"Preview gain +{gain} dB", gain)
        self.export_button = QPushButton("Export plot PNG")
        self.selection_label = QLabel("Selection: none")
        self.selection_label.setObjectName("SectionHint")
        action_layout.addWidget(self.play_button)
        action_layout.addWidget(self.stop_button)
        action_layout.addWidget(self.preview_gain_combo)
        action_layout.addWidget(self.export_button)
        action_layout.addStretch()
        action_layout.addWidget(self.selection_label)
        viewer_layout.addWidget(action_card)

        splitter.addWidget(viewer)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([390, 950])
        layout.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_runs)
        self.latest_button.clicked.connect(self.load_latest)
        self.load_wav_button.clicked.connect(self._choose_wav)
        self.open_run_button.clicked.connect(self._open_run_folder)
        self.run_table.itemSelectionChanged.connect(self._load_selected_row)
        self.display_combo.currentIndexChanged.connect(self._display_changed)
        self.scale_combo.currentIndexChanged.connect(self._scale_changed)
        self.reset_view_button.clicked.connect(self.canvas.reset_view)
        self.clear_selection_button.clicked.connect(self.canvas.clear_selection)
        self.canvas.selection_changed.connect(self._selection_changed)
        self.play_button.clicked.connect(self._play)
        self.stop_button.clicked.connect(self._stop_playback)
        self.export_button.clicked.connect(self._export_plot)

        self._update_button_state()

    def current_run_dir(self) -> Path | None:
        return self._loaded.run_dir if self._loaded is not None else None

    def set_latest_run_hint(self, run_dir: Path | None) -> None:
        """Remember the newest run without scanning the dataset.

        AppWindow calls this whenever a run completes.  Keeping this pointer is
        the key to making Signal Review O(1) on page entry: opening the page
        itself performs no filesystem walk and no metadata parsing.
        """
        self._latest_run_hint = Path(run_dir) if run_dir is not None else None
        self._update_button_state()

    def reset_dataset_view(self) -> None:
        """Clear list state after the dataset root changes, without scanning."""
        self._latest_run_hint = None
        self._run_paths = []
        self.run_table.blockSignals(True)
        try:
            self.run_table.setRowCount(0)
        finally:
            self.run_table.blockSignals(False)
        self.dataset_label.setText(f"Dataset: {self._resolved_dataset_path()}")
        self._set_status("Signal Review ready. Load the latest run or list recent runs when needed.")
        self._update_button_state()

    @staticmethod
    def _safe_mtime(path: Path) -> float:
        try:
            return float(path.stat().st_mtime)
        except (OSError, RuntimeError):
            return 0.0

    def _discover_recent_wavs(self, dataset: Path, current: Path | None = None) -> list[Path]:
        """Return a small list from one recent session only.

        This method is called only after an explicit user action (List recent
        runs / Load latest).  It never recursively walks the dataset.  If the
        App already knows the newest run, its session is used directly.
        Otherwise only immediate session directories under raw/rejected are
        inspected to choose the newest session.
        """
        max_rows = 180

        anchor_run = self._latest_run_hint
        session_dir: Path | None = None
        if anchor_run is not None:
            try:
                if (anchor_run / "audio.wav").is_file():
                    session_dir = anchor_run.parent
            except (OSError, RuntimeError):
                session_dir = None

        if session_dir is None:
            sessions: list[tuple[float, Path]] = []
            for branch in ("raw", "rejected"):
                root = dataset / branch
                try:
                    if not root.is_dir():
                        continue
                    for child in root.iterdir():
                        if child.is_dir():
                            sessions.append((self._safe_mtime(child), child))
                except (OSError, RuntimeError):
                    continue
            if sessions:
                sessions.sort(key=lambda item: item[0], reverse=True)
                session_dir = sessions[0][1]

        if session_dir is None:
            return []

        try:
            run_dirs = [entry for entry in session_dir.iterdir() if entry.is_dir()]
        except (OSError, RuntimeError):
            return []

        # Run names are normally monotonically numbered.  Sort by name first
        # and cap BEFORE any per-file stat/JSON work.
        run_dirs.sort(key=lambda path: path.name, reverse=True)
        wav_paths: list[Path] = []
        for run_dir in run_dirs[: max_rows * 2]:
            wav = run_dir / "audio.wav"
            try:
                if wav.is_file():
                    wav_paths.append(wav)
            except (OSError, RuntimeError):
                continue
            if len(wav_paths) >= max_rows:
                break

        # Put the hinted latest run first even if run naming is unusual.
        if anchor_run is not None:
            hinted = anchor_run / "audio.wav"
            try:
                if hinted.is_file():
                    wav_paths = [path for path in wav_paths if path != hinted]
                    wav_paths.insert(0, hinted)
            except (OSError, RuntimeError):
                pass

        if current is not None:
            current_wav = current / "audio.wav"
            try:
                if current_wav.is_file() and current_wav not in wav_paths:
                    wav_paths.append(current_wav)
            except (OSError, RuntimeError):
                pass
        return wav_paths

    def refresh_runs(self, preserve_current: bool = True) -> None:
        """Populate a bounded recent-run list after explicit user request.

        Deliberately avoids reading metadata.json for every row.  Metadata and
        the WAV are loaded only for the selected run.  This keeps the GUI
        responsive even when the dataset contains thousands of recordings.
        """
        current = self.current_run_dir() if preserve_current else None
        dataset = self._resolved_dataset_path()
        self.dataset_label.setText(f"Dataset: {dataset}")
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Listing…")
        try:
            wav_paths = self._discover_recent_wavs(dataset, current=current)
        except Exception as exc:
            self._set_status(f"Recent-run lookup failed safely: {exc}")
            wav_paths = []

        self._run_paths = [path.parent for path in wav_paths]
        self.run_table.blockSignals(True)
        self.run_table.setUpdatesEnabled(False)
        selected_row = -1
        try:
            self.run_table.setRowCount(len(wav_paths))
            for row, wav_path in enumerate(wav_paths):
                run_dir = wav_path.parent
                parts_lower = {part.lower() for part in run_dir.parts}
                status = "REJECTED" if "rejected" in parts_lower else "VALID"
                session = run_dir.parent.name
                run_id = run_dir.name
                # Wheel/metadata is intentionally loaded only when a row is
                # selected; bulk JSON parsing was a major source of UI stalls.
                values = [status, session, run_id, "—", ""]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 0:
                        item.setForeground(QColor("#f2c66d" if status == "REJECTED" else "#66d9a8"))
                    if column == 2:
                        item.setData(Qt.ItemDataRole.UserRole, str(run_dir))
                    self.run_table.setItem(row, column, item)
                if current is not None:
                    try:
                        if run_dir.resolve() == current.resolve():
                            selected_row = row
                    except (OSError, RuntimeError):
                        pass
        finally:
            self.run_table.blockSignals(False)
            self.run_table.setUpdatesEnabled(True)
            self.refresh_button.setText("List recent runs")
            self.refresh_button.setEnabled(True)

        if selected_row >= 0:
            self.run_table.selectRow(selected_row)
        if wav_paths:
            self._set_status(f"Listed {len(wav_paths)} run(s) from the most recent session.")
        else:
            self._set_status("No recent run list loaded. Use Load WAV to open a file directly.")
        self._update_button_state()

    def register_run(self, run_dir: Path) -> None:
        if not run_dir.exists():
            return
        self.refresh_runs(preserve_current=False)
        for row in range(self.run_table.rowCount()):
            item = self.run_table.item(row, 2)
            if item is None:
                continue
            stored = item.data(Qt.ItemDataRole.UserRole)
            if stored and Path(str(stored)).resolve() == run_dir.resolve():
                self.run_table.selectRow(row)
                self.load_run(run_dir)
                return

    def load_latest(self) -> None:
        hint = self._latest_run_hint
        if hint is not None:
            try:
                if (hint / "audio.wav").is_file():
                    self.load_run(hint)
                    return
            except (OSError, RuntimeError):
                pass

        dataset = self._resolved_dataset_path()
        self.dataset_label.setText(f"Dataset: {dataset}")
        wav_paths = self._discover_recent_wavs(dataset, current=None)
        if not wav_paths:
            self._set_status("No audio.wav files were found in the most recent session.")
            return
        self._latest_run_hint = wav_paths[0].parent
        self.load_run(self._latest_run_hint)
        self._update_button_state()

    def load_run(self, run_dir: Path) -> None:
        wav_path = run_dir / "audio.wav"
        try:
            exists = wav_path.is_file()
        except (OSError, RuntimeError):
            exists = False
        if not exists:
            self._set_status(f"WAV file not found or moved: {wav_path}")
            return
        self._load_wav(wav_path)

    def _load_wav(self, wav_path: Path) -> None:
        try:
            samples, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=True)
        except Exception as exc:
            self._set_status(f"Could not load WAV: {exc}")
            return
        if samples.size == 0:
            self._set_status("The selected WAV file is empty.")
            return
        mono = np.ascontiguousarray(samples[:, 0], dtype=np.float32)
        run_dir = wav_path.parent
        metadata = self._read_json(run_dir / "metadata.json")
        quality = self._read_json(run_dir / "quality.json")
        markers = self._read_markers(run_dir / "events.csv")
        action_start = next((m.time_s for m in markers if m.name in {"SCAN_START", "PROBE_START", "WIDE_PROBE_START"}), None)
        action_end = next((m.time_s for m in reversed(markers) if m.name in {"SCAN_END", "PROBE_END", "WIDE_PROBE_END"}), None)
        duration = mono.size / max(1, int(sample_rate))
        if action_start is not None:
            action_start = max(0.0, min(duration, action_start))
        if action_end is not None:
            action_end = max(0.0, min(duration, action_end))
        if action_start is not None and action_end is not None and action_end <= action_start:
            action_start = None
            action_end = None

        self._loaded = LoadedSignal(
            wav_path=wav_path,
            run_dir=run_dir,
            samples=mono,
            sample_rate=int(sample_rate),
            markers=markers,
            action_start_s=action_start,
            action_end_s=action_end,
            metadata=metadata,
            quality=quality,
        )
        self.canvas.set_signal(mono, int(sample_rate), markers, action_start, action_end)
        run = metadata.get("run", {}) if isinstance(metadata, dict) else {}
        run_id = str(run.get("run_id", run_dir.name))
        wheel = run.get("wheel_index")
        status = str(metadata.get("status", "")) if isinstance(metadata, dict) else ""
        suffix = f" · Wheel {wheel}" if wheel not in (None, "") else ""
        self.file_title.setText(f"{run_id}{suffix} · {status or 'WAV'}")
        self._update_metrics()
        self._selection_changed(0.0, 0.0)
        self._update_button_state()
        self._set_status(f"Loaded {wav_path.name}: {duration:.3f} s at {sample_rate} Hz")

    def _update_metrics(self) -> None:
        loaded = self._loaded
        if loaded is None:
            for value in self.metric_values.values():
                value.setText("—")
            return
        samples = loaded.samples
        peak = _peak(samples)
        whole_rms = _rms(samples)
        action_samples = self._slice(loaded.action_start_s, loaded.action_end_s)
        if action_samples.size == 0:
            action_samples = samples
        action_rms = _rms(action_samples)

        noise_parts: list[np.ndarray] = []
        guard_s = 0.015
        if loaded.action_start_s is not None and loaded.action_start_s > 0.035:
            noise_parts.append(self._slice(0.0, max(0.0, loaded.action_start_s - guard_s)))
        if loaded.action_end_s is not None and loaded.duration_s - loaded.action_end_s > 0.035:
            noise_parts.append(self._slice(min(loaded.duration_s, loaded.action_end_s + guard_s), loaded.duration_s))
        noise_parts = [part for part in noise_parts if part.size]
        noise_samples = np.concatenate(noise_parts) if noise_parts else np.empty(0, dtype=np.float32)
        noise_rms = _rms(noise_samples)
        snr = 20.0 * math.log10(action_rms / noise_rms) if action_rms > EPSILON and noise_rms > EPSILON else float("nan")
        clipped_count = int(np.count_nonzero(np.abs(samples) >= 0.999))
        clipped_ratio = clipped_count / samples.size if samples.size else 0.0

        self.metric_values["peak"].setText(f"{peak:.4f}  |  {_format_db(_linear_to_db(peak))}")
        self.metric_values["whole_rms"].setText(f"{whole_rms:.4f}  |  {_format_db(_linear_to_db(whole_rms))}")
        self.metric_values["action_rms"].setText(f"{action_rms:.4f}  |  {_format_db(_linear_to_db(action_rms))}")
        self.metric_values["noise_rms"].setText(
            f"{noise_rms:.4f}  |  {_format_db(_linear_to_db(noise_rms))}" if noise_samples.size else "No clean pre/post-roll"
        )
        self.metric_values["snr"].setText(f"{snr:.1f} dB" if math.isfinite(snr) else "Unavailable")
        self.metric_values["clipping"].setText(f"{clipped_count} samples  |  {clipped_ratio:.5%}")

    def _slice(self, start_s: float | None, end_s: float | None) -> np.ndarray:
        loaded = self._loaded
        if loaded is None or start_s is None or end_s is None or end_s <= start_s:
            return np.empty(0, dtype=np.float32)
        start = max(0, int(round(start_s * loaded.sample_rate)))
        end = min(loaded.samples.size, int(round(end_s * loaded.sample_rate)))
        return loaded.samples[start:end]

    def _selection_changed(self, start_s: float, end_s: float) -> None:
        selection = self.canvas.selection
        if selection is None or self._loaded is None:
            self.selection_label.setText("Selection: none")
            self.play_button.setText("Play")
            return
        start_s, end_s = selection
        samples = self._slice(start_s, end_s)
        peak = _peak(samples)
        rms = _rms(samples)
        self.selection_label.setText(
            f"Selection {start_s:.3f}–{end_s:.3f} s · {end_s - start_s:.3f} s · Peak {_format_db(_linear_to_db(peak))} · RMS {_format_db(_linear_to_db(rms))}"
        )
        self.play_button.setText("Play selection")

    def _display_changed(self) -> None:
        mode = str(self.display_combo.currentData())
        self.canvas.set_display_mode(mode)
        self.scale_combo.setEnabled(mode == "waveform")

    def _scale_changed(self) -> None:
        self.canvas.set_auto_scale(bool(self.scale_combo.currentData()))

    def _play(self) -> None:
        loaded = self._loaded
        if loaded is None:
            return
        selection = self.canvas.selection
        if selection is None:
            samples = loaded.samples
        else:
            samples = self._slice(*selection)
        if samples.size == 0:
            return
        gain_db = int(self.preview_gain_combo.currentData())
        multiplier = 10.0 ** (gain_db / 20.0)
        playback = np.clip(samples * multiplier, -1.0, 1.0).astype(np.float32)
        try:
            sd.stop()
            sd.play(playback, loaded.sample_rate, blocking=False)
        except Exception as exc:
            self._set_status(f"Playback failed: {exc}")
            return
        self._playback_token += 1
        token = self._playback_token
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        duration_ms = int(playback.size / loaded.sample_rate * 1000) + 150
        QTimer.singleShot(duration_ms, lambda: self._playback_finished(token))
        self._set_status(f"Playing raw recording with preview gain +{gain_db} dB. The WAV file is unchanged.")

    def _playback_finished(self, token: int) -> None:
        if token != self._playback_token:
            return
        self.play_button.setEnabled(self._loaded is not None)
        self.stop_button.setEnabled(False)

    def _stop_playback(self) -> None:
        self._playback_token += 1
        try:
            sd.stop()
        except Exception:
            pass
        self.play_button.setEnabled(self._loaded is not None)
        self.stop_button.setEnabled(False)
        self._set_status("Playback stopped")

    def _export_plot(self) -> None:
        loaded = self._loaded
        if loaded is None:
            return
        mode = str(self.display_combo.currentData())
        default = loaded.run_dir / f"{mode}_review.png"
        path, _ = QFileDialog.getSaveFileName(self, "Export signal plot", str(default), "PNG image (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if self.canvas.grab().save(path, "PNG"):
            self._set_status(f"Exported plot: {path}")
        else:
            self._set_status("Could not export the plot image.")

    def _choose_wav(self) -> None:
        dataset = self._resolved_dataset_path()
        path, _ = QFileDialog.getOpenFileName(self, "Load recorded WAV", str(dataset), "WAV audio (*.wav)")
        if path:
            self._load_wav(Path(path))

    def _load_selected_row(self) -> None:
        row = self.run_table.currentRow()
        if row < 0:
            return
        item = self.run_table.item(row, 2)
        if item is None:
            return
        stored = item.data(Qt.ItemDataRole.UserRole)
        if stored:
            run_dir = Path(str(stored))
            if self._loaded is not None and run_dir.resolve() == self._loaded.run_dir.resolve():
                return
            self.load_run(run_dir)

    def _open_run_folder(self) -> None:
        loaded = self._loaded
        if loaded is None:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(loaded.run_dir.resolve())))

    def _update_button_state(self) -> None:
        has_loaded = self._loaded is not None
        self.play_button.setEnabled(has_loaded)
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(has_loaded)
        self.open_run_button.setEnabled(has_loaded)
        self.reset_view_button.setEnabled(has_loaded)
        self.clear_selection_button.setEnabled(has_loaded)
        self.latest_button.setEnabled(
            self._latest_run_hint is not None
            or bool(self._run_paths)
            or self.run_table.rowCount() > 0
        )

    def _resolved_dataset_path(self) -> Path:
        path = Path(self._dataset_provider()).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _read_markers(path: Path) -> list[TimelineMarker]:
        if not path.exists():
            return []
        markers: list[TimelineMarker] = []
        try:
            with path.open("r", newline="", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    raw_time = row.get("aligned_audio_elapsed_s") or row.get("received_audio_elapsed_s") or ""
                    name = str(row.get("event", "")).strip()
                    if not raw_time or not name:
                        continue
                    try:
                        time_s = float(raw_time)
                        step = int(row.get("step", 0) or 0)
                    except (TypeError, ValueError):
                        continue
                    markers.append(TimelineMarker(time_s=time_s, name=name, step=step))
        except OSError:
            return []
        return markers

    def _set_status(self, message: str) -> None:
        self.selection_label.setText(message)
        if self._log is not None:
            self._log(message)
