"""Window lifecycle, settings, status and logging support for the GUI.

These methods are moved unchanged from ``MainWindow`` so the automatic
recognition and collection state machines can remain concentrated in
``app_window.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import ctypes
from pathlib import Path
import sys
import time

from PySide6.QtCore import QTimer, QUrl, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QShowEvent, QTextCursor
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app_dialogs import _themed_question, _themed_warning
from app_settings import APP_DIR
from config import WHEEL_STEPS_PER_DIGIT
from models import ActionType, ConfigSnapshot, StatusSnapshot


class WindowSupportMixin:
    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._window_fitted_once:
            self._window_fitted_once = True
            QTimer.singleShot(0, self._fit_window_to_screen)
        QTimer.singleShot(0, self._apply_native_dark_frame)

    def _fit_window_to_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        target_w = min(1540, max(1080, int(available.width() * 0.96)))
        target_h = min(940, max(700, int(available.height() * 0.94)))
        target_w = min(target_w, available.width())
        target_h = min(target_h, available.height())
        self.resize(target_w, target_h)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        top_left = frame.topLeft()
        top_left.setX(max(available.left(), top_left.x()))
        top_left.setY(max(available.top(), top_left.y()))
        self.move(top_left)

    def _apply_native_dark_frame(self) -> None:
        """Use the Windows DWM dark title bar while keeping native controls."""
        if sys.platform != "win32":
            return

        try:
            hwnd = int(self.winId())
            enabled = ctypes.c_int(1)
            dwm = ctypes.windll.dwmapi

            # Windows 11 uses 20; earlier builds may use 19.
            for attribute in (20, 19):
                result = dwm.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(enabled),
                    ctypes.sizeof(enabled),
                )
                if result == 0:
                    break

            def colorref(hex_color: str) -> int:
                value = hex_color.lstrip("#")
                red = int(value[0:2], 16)
                green = int(value[2:4], 16)
                blue = int(value[4:6], 16)
                return red | (green << 8) | (blue << 16)

            # Windows 11: border, caption and title text colours.
            for attribute, value in (
                (34, colorref("#080c12")),
                (35, colorref("#080c12")),
                (36, colorref("#e9eef7")),
            ):
                colour = ctypes.c_uint(value)
                dwm.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(colour),
                    ctypes.sizeof(colour),
                )
        except Exception:
            # DWM attributes vary by Windows build; the app remains usable.
            return

    def _digit_steps_changed(self, value: int) -> None:
        # Keep an already-generated preview consistent with the runtime value.
        if hasattr(self, "plan_table"):
            for row in range(self.plan_table.rowCount()):
                action_item = self.plan_table.item(row, 1)
                if action_item is None or "Digit" not in action_item.text():
                    continue
                steps_item = self.plan_table.item(row, 6)
                if steps_item is not None:
                    steps_item.setText(str(int(value)))

        if self._requests:
            self._requests = [
                replace(request, digit_steps=int(value))
                if request.action_type == ActionType.DIGIT_MOVE.value
                else request
                for request in self._requests
            ]

    def _collection_mode_changed(self) -> None:
        self.tension_combo.setEnabled(True)
        self.generate_plan_button.setText(
            "Generate ten-transition digit scan"
        )
        self._requests = []
        if hasattr(self, "plan_table"):
            self.plan_table.setRowCount(0)
            self.collection_state_label.setText("Plan settings changed")
        self._update_controls()

    def _current_code_values(self) -> list[int]:
        return [spin.value() for spin in self.current_digit_spins]

    def _current_code_text(self) -> str:
        return "".join(str(value) for value in self._current_code_values())

    def _apply_current_code(self, code: str, *, valid: bool) -> None:
        if len(code) != 4 or not code.isdigit():
            self._set_position_valid(False)
            return

        for spin, digit in zip(self.current_digit_spins, code):
            spin.blockSignals(True)
            spin.setValue(int(digit))
            spin.blockSignals(False)
        if hasattr(self, "manual_code_current_edit"):
            self.manual_code_current_edit.setText(code)
        self._set_position_valid(valid)

    def _set_position_valid(self, valid: bool) -> None:
        self._position_valid = valid
        if not hasattr(self, "position_status_label"):
            return
        if valid:
            self.position_status_label.setText(
                f"SYNCED  {self._current_code_text()}"
            )
            self.position_status_label.setStyleSheet(
                "background:#123329;color:#84e1b3;"
                "border:1px solid #275f4b;border-radius:9px;"
                "padding:7px 10px;font-weight:700;"
            )
        else:
            self.position_status_label.setText("NOT SYNCHRONISED")
            self.position_status_label.setStyleSheet(
                "background:#3b1e24;color:#ffb6c1;"
                "border:1px solid #713342;border-radius:9px;"
                "padding:7px 10px;font-weight:700;"
            )
        if hasattr(self, "auto_recognition_code_label"):
            self._update_auto_recognition_ui()

    def _invalidate_position(self, reason: str) -> None:
        was_valid = self._position_valid
        self._set_position_valid(False)
        self._requests = []
        if hasattr(self, "plan_table"):
            self.plan_table.setRowCount(0)
            self.collection_state_label.setText(
                "Synchronise the physical code before generating a plan"
            )
        if was_valid:
            self.append_log(f"Physical code invalidated: {reason}")
        self._update_controls()

    def _position_fields_changed(self, _value: int = 0) -> None:
        self._invalidate_position("code fields were edited")

    def _synchronise_position(self) -> None:
        code = self._current_code_text()
        confirmation = _themed_question(
            self,
            "Synchronise physical code",
            (
                f"Confirm that the four physical wheels currently read {code}.\n\n"
                "This app has no wheel-position encoder. The code will be tracked "
                "from motor steps until STOP, a failed run, or manual wheel movement."
            ),
        )
        if confirmation is QMessageBox.StandardButton.Yes:
            self._set_position_valid(True)
            self.append_log(f"Physical code synchronised to {code}")
            self._requests = []
            self.plan_table.setRowCount(0)
            self.collection_state_label.setText(
                "Position synchronised; generate a plan"
            )
            self._update_controls()

    def _apply_settings(self) -> None:
        self.session_id_edit.setText(
            f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        self.lock_id_edit.setText(self.settings.lock_id)
        self.scenario_edit.setText(self.settings.scenario)
        self.tape_edit.setText(self.settings.tape_version)
        self.microphone_edit.setText(self.settings.microphone_position)
        self.gain_edit.setText(self.settings.focusrite_gain)
        self.spring_edit.setText(self.settings.spring_setting)
        self.collection_direction.setCurrentText(self.settings.direction)
        self.repetitions_spin.setValue(self.settings.repetitions)
        self.digit_steps_spin.setValue(
            int(getattr(self.settings, "digit_steps", WHEEL_STEPS_PER_DIGIT))
        )
        self.keep_contact_check.setChecked(
            bool(getattr(self.settings, "keep_contact_between_digits", True))
        )
        saved_order: list[int] = []
        try:
            saved_order = [
                int(value)
                for value in str(self.settings.wheel_click_order).split(",")
                if value.strip()
            ]
        except ValueError:
            saved_order = []
        if (
            len(saved_order) != len(set(saved_order))
            or any(wheel not in {1, 2, 3, 4} for wheel in saved_order)
        ):
            saved_order = []

        self._wheel_collection_order = list(saved_order)
        for wheel, check in enumerate(self.wheel_checks, start=1):
            previous = check.blockSignals(True)
            check.setChecked(wheel in saved_order)
            check.blockSignals(previous)
        self._refresh_wheel_order_badges()

        mode_index = self.collection_mode_combo.findData(
            self.settings.collection_mode
        )
        if mode_index >= 0:
            self.collection_mode_combo.setCurrentIndex(mode_index)

        tension_index = self.tension_combo.findData(
            self.settings.tension_state
        )
        if tension_index >= 0:
            self.tension_combo.setCurrentIndex(tension_index)

        current_code = str(self.settings.current_code).strip()
        if len(current_code) == 4 and current_code.isdigit():
            for spin, digit in zip(self.current_digit_spins, current_code):
                spin.setValue(int(digit))
            if hasattr(self, "manual_code_current_edit"):
                self.manual_code_current_edit.setText(current_code)
        if hasattr(self, "manual_code_digit_steps_spin"):
            self.manual_code_digit_steps_spin.setValue(self.settings.digit_steps)

        true_code = str(getattr(self.settings, "decision_true_code", "1111")).strip()
        if len(true_code) != 4 or not true_code.isdigit():
            true_code = "1111"
        for spin, digit in zip(self.decision_true_digit_spins, true_code):
            spin.setValue(int(digit))

        self._set_position_valid(False)
        self.pre_roll_spin.setValue(self.settings.pre_roll_s)
        self.post_roll_spin.setValue(self.settings.post_roll_s)
        self.pause_spin.setValue(self.settings.pause_between_runs_s)
        self.stop_rejected_check.setChecked(self.settings.stop_on_rejected)

        dataset_path = Path(self.settings.dataset_dir)
        if not dataset_path.is_absolute():
            dataset_path = APP_DIR / dataset_path
        self.dataset_edit.setText(str(dataset_path.resolve()))

    def _save_settings(self) -> None:
        serial = self.serial_combo.currentData()
        audio = self.audio_combo.currentData()
        if serial is not None:
            self.settings.serial_port = serial.device
        if audio is not None:
            self.settings.audio_device = audio.index

        dataset_path = self._resolved_dataset_path()
        default_dataset = (APP_DIR / "dataset").resolve()
        if dataset_path == default_dataset:
            # Keep the default dataset path portable when the application directory moves.
            self.settings.dataset_dir = "dataset"
        else:
            self.settings.dataset_dir = str(dataset_path)
        self.settings.lock_id = self.lock_id_edit.text().strip()
        self.settings.scenario = self.scenario_edit.text().strip()
        self.settings.tape_version = self.tape_edit.text().strip()
        self.settings.microphone_position = self.microphone_edit.text().strip()
        self.settings.focusrite_gain = self.gain_edit.text().strip()
        self.settings.spring_setting = self.spring_edit.text().strip()
        self.settings.direction = self.collection_direction.currentText()
        self.settings.repetitions = self.repetitions_spin.value()
        self.settings.digit_steps = self.digit_steps_spin.value()
        self.settings.keep_contact_between_digits = self.keep_contact_check.isChecked()
        self.settings.collection_mode = str(
            self.collection_mode_combo.currentData()
        )
        self.settings.tension_state = str(
            self.tension_combo.currentData()
        )
        self.settings.wheel_click_order = ",".join(
            str(wheel) for wheel in self._wheel_collection_order
        )
        self.settings.current_code = self._current_code_text()
        self.settings.decision_true_code = "".join(
            str(spin.value()) for spin in self.decision_true_digit_spins
        )
        self.settings.pre_roll_s = self.pre_roll_spin.value()
        self.settings.post_roll_s = self.post_roll_spin.value()
        self.settings.pause_between_runs_s = self.pause_spin.value()
        self.settings.stop_on_rejected = self.stop_rejected_check.isChecked()
        self.settings.save()

    def _browse_dataset(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select dataset folder",
            str(self._resolved_dataset_path()),
        )
        if directory:
            self.dataset_edit.setText(directory)
            if hasattr(self, "signal_review_panel"):
                self.signal_review_panel.refresh_runs(preserve_current=False)

    def _resolved_dataset_path(self) -> Path:
        raw = self.dataset_edit.text().strip() if hasattr(self, "dataset_edit") else "dataset"
        path = Path(raw or "dataset").expanduser()
        if not path.is_absolute():
            path = APP_DIR / path
        return path.resolve()

    def _open_dataset(self) -> None:
        path = self._resolved_dataset_path()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_latest_review(self) -> None:
        self._navigate(self.SIGNAL_REVIEW_PAGE_INDEX)
        if self._latest_review_dir is not None and self._latest_review_dir.exists():
            self.signal_review_panel.load_run(self._latest_review_dir)
        else:
            self.signal_review_panel.load_latest()

    def _status_result(self, result: object) -> None:
        status, device_config = result  # type: ignore[misc]
        self._update_status(status, device_config)

    def _update_status(
        self,
        status: StatusSnapshot,
        device_config: ConfigSnapshot,
    ) -> None:
        values = {
            "acquisition_state": status.acquisition_state,
            "fault": status.fault,
            "rail_homed": self._bool_text(status.rail_homed),
            "limit_triggered": self._bool_text(status.limit_triggered),
            "rail_position": str(status.rail_position),
            "collection_ready": self._bool_text(device_config.collection_ready),
            "servo_configured": self._bool_text(device_config.servo_configured),
            "wheel_configured": self._bool_text(device_config.wheel_configured),
            "rail_configured": self._bool_text(device_config.rail_configured),
            "auto_enabled": self._bool_text(device_config.auto_enabled),
        }
        for key, value in values.items():
            self.status_labels[key].setText(value)

        self.state_badge.setText(f"State  {status.acquisition_state}")
        if status.fault != "NONE":
            self.state_badge.setStyleSheet(
                "background:#4b1d27;color:#ffc0ca;border:1px solid #8d3446;border-radius:13px;padding:6px 11px;font-weight:700;"
            )
        else:
            self.state_badge.setStyleSheet("")

    def _clear_status(self) -> None:
        for label in self.status_labels.values():
            label.setText("—")
        self.state_badge.setText("State  IDLE")
        self.state_badge.setStyleSheet("")
        self.state_badge.setStyleSheet("")

    def _update_counter(self) -> None:
        self.counter_label.setText(
            f"Valid {self._valid_count} | "
            f"Rejected {self._rejected_count} | "
            f"Failed {self._failed_count}"
        )
        if hasattr(self, "valid_metric"):
            self.valid_metric.setText(str(self._valid_count))
            self.rejected_metric.setText(str(self._rejected_count))
            self.failed_metric.setText(str(self._failed_count))

    @Slot(str)
    def append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}"
        self._pending_log_lines.append(line)
        auto_store = getattr(self, "_auto_store", None)
        auto_active = bool(getattr(self, "_auto_recognition_active", False))
        if auto_store is not None and (auto_active or str(text).startswith("AUTO RECOGNITION")):
            try:
                auto_store.append_console_line(line)
            except Exception:
                # Logging failures must not interrupt acquisition or control flow.
                pass
        if not self._log_flush_timer.isActive():
            self._log_flush_timer.start(45)

    def _flush_logs(self) -> None:
        if not self._pending_log_lines:
            return

        lines = self._pending_log_lines
        self._pending_log_lines = []
        scroll_bar = self.log_box.verticalScrollBar()
        keep_at_bottom = (
            scroll_bar.value() >= scroll_bar.maximum() - 4
        )

        cursor = self.log_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.log_box.document().characterCount() > 1:
            cursor.insertText("\n")
        cursor.insertText("\n".join(lines))
        self.log_box.setTextCursor(cursor)

        if keep_at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())

    def _clear_log(self) -> None:
        self._pending_log_lines.clear()
        self.log_box.clear()

    def _show_busy_notice(self) -> None:
        active = self._active_task_name or "the current operation"
        message = f"{active} is still running — repeated click ignored"
        self.statusBar().showMessage(message, 2200)

        now = time.monotonic()
        if now - self._last_busy_notice_at >= 1.0:
            self.append_log(message)
            self._last_busy_notice_at = now

    def _update_task_elapsed(self) -> None:
        if (
            not self._task_running
            or self._task_started_at <= 0
            or not self._active_task_name
        ):
            self._task_elapsed_timer.stop()
            return

        elapsed = time.monotonic() - self._task_started_at

        if self._active_task_offline:
            self._set_operation_state(
                "busy",
                self._active_task_name,
                f"Local MAIN v8 analysis is running — {elapsed:.1f} s.",
            )
            return

        if elapsed < 2.0:
            detail = (
                f"Command sent. Waiting for the ESP32 response — "
                f"{elapsed:.1f} s"
            )
        elif elapsed < 5.0:
            detail = (
                f"ESP32 confirmation is pending — {elapsed:.1f} s. "
                "Repeated clicks are ignored."
            )
        else:
            detail = (
                f"No confirmation yet — {elapsed:.1f} s. The app is still "
                "listening; use EMERGENCY STOP if the hardware behaves "
                "unexpectedly."
            )

        self._set_operation_state(
            "busy",
            self._active_task_name,
            detail,
        )

    def _set_operation_state(
        self,
        state: str,
        title: str,
        detail: str,
    ) -> None:
        if not hasattr(self, "manual_operation_title"):
            return

        palette = {
            "ready": ("#0d1622", "#26364a", "#eaf1fb", "#7f91a8"),
            "busy": ("#10233e", "#2f6fbd", "#d8eaff", "#9fcfff"),
            "success": ("#102b24", "#25634f", "#c7f7e5", "#8fd9bd"),
            "warning": ("#332516", "#8a5a21", "#ffe0ab", "#d8b67c"),
            "error": ("#351821", "#8d3446", "#ffd1d8", "#e6a2ae"),
        }
        background, border, title_color, detail_color = palette.get(
            state,
            palette["ready"],
        )
        parent = self.manual_operation_title.parentWidget()
        if parent is not None:
            parent.setStyleSheet(
                f"QFrame#OperationStrip {{background:{background};"
                f"border:1px solid {border};border-radius:11px;}}"
            )
        self.manual_operation_title.setStyleSheet(
            f"color:{title_color};font-weight:700;"
        )
        self.manual_operation_detail.setStyleSheet(
            f"color:{detail_color};"
        )
        self.manual_operation_title.setText(title)
        self.manual_operation_detail.setText(detail)
        self.manual_operation_progress.setVisible(state == "busy")

    def _show_error(self, message: str) -> None:
        _themed_warning(self, "Padlock Collector", message)

    @staticmethod
    def _bool_text(value: bool) -> str:
        return "Yes" if value else "No"

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._collection_running:
            answer = _themed_question(
                self,
                "Collection is running",
                "Send an emergency stop and close the application?",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._csv_batch_active = False
            self.backend.emergency_stop(self.append_log)
        elif self._csv_batch_active:
            answer = _themed_question(
                self,
                "CSV batch is active",
                "Cancel the CSV batch and close the application?",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._csv_batch_active = False

        self._save_settings()
        self.backend.disconnect()
        event.accept()
