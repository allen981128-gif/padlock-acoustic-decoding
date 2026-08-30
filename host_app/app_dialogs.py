"""Reusable dark-theme dialogs and small UI widgets.

This module contains presentation-only controls shared by the main window.
Hardware orchestration and recognition state remain in ``app_window.py``.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from app_theme import APP_STYLE, DIALOG_STYLE

if TYPE_CHECKING:
    from app_window import MainWindow

def _prepare_themed_dialog(dialog: QDialog, *, width: int = 560) -> None:
    """Give modal workflow dialogs the same non-native dark shell as the App."""
    dialog.setObjectName(dialog.objectName() or "ThemedDialog")
    dialog.setModal(True)
    dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    dialog.setMinimumWidth(width)
    dialog.setStyleSheet(APP_STYLE + DIALOG_STYLE)


class _ThemedMessageDialog(QDialog):
    """Small dark modal used instead of Windows' light QMessageBox surface."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        body: str,
        kind: str = "info",
        primary_text: str = "OK",
        secondary_text: str | None = None,
        danger_primary: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ThemedDialog")
        _prepare_themed_dialog(self, width=540)
        self._accepted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        eyebrow = QLabel(
            "CONFIRMATION" if kind == "question" else ("ATTENTION" if kind == "warning" else "PADLOCK COLLECTOR")
        )
        eyebrow.setObjectName("DialogEyebrow")
        root.addWidget(eyebrow)

        title_label = QLabel(title)
        title_label.setObjectName("DialogTitle")
        title_label.setWordWrap(True)
        root.addWidget(title_label)

        body_label = QLabel(body)
        body_label.setObjectName("DialogBody")
        body_label.setWordWrap(True)
        body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(body_label)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch()

        if secondary_text is not None:
            secondary = QPushButton(secondary_text)
            secondary.setObjectName("DialogGhost")
            secondary.clicked.connect(self.reject)
            actions.addWidget(secondary)

        primary = QPushButton(primary_text)
        primary.setObjectName("DialogDanger" if danger_primary else "DialogPrimary")
        primary.clicked.connect(self._accept_choice)
        primary.setDefault(True)
        actions.addWidget(primary)
        root.addLayout(actions)

    def _accept_choice(self) -> None:
        self._accepted = True
        self.accept()

    @property
    def accepted_choice(self) -> bool:
        return self._accepted


def _themed_question(
    parent: QWidget | None,
    title: str,
    body: str,
    *,
    yes_text: str = "Continue",
    no_text: str = "Cancel",
    danger_yes: bool = False,
) -> QMessageBox.StandardButton:
    dialog = _ThemedMessageDialog(
        parent,
        title=title,
        body=body,
        kind="question",
        primary_text=yes_text,
        secondary_text=no_text,
        danger_primary=danger_yes,
    )
    dialog.exec()
    return (
        QMessageBox.StandardButton.Yes
        if dialog.accepted_choice
        else QMessageBox.StandardButton.No
    )


def _themed_warning(parent: QWidget | None, title: str, body: str) -> None:
    dialog = _ThemedMessageDialog(
        parent,
        title=title,
        body=body,
        kind="warning",
        primary_text="Got it",
    )
    dialog.exec()


def _themed_information(parent: QWidget | None, title: str, body: str) -> None:
    dialog = _ThemedMessageDialog(
        parent,
        title=title,
        body=body,
        kind="info",
        primary_text="Done",
    )
    dialog.exec()


def _themed_item_choice(
    parent: QWidget | None,
    title: str,
    body: str,
    items: list[str],
    default_index: int = 0,
) -> tuple[str, bool]:
    dialog = QDialog(parent)
    dialog.setObjectName("ThemedDialog")
    _prepare_themed_dialog(dialog, width=520)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(24, 22, 24, 22)
    root.setSpacing(14)

    eyebrow = QLabel("OPERATOR INPUT")
    eyebrow.setObjectName("DialogEyebrow")
    root.addWidget(eyebrow)
    heading = QLabel(title)
    heading.setObjectName("DialogTitle")
    heading.setWordWrap(True)
    root.addWidget(heading)
    note = QLabel(body)
    note.setObjectName("DialogBody")
    note.setWordWrap(True)
    root.addWidget(note)

    combo = QComboBox()
    combo.addItems(items)
    if items:
        combo.setCurrentIndex(max(0, min(default_index, len(items) - 1)))
    root.addWidget(combo)

    actions = QHBoxLayout()
    actions.addStretch()
    cancel = QPushButton("Cancel")
    cancel.setObjectName("DialogGhost")
    confirm = QPushButton("Confirm")
    confirm.setObjectName("DialogPrimary")
    confirm.setDefault(True)
    cancel.clicked.connect(dialog.reject)
    confirm.clicked.connect(dialog.accept)
    actions.addWidget(cancel)
    actions.addWidget(confirm)
    root.addLayout(actions)

    accepted = dialog.exec() == QDialog.DialogCode.Accepted
    return (combo.currentText() if accepted else "", accepted)


def _themed_choice(
    parent: QWidget | None,
    title: str,
    body: str,
    *,
    primary_key: str,
    primary_text: str,
    secondary_key: str,
    secondary_text: str,
    cancel_text: str = "Pause",
) -> str:
    dialog = QDialog(parent)
    dialog.setObjectName("ThemedDialog")
    _prepare_themed_dialog(dialog, width=560)
    result = {"key": ""}

    root = QVBoxLayout(dialog)
    root.setContentsMargins(24, 22, 24, 22)
    root.setSpacing(14)
    eyebrow = QLabel("OPERATOR CHECK")
    eyebrow.setObjectName("DialogEyebrow")
    root.addWidget(eyebrow)
    heading = QLabel(title)
    heading.setObjectName("DialogTitle")
    heading.setWordWrap(True)
    root.addWidget(heading)
    note = QLabel(body)
    note.setObjectName("DialogBody")
    note.setWordWrap(True)
    root.addWidget(note)

    actions = QHBoxLayout()
    actions.setSpacing(10)
    pause = QPushButton(cancel_text)
    pause.setObjectName("DialogGhost")
    secondary = QPushButton(secondary_text)
    secondary.setObjectName("Secondary")
    primary = QPushButton(primary_text)
    primary.setObjectName("DialogPrimary")

    def choose(key: str) -> None:
        result["key"] = key
        dialog.accept()

    pause.clicked.connect(dialog.reject)
    secondary.clicked.connect(lambda: choose(secondary_key))
    primary.clicked.connect(lambda: choose(primary_key))
    actions.addWidget(pause)
    actions.addStretch()
    actions.addWidget(secondary)
    actions.addWidget(primary)
    root.addLayout(actions)
    dialog.exec()
    return result["key"]


class CodeTransitionDialog(QDialog):
    """Human-in-the-loop assistant for moving between planned physical codes."""

    def __init__(
        self,
        window: "MainWindow",
        *,
        current_code: str,
        planned_code: str,
        next_key: str,
    ) -> None:
        super().__init__(window)
        self._window = window
        self._planned_code = planned_code
        self._next_key = next_key
        self._confirmed = False
        self._last_task_seen = False

        self.setWindowTitle(f"Set next physical code — {next_key}")
        self.setObjectName("CodeTransitionDialog")
        _prepare_themed_dialog(self, width=650)
        self.resize(680, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        eyebrow = QLabel("HUMAN CHECKPOINT")
        eyebrow.setObjectName("DialogEyebrow")
        root.addWidget(eyebrow)
        title = QLabel("Apply MAIN v8 prediction")
        title.setObjectName("DialogTitle")
        root.addWidget(title)
        intro = QLabel(
            "Move the lock to the predicted code, then visually verify all four wheels before the workflow continues."
        )
        intro.setObjectName("DialogBody")
        intro.setWordWrap(True)
        root.addWidget(intro)

        code_card = QFrame()
        code_card.setObjectName("DialogPanel")
        code_layout = QVBoxLayout(code_card)
        code_layout.setContentsMargins(16, 14, 16, 14)
        code_layout.setSpacing(8)

        labels = QHBoxLayout()
        current_caption = QLabel("CURRENT")
        current_caption.setObjectName("DialogEyebrow")
        target_caption = QLabel("MAIN v8 TARGET")
        target_caption.setObjectName("DialogEyebrow")
        labels.addWidget(current_caption)
        labels.addStretch()
        labels.addWidget(target_caption)
        code_layout.addLayout(labels)

        code_row = QHBoxLayout()
        self.current_label = QLabel(current_code)
        self.current_label.setObjectName("DialogCode")
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow = QLabel("→")
        arrow.setObjectName("DialogArrow")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plan_label = QLabel(planned_code)
        self.plan_label.setObjectName("DialogCode")
        self.plan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_row.addWidget(self.current_label, 1)
        code_row.addWidget(arrow)
        code_row.addWidget(self.plan_label, 1)
        code_layout.addLayout(code_row)

        self.target_edit = QLineEdit(planned_code)
        self.target_edit.setMaxLength(4)
        self.target_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.target_edit.setVisible(False)
        self.use_plan_button = QPushButton("Use plan code")
        self.use_plan_button.setVisible(False)
        root.addWidget(code_card)

        auto_card = QFrame()
        auto_card.setObjectName("DialogAccentPanel")
        auto_layout = QVBoxLayout(auto_card)
        auto_layout.setContentsMargins(14, 14, 14, 14)
        auto_layout.setSpacing(8)
        auto_title = QLabel("Automatic adjustment")
        auto_title.setObjectName("SectionTitle")
        auto_layout.addWidget(auto_title)
        self.auto_detail = QLabel(
            f"{window.digit_steps_spin.value()} steps / digit · shortest-path move · automatic pressure settle."
        )
        self.auto_detail.setObjectName("SectionHint")
        self.auto_detail.setWordWrap(True)
        auto_layout.addWidget(self.auto_detail)

        self.pressure_settle_spin = QDoubleSpinBox()
        self.pressure_settle_spin.setRange(0.0, 5.0)
        self.pressure_settle_spin.setDecimals(1)
        self.pressure_settle_spin.setSingleStep(0.1)
        self.pressure_settle_spin.setValue(1.0)
        self.pressure_settle_spin.setSuffix(" s")
        self.pressure_settle_spin.setToolTip(
            "Wait after SERVO DOWN completes before the wheel motor is allowed to rotate."
        )
        auto_layout.addWidget(
            self._mini_field(
                "Pressure settle after servo down",
                self.pressure_settle_spin,
            )
        )

        self.auto_button = QPushButton("Auto adjust to predicted code")
        self.auto_button.setObjectName("DialogPrimary")
        auto_layout.addWidget(self.auto_button)
        root.addWidget(auto_card)

        self.manual_toggle = QPushButton("Advanced manual correction")
        self.manual_toggle.setObjectName("DialogGhost")
        self.manual_toggle.setCheckable(True)
        root.addWidget(self.manual_toggle)

        manual_card = QFrame()
        manual_card.setObjectName("DialogPanel")
        manual_layout = QVBoxLayout(manual_card)
        manual_layout.setContentsMargins(14, 14, 14, 14)
        manual_layout.setSpacing(8)
        manual_title = QLabel("Manual correction")
        manual_title.setObjectName("SectionTitle")
        manual_layout.addWidget(manual_title)
        manual_hint = QLabel(
            "If any wheel is wrong after automatic adjustment, correct it here. "
            "The collection remains paused until you explicitly confirm the observed physical code."
        )
        manual_hint.setObjectName("SectionHint")
        manual_hint.setWordWrap(True)
        manual_layout.addWidget(manual_hint)

        manual_grid = QGridLayout()
        self.manual_wheel_combo = QComboBox()
        for wheel in range(1, 5):
            self.manual_wheel_combo.addItem(f"W{wheel}", wheel)
        self.goto_button = QPushButton("Raise + move to wheel")
        manual_grid.addWidget(self._mini_field("Wheel", self.manual_wheel_combo), 0, 0)
        manual_grid.addWidget(self.goto_button, 0, 1)

        self.servo_up_button = QPushButton("Servo up")
        self.servo_down_button = QPushButton("Servo down")
        manual_grid.addWidget(self.servo_up_button, 1, 0)
        manual_grid.addWidget(self.servo_down_button, 1, 1)

        self.cw_digit_button = QPushButton("CW 1 digit")
        self.ccw_digit_button = QPushButton("CCW 1 digit")
        manual_grid.addWidget(self.cw_digit_button, 2, 0)
        manual_grid.addWidget(self.ccw_digit_button, 2, 1)

        self.fine_steps_spin = QSpinBox()
        self.fine_steps_spin.setRange(1, 2000)
        self.fine_steps_spin.setValue(max(1, window.digit_steps_spin.value() // 10))
        self.cw_fine_button = QPushButton("CW fine jog")
        self.ccw_fine_button = QPushButton("CCW fine jog")
        manual_grid.addWidget(self._mini_field("Fine jog steps", self.fine_steps_spin), 3, 0)
        fine_buttons = QWidget()
        fine_buttons_layout = QHBoxLayout(fine_buttons)
        fine_buttons_layout.setContentsMargins(0, 0, 0, 0)
        fine_buttons_layout.addWidget(self.cw_fine_button)
        fine_buttons_layout.addWidget(self.ccw_fine_button)
        manual_grid.addWidget(fine_buttons, 3, 1)
        manual_layout.addLayout(manual_grid)
        manual_card.setVisible(False)
        self.manual_toggle.toggled.connect(manual_card.setVisible)
        self.manual_toggle.toggled.connect(
            lambda expanded: self.resize(680, 820 if expanded else 560)
        )
        root.addWidget(manual_card)

        verify_card = QFrame()
        verify_card.setObjectName("DialogPanel")
        verify_layout = QVBoxLayout(verify_card)
        verify_layout.setContentsMargins(14, 14, 14, 14)
        verify_layout.setSpacing(8)
        observed_title = QLabel("Observed physical code — set this only after looking at the lock")
        observed_title.setObjectName("FieldLabel")
        verify_layout.addWidget(observed_title)
        observed_grid = QGridLayout()
        self.observed_spins: list[QSpinBox] = []
        for index, digit in enumerate(current_code, start=1):
            spin = QSpinBox()
            spin.setRange(0, 9)
            spin.setValue(int(digit))
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.observed_spins.append(spin)
            observed_grid.addWidget(self._mini_field(f"W{index}", spin), 0, index - 1)
        verify_layout.addLayout(observed_grid)
        self.status_label = QLabel("Collection is paused. Automatic motion has not been visually confirmed.")
        self.status_label.setObjectName("SectionHint")
        self.status_label.setWordWrap(True)
        verify_layout.addWidget(self.status_label)
        root.addWidget(verify_card)

        actions = QHBoxLayout()
        self.cancel_button = QPushButton("Keep paused")
        self.cancel_button.setObjectName("DialogGhost")
        self.confirm_button = QPushButton("Confirm code & continue")
        self.confirm_button.setObjectName("DialogPrimary")
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.confirm_button)
        root.addLayout(actions)

        self._manual_controls = [
            self.target_edit,
            self.use_plan_button,
            self.pressure_settle_spin,
            self.auto_button,
            self.manual_wheel_combo,
            self.goto_button,
            self.servo_up_button,
            self.servo_down_button,
            self.cw_digit_button,
            self.ccw_digit_button,
            self.fine_steps_spin,
            self.cw_fine_button,
            self.ccw_fine_button,
            *self.observed_spins,
            self.confirm_button,
        ]

        self.use_plan_button.clicked.connect(
            lambda: self.target_edit.setText(self._planned_code)
        )
        self.auto_button.clicked.connect(self._auto_adjust)
        self.goto_button.clicked.connect(self._goto_selected_wheel)
        self.servo_up_button.clicked.connect(
            lambda: self._run_task(
                lambda log: self._window.backend.servo_up(log),
                "Raising servo",
            )
        )
        self.servo_down_button.clicked.connect(
            lambda: self._run_task(
                lambda log: self._window.backend.servo_down(log),
                "Lowering servo",
            )
        )
        self.cw_digit_button.clicked.connect(lambda: self._manual_digit("CW"))
        self.ccw_digit_button.clicked.connect(lambda: self._manual_digit("CCW"))
        self.cw_fine_button.clicked.connect(lambda: self._manual_fine("CW"))
        self.ccw_fine_button.clicked.connect(lambda: self._manual_fine("CCW"))
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self._confirm)

        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(120)
        self._busy_timer.timeout.connect(self._poll_task_state)
        self._busy_timer.start()

    @staticmethod
    def _mini_field(label: str, control: QWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        text = QLabel(label)
        text.setObjectName("FieldLabel")
        layout.addWidget(text)
        layout.addWidget(control)
        return box

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    def target_code(self) -> str | None:
        value = self.target_edit.text().strip()
        if len(value) != 4 or not value.isdigit():
            _themed_warning(self, "Invalid code", "Enter exactly four digits, 0-9.")
            return None
        if value != self._planned_code:
            _themed_warning(
                self,
                "Target does not match the workflow target",
                (
                    f"The current workflow requires physical code {self._planned_code}.\n\n"
                    f"You entered {value}. The workflow cannot continue with a different code."
                ),
            )
            return None
        return value

    def observed_code(self) -> str:
        return "".join(str(spin.value()) for spin in self.observed_spins)

    def _set_observed_code(self, code: str) -> None:
        if len(code) != 4 or not code.isdigit():
            return
        for spin, digit in zip(self.observed_spins, code):
            spin.setValue(int(digit))
        self.current_label.setText(code)

    def _run_task(self, function: Any, task_name: str, on_result: Any = None) -> None:
        if self._window._task_running or self._window._collection_running:
            return
        started = self._window._start_task(
            function,
            on_result=on_result,
            task_name=task_name,
            allow_when_disconnected=False,
        )
        if started:
            self._last_task_seen = True
            self.status_label.setText(f"{task_name}… collection remains paused.")
            self._set_local_controls(False)

    def _poll_task_state(self) -> None:
        busy = self._window._task_running or self._window._collection_running
        if busy:
            self._last_task_seen = True
            self._set_local_controls(False)
        elif self._last_task_seen:
            self._last_task_seen = False
            self._set_local_controls(True)
            if self._window._task_failed:
                self.status_label.setText(
                    "The last hardware command failed. Inspect the lock and use manual correction before confirming."
                )

    def _set_local_controls(self, enabled: bool) -> None:
        for control in self._manual_controls:
            control.setEnabled(enabled)
        self.cancel_button.setEnabled(enabled)

    def _auto_adjust(self) -> None:
        target = self.target_code()
        if target is None:
            return
        current = self.observed_code()
        steps = int(self._window.digit_steps_spin.value())
        settle_s = float(self.pressure_settle_spin.value())

        def completed(result: object) -> None:
            code = str(result)
            self._set_observed_code(code)
            self._window._apply_current_code(code, valid=False)
            self.status_label.setText(
                f"Automatic adjustment finished at expected code {code}. VISUALLY CHECK ALL FOUR WHEELS before confirming."
            )

        self._run_task(
            lambda log: self._window.backend.transition_to_code(
                current_digits=[int(v) for v in current],
                target_digits=[int(v) for v in target],
                digit_steps=steps,
                settle_delay_s=settle_s,
                log=log,
            ),
            f"Automatically setting code {current} → {target} (pressure settle {settle_s:.1f}s)",
            on_result=completed,
        )

    def _goto_selected_wheel(self) -> None:
        wheel = int(self.manual_wheel_combo.currentData())
        self._run_task(
            lambda log: self._window.backend.transition_goto_wheel(wheel, log),
            f"Moving to W{wheel}",
        )

    def _manual_digit(self, direction: str) -> None:
        wheel = int(self.manual_wheel_combo.currentData())
        steps = int(self._window.digit_steps_spin.value())

        def completed(_: object) -> None:
            current = self.observed_spins[wheel - 1].value()
            next_digit = (current - 1) % 10 if direction == "CW" else (current + 1) % 10
            self.observed_spins[wheel - 1].setValue(next_digit)
            self.current_label.setText(self.observed_code())
            self._window._apply_current_code(self.observed_code(), valid=False)
            self.status_label.setText(
                f"Manual {direction} one-digit move completed on W{wheel}. Visually verify the wheel."
            )

        self._run_task(
            lambda log: self._window.backend.wheel_jog(direction, steps, log),
            f"Manual W{wheel} {direction} one digit",
            on_result=completed,
        )

    def _manual_fine(self, direction: str) -> None:
        wheel = int(self.manual_wheel_combo.currentData())
        steps = int(self.fine_steps_spin.value())

        def completed(_: object) -> None:
            self._window._set_position_valid(False)
            self.status_label.setText(
                f"Fine jog {direction} {steps} steps completed on W{wheel}. "
                "The App cannot infer the exact digit from a partial move; set Observed physical code after looking at the lock."
            )

        self._run_task(
            lambda log: self._window.backend.wheel_jog(direction, steps, log),
            f"Manual W{wheel} {direction} fine jog {steps} steps",
            on_result=completed,
        )

    def _confirm(self) -> None:
        target = self.target_code()
        if target is None:
            return
        observed = self.observed_code()
        if observed != target:
            _themed_warning(
                self,
                "Observed code does not match target",
                f"Observed physical code is entered as {observed}, but the next plan requires {target}.",
            )
            return
        answer = _themed_question(
            self,
            "Confirm physical code",
            (
                "Visually check all four wheels on the physical lock.\n\n"
                f"Confirmed code: {target}"
            ),
            yes_text="Confirm & continue",
            no_text="Go back",
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        self._window._apply_current_code(target, valid=True)
        self._confirmed = True
        self.accept()


class OrderedCollectCheckBox(QCheckBox):
    """Checkbox whose blue indicator shows its selected run order."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._order_number: int | None = None
        self.setObjectName("OrderedCollect")

    def set_order_number(self, number: int | None) -> None:
        self._order_number = number
        self.update()

    def paintEvent(self, event: object) -> None:
        super().paintEvent(event)
        if not self.isChecked() or self._order_number is None:
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator,
            option,
            self,
        )

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setPen(QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(8.0)
        painter.setFont(font)
        painter.drawText(
            indicator,
            Qt.AlignmentFlag.AlignCenter,
            str(self._order_number),
        )


class CircleReviewDialog(QDialog):
    """Mandatory human checkpoint after every full 10-movement circle."""

    RETRY = 1
    CONTINUE = 2

    def __init__(
        self,
        parent: QWidget,
        *,
        wheel: int,
        direction: str,
        repeat_id: str,
        start_code: str,
        summary: dict[str, object],
    ) -> None:
        super().__init__(parent)
        self.choice = 0
        self.setWindowTitle(f"Review completed circle — W{wheel} {direction}-{repeat_id}")
        self.setObjectName("CircleReviewDialog")
        _prepare_themed_dialog(self, width=610)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)

        eyebrow = QLabel("CIRCLE COMPLETE · HUMAN CHECKPOINT")
        eyebrow.setObjectName("DialogEyebrow")
        root.addWidget(eyebrow)
        title = QLabel(f"W{wheel} · {direction}-{repeat_id}")
        title.setObjectName("DialogTitle")
        root.addWidget(title)

        intro = QLabel(
            "Review the physical lock and this 10-WAV acquisition. The workflow will not continue until you accept or re-record this circle."
        )
        intro.setObjectName("DialogBody")
        intro.setWordWrap(True)
        root.addWidget(intro)

        card = QFrame()
        card.setObjectName("DialogPanel")
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        rows = [
            ("Expected physical code", start_code),
            ("WAVs", f"{int(summary.get('count') or 0)} / 10"),
            ("VALID", str(int(summary.get('valid') or 0))),
            ("REJECTED", str(int(summary.get('rejected') or 0))),
            ("FAILED / ABORTED", str(int(summary.get('failed') or 0))),
            ("Target peak max", f"{float(summary.get('target_peak_max') or 0.0):.4f}"),
            ("Target clip max", f"{100.0 * float(summary.get('target_clip_max') or 0.0):.4f}%"),
            ("Reference clip max", f"{100.0 * float(summary.get('reference_clip_max') or 0.0):.4f}%"),
        ]
        for row, (label, value) in enumerate(rows):
            left = QLabel(label)
            left.setObjectName("FieldLabel")
            right = QLabel(value)
            right.setObjectName("ControlState")
            grid.addWidget(left, row, 0)
            grid.addWidget(right, row, 1)
        root.addWidget(card)

        all_valid = bool(summary.get("all_valid"))
        note = QLabel(
            "Continue accepts this circle into MAIN v8. Re-record deletes only these newly recorded run folders and repeats the same component."
            if all_valid
            else "This circle is incomplete or contains a rejected/failed WAV, so Continue is disabled. Re-record the circle."
        )
        note.setObjectName("SectionHint")
        note.setWordWrap(True)
        root.addWidget(note)

        actions = QHBoxLayout()
        retry = QPushButton("Re-record")
        retry.setObjectName("DialogDanger")
        cont = QPushButton("Accept & continue")
        cont.setObjectName("DialogPrimary")
        cont.setEnabled(all_valid)
        actions.addWidget(retry)
        actions.addStretch()
        actions.addWidget(cont)
        root.addLayout(actions)

        retry.clicked.connect(self._retry)
        cont.clicked.connect(self._continue)

    def _retry(self) -> None:
        self.choice = self.RETRY
        self.accept()

    def _continue(self) -> None:
        self.choice = self.CONTINUE
        self.accept()
