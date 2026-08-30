"""Static layout builders for the main application window.

This module owns widget construction and page layout only. Hardware control,
collection orchestration and recognition state remain in ``app_window.py``.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_dialogs import OrderedCollectCheckBox
from auto_recognition import (
    AUTO_MAX_RECOGNITION_PASSES,
    AUTO_RETRY_MARGIN_THRESHOLD,
    AUTO_WHEELS,
)
from config import WHEEL_STEPS_PER_DIGIT
from signal_review import SignalReviewPanel


class MainWindowUiMixin:
    """Presentation layer mixed into ``MainWindow``."""

    @staticmethod
    def _card() -> QFrame:
        frame = QFrame()
        frame.setObjectName("Card")
        return frame


    @staticmethod
    def _soft_card() -> QFrame:
        frame = QFrame()
        frame.setObjectName("SoftCard")
        return frame


    @staticmethod
    def _compact_card() -> QFrame:
        frame = QFrame()
        frame.setObjectName("CompactCard")
        frame.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        return frame


    @staticmethod
    def _section_header(title: str, hint: str = "") -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        layout.addWidget(title_label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("SectionHint")
            layout.addWidget(hint_label)
        layout.addStretch()
        return widget


    @staticmethod
    def _metric_card(label: str, value: str = "—") -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("MetricCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        label_widget = QLabel(label.upper())
        label_widget.setObjectName("MetricLabel")
        value_widget = QLabel(value)
        value_widget.setObjectName("MetricValue")
        layout.addWidget(label_widget)
        layout.addWidget(value_widget)
        return frame, value_widget


    @staticmethod
    def _field(label: str, control: QWidget) -> QWidget:
        widget = QWidget()
        widget.setMinimumWidth(0)
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        control.setMinimumWidth(0)
        control.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            control.sizePolicy().verticalPolicy(),
        )
        if isinstance(control, QComboBox):
            control.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            control.setMinimumContentsLength(8)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label_widget = QLabel(label)
        label_widget.setObjectName("FieldLabel")
        layout.addWidget(label_widget)
        layout.addWidget(control)
        return widget


    @staticmethod
    def _scroll_wrap(content: QWidget) -> QScrollArea:
        content.setObjectName("ScrollContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.viewport().setObjectName("ScrollViewport")
        scroll.viewport().setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        scroll.setWidget(content)
        return scroll


    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("ContentSurface")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        content_layout.addWidget(self._build_topbar())

        work_splitter = QSplitter(Qt.Orientation.Vertical)
        work_splitter.setChildrenCollapsible(False)
        work_splitter.setHandleWidth(2)

        self.pages = QStackedWidget()
        self.tabs = self.pages
        self.pages.addWidget(self._build_device_page())
        self.pages.addWidget(self._build_manual_page())
        self.pages.addWidget(self._build_collection_page())
        self.pages.addWidget(self._build_signal_review_page())
        self.pages.addWidget(self._build_recognition_page())
        work_splitter.addWidget(self.pages)

        work_splitter.addWidget(self._build_console())
        work_splitter.setStretchFactor(0, 1)
        work_splitter.setStretchFactor(1, 0)
        work_splitter.setSizes([820, 110])
        self.work_splitter = work_splitter

        content_layout.addWidget(work_splitter, 1)
        root_layout.addWidget(content, 1)
        self.setCentralWidget(root)

        self.statusBar().showMessage("Ready")
        self._navigate(0)


    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(10)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(3, 0, 3, 15)
        brand_layout.setSpacing(11)
        mark = QLabel("P")
        mark.setObjectName("BrandMark")
        brand_layout.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("Padlock Collector")
        name.setObjectName("BrandName")
        caption = QLabel("Acoustic research console")
        caption.setObjectName("BrandCaption")
        brand_text.addWidget(name)
        brand_text.addWidget(caption)
        brand_layout.addLayout(brand_text)
        layout.addWidget(brand)

        nav_caption = QLabel("WORKSPACE")
        nav_caption.setObjectName("MetricLabel")
        nav_caption.setContentsMargins(8, 2, 0, 3)
        layout.addWidget(nav_caption)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        for index, (icon, title, _) in enumerate(self.PAGE_INFO):
            button = QPushButton(f"{icon}    {title}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, page=index: self._navigate(page)
            )
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch()

        system_card = self._soft_card()
        system_layout = QVBoxLayout(system_card)
        system_layout.setContentsMargins(12, 11, 12, 11)
        system_layout.setSpacing(7)
        sys_title = QLabel("SYSTEM")
        sys_title.setObjectName("MetricLabel")
        self.sidebar_esp = QLabel("●  ESP32 offline")
        self.sidebar_audio = QLabel("●  Audio unchecked")
        self.sidebar_esp.setStyleSheet("color:#74849a;")
        self.sidebar_audio.setStyleSheet("color:#74849a;")
        system_layout.addWidget(sys_title)
        system_layout.addWidget(self.sidebar_esp)
        system_layout.addWidget(self.sidebar_audio)
        layout.addWidget(system_card)

        self.sidebar_emergency = QPushButton("EMERGENCY STOP")
        self.sidebar_emergency.setObjectName("Emergency")
        self.sidebar_emergency.setAutoRepeat(False)
        self.sidebar_emergency.clicked.connect(self._emergency_stop)
        layout.addWidget(self.sidebar_emergency)
        return sidebar


    def _build_topbar(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("TopBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(1)
        self.page_title = QLabel("Devices")
        self.page_title.setObjectName("PageTitle")
        self.page_subtitle = QLabel("Connection and system health")
        self.page_subtitle.setObjectName("PageSubtitle")
        title_layout.addWidget(self.page_title)
        title_layout.addWidget(self.page_subtitle)
        layout.addLayout(title_layout)
        layout.addStretch()

        self.esp_badge = QLabel("ESP32  Offline")
        self.esp_badge.setObjectName("Pill")
        self.audio_badge = QLabel("Audio  Not checked")
        self.audio_badge.setObjectName("Pill")
        self.state_badge = QLabel("State  IDLE")
        self.state_badge.setObjectName("Pill")
        layout.addWidget(self.esp_badge)
        layout.addWidget(self.audio_badge)
        layout.addWidget(self.state_badge)

        self.console_toggle_button = QPushButton("Console")
        self.console_toggle_button.setObjectName("Secondary")
        self.console_toggle_button.setCheckable(True)
        self.console_toggle_button.setChecked(True)
        self.console_toggle_button.clicked.connect(self._toggle_console)
        layout.addWidget(self.console_toggle_button)
        return frame


    def _build_console(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Live console")
        title.setObjectName("SectionTitle")
        hint = QLabel("ESP32 protocol, acquisition states and errors")
        hint.setObjectName("SectionHint")
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("IconButton")
        clear_button.clicked.connect(self._clear_log)
        header.addWidget(title)
        header.addWidget(hint)
        header.addStretch()
        header.addWidget(clear_button)
        layout.addLayout(header)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(92)
        layout.addWidget(self.log_box)
        self.console_panel = frame
        return frame


    def _toggle_console(self, checked: bool) -> None:
        self.console_panel.setVisible(checked)
        if checked:
            self.work_splitter.setSizes([760, 170])


    def _navigate(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        icon, title, subtitle = self.PAGE_INFO[index]
        del icon
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        if 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if (
            index == self.SIGNAL_REVIEW_PAGE_INDEX
            and hasattr(self, "signal_review_panel")
        ):
            self.signal_review_panel.refresh_runs(preserve_current=True)
        if index == 4 and hasattr(self, "recognition_session_combo"):
            self._refresh_recognition_sessions()


    def _page_shell(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("PageSurface")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        return page, layout


    def _build_device_page(self) -> QWidget:
        page, layout = self._page_shell()

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        metric_defs = [
            ("System state", "—", "acquisition_state"),
            ("Fault", "—", "fault"),
            ("Rail position", "—", "rail_position"),
            ("Collection ready", "—", "collection_ready"),
        ]
        self.status_labels: dict[str, QLabel] = {}
        for col, (label, value, key) in enumerate(metric_defs):
            card, value_label = self._metric_card(label, value)
            metrics.addWidget(card, 0, col)
            self.status_labels[key] = value_label
        layout.addLayout(metrics)

        body = QGridLayout()
        body.setHorizontalSpacing(16)
        body.setVerticalSpacing(16)

        connection_card = self._card()
        connection_layout = QVBoxLayout(connection_card)
        connection_layout.setContentsMargins(18, 17, 18, 18)
        connection_layout.setSpacing(14)
        connection_layout.addWidget(
            self._section_header(
                "Device connections",
                "Select the ESP32 and Focusrite interfaces",
            )
        )

        self.serial_combo = QComboBox()
        self.audio_combo = QComboBox()
        connection_layout.addWidget(self._field("ESP32 serial port", self.serial_combo))
        connection_layout.addWidget(self._field("Focusrite input", self.audio_combo))

        connect_actions = QHBoxLayout()
        self.refresh_devices_button = QPushButton("Scan devices")
        self.connect_button = QPushButton("Connect system")
        self.connect_button.setObjectName("Primary")
        self.disconnect_button = QPushButton("Disconnect")
        connect_actions.addWidget(self.refresh_devices_button)
        connect_actions.addWidget(self.connect_button, 1)
        connect_actions.addWidget(self.disconnect_button)
        connection_layout.addLayout(connect_actions)
        body.addWidget(connection_card, 0, 0)

        health_card = self._card()
        health_layout = QVBoxLayout(health_card)
        health_layout.setContentsMargins(18, 17, 18, 18)
        health_layout.setSpacing(14)
        health_layout.addWidget(
            self._section_header(
                "Hardware readiness",
                "Calibration and safety signals reported by ESP32",
            )
        )

        health_grid = QGridLayout()
        health_grid.setHorizontalSpacing(24)
        health_grid.setVerticalSpacing(12)
        health_fields = [
            ("rail_homed", "Rail homed"),
            ("limit_triggered", "Limit switch"),
            ("servo_configured", "Servo configured"),
            ("wheel_configured", "Wheel configured"),
            ("rail_configured", "Rail configured"),
            ("auto_enabled", "Auto acquisition"),
        ]
        for index, (key, title) in enumerate(health_fields):
            label = QLabel(title)
            label.setObjectName("FieldLabel")
            value = QLabel("—")
            value.setObjectName("StatusValue")
            row = index // 2
            col = (index % 2) * 2
            health_grid.addWidget(label, row, col)
            health_grid.addWidget(value, row, col + 1)
            self.status_labels[key] = value
        health_layout.addLayout(health_grid)
        health_layout.addStretch()

        health_actions = QHBoxLayout()
        self.check_status_button = QPushButton("Refresh status")
        self.limit_read_button = QPushButton("Read limit")
        self.reset_fault_button = QPushButton("Reset fault")
        self.reset_fault_button.setObjectName("Danger")
        health_actions.addWidget(self.check_status_button)
        health_actions.addWidget(self.limit_read_button)
        health_actions.addStretch()
        health_actions.addWidget(self.reset_fault_button)
        health_layout.addLayout(health_actions)
        body.addWidget(health_card, 0, 1)

        body.setColumnStretch(0, 1)
        body.setColumnStretch(1, 1)
        layout.addLayout(body, 1)

        self.refresh_devices_button.clicked.connect(self._refresh_devices)
        self.connect_button.clicked.connect(self._connect_devices)
        self.disconnect_button.clicked.connect(self._disconnect_devices)
        self.check_status_button.clicked.connect(self._refresh_status)
        self.limit_read_button.clicked.connect(self._read_limit)
        self.reset_fault_button.clicked.connect(self._reset_fault)
        return page


    def _build_manual_page(self) -> QWidget:
        page, layout = self._page_shell()

        operation_strip = QFrame()
        operation_strip.setObjectName("OperationStrip")
        operation_layout = QHBoxLayout(operation_strip)
        operation_layout.setContentsMargins(15, 11, 15, 11)
        operation_layout.setSpacing(12)

        operation_copy = QVBoxLayout()
        operation_copy.setSpacing(1)
        self.manual_operation_title = QLabel("Manual controls ready")
        self.manual_operation_title.setObjectName("OperationTitle")
        self.manual_operation_detail = QLabel(
            "One hardware command is accepted at a time. Repeated clicks are ignored safely."
        )
        self.manual_operation_detail.setObjectName("OperationDetail")
        operation_copy.addWidget(self.manual_operation_title)
        operation_copy.addWidget(self.manual_operation_detail)
        operation_layout.addLayout(operation_copy, 1)

        self.manual_operation_progress = QProgressBar()
        self.manual_operation_progress.setRange(0, 0)
        self.manual_operation_progress.setTextVisible(False)
        self.manual_operation_progress.setFixedWidth(150)
        self.manual_operation_progress.setFixedHeight(8)
        self.manual_operation_progress.hide()
        operation_layout.addWidget(self.manual_operation_progress)
        layout.addWidget(operation_strip)

        positioning = self._card()
        positioning_layout = QHBoxLayout(positioning)
        positioning_layout.setContentsMargins(16, 14, 16, 14)
        positioning_layout.setSpacing(10)

        position_copy = QVBoxLayout()
        position_copy.setSpacing(1)
        position_title = QLabel("Absolute positioning")
        position_title.setObjectName("SectionTitle")
        position_hint = QLabel("Home the rail or move directly to a calibrated wheel")
        position_hint.setObjectName("SectionHint")
        position_copy.addWidget(position_title)
        position_copy.addWidget(position_hint)
        positioning_layout.addLayout(position_copy)
        positioning_layout.addStretch()

        self.home_button = QPushButton("Home rail")
        self.home_button.setObjectName("Primary")
        self.home_button.setMinimumWidth(150)
        self.home_button.setAutoRepeat(False)
        positioning_layout.addWidget(self.home_button)

        self.goto_buttons: list[QPushButton] = []
        for wheel in range(1, 5):
            button = QPushButton(f"Wheel {wheel}")
            button.setMinimumWidth(105)
            button.setAutoRepeat(False)
            button.clicked.connect(
                lambda checked=False, value=wheel: self._goto_wheel(value)
            )
            self.goto_buttons.append(button)
            positioning_layout.addWidget(button)

        layout.addWidget(positioning)

        code_transition = self._card()
        code_transition_layout = QHBoxLayout(code_transition)
        code_transition_layout.setContentsMargins(18, 15, 18, 15)
        code_transition_layout.setSpacing(12)

        code_transition_copy = QVBoxLayout()
        code_transition_copy.setSpacing(3)
        code_transition_title = QLabel("Automatic code adjustment")
        code_transition_title.setObjectName("SectionTitle")
        code_transition_hint = QLabel(
            "Enter the code currently visible on the lock and the target code. "
            "The App moves each wheel by the shortest CW/CCW path without opening a new window."
        )
        code_transition_hint.setObjectName("SectionHint")
        code_transition_hint.setWordWrap(True)
        code_transition_copy.addWidget(code_transition_title)
        code_transition_copy.addWidget(code_transition_hint)
        code_transition_layout.addLayout(code_transition_copy, 1)

        self.manual_code_current_edit = QLineEdit()
        self.manual_code_current_edit.setMaxLength(4)
        self.manual_code_current_edit.setFixedWidth(92)
        self.manual_code_current_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.manual_code_current_edit.setPlaceholderText("0000")
        self.manual_code_current_edit.setToolTip(
            "Enter the four digits currently visible on the physical lock."
        )

        self.manual_code_target_edit = QLineEdit()
        self.manual_code_target_edit.setMaxLength(4)
        self.manual_code_target_edit.setFixedWidth(92)
        self.manual_code_target_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.manual_code_target_edit.setPlaceholderText("0000")
        self.manual_code_target_edit.setToolTip(
            "Enter the four-digit code that the lock should move to."
        )

        self.manual_code_digit_steps_spin = QSpinBox()
        self.manual_code_digit_steps_spin.setRange(1, 2000)
        self.manual_code_digit_steps_spin.setValue(WHEEL_STEPS_PER_DIGIT)
        self.manual_code_digit_steps_spin.setSuffix(" steps")
        self.manual_code_digit_steps_spin.setFixedWidth(112)
        self.manual_code_digit_steps_spin.setToolTip(
            "Motor steps per visible digit used by the automatic adjustment."
        )

        code_transition_layout.addWidget(
            self._field("Current code", self.manual_code_current_edit)
        )
        code_transition_layout.addWidget(
            self._field("Target code", self.manual_code_target_edit)
        )
        code_transition_layout.addWidget(
            self._field("Steps / digit", self.manual_code_digit_steps_spin)
        )

        self.manual_code_transition_button = QPushButton("Auto adjust")
        self.manual_code_transition_button.setObjectName("Primary")
        self.manual_code_transition_button.setMinimumWidth(145)
        self.manual_code_transition_button.setMinimumHeight(42)
        self.manual_code_transition_button.setAutoRepeat(False)
        code_transition_layout.addWidget(self.manual_code_transition_button)
        layout.addWidget(code_transition)

        controls = QGridLayout()
        controls.setHorizontalSpacing(14)
        controls.setVerticalSpacing(14)

        # Drive head: compact, no empty stretch area.
        actuator = self._compact_card()
        actuator.setMinimumHeight(205)
        actuator.setMaximumHeight(225)
        actuator_layout = QVBoxLayout(actuator)
        actuator_layout.setContentsMargins(18, 17, 18, 17)
        actuator_layout.setSpacing(12)
        actuator_layout.addWidget(
            self._section_header(
                "Drive head",
                "Servo lift and contact control",
            )
        )
        actuator_state = QLabel("Working positions: 80° raised  •  120° lowered")
        actuator_state.setObjectName("ControlState")
        actuator_state.setWordWrap(True)
        actuator_layout.addWidget(actuator_state)
        servo_actions = QGridLayout()
        servo_actions.setHorizontalSpacing(10)
        self.servo_up_button = QPushButton("Raise drive head")
        self.servo_up_button.setObjectName("Secondary")
        self.servo_up_button.setMinimumHeight(42)
        self.servo_up_button.setAutoRepeat(False)
        self.servo_down_button = QPushButton("Lower drive head")
        self.servo_down_button.setMinimumHeight(42)
        self.servo_down_button.setAutoRepeat(False)
        servo_actions.addWidget(self.servo_up_button, 0, 0)
        servo_actions.addWidget(self.servo_down_button, 0, 1)
        actuator_layout.addLayout(servo_actions)
        actuator_note = QLabel(
            "Raise before rail movement. Lower only when the selected wheel is aligned."
        )
        actuator_note.setObjectName("SectionHint")
        actuator_note.setWordWrap(True)
        actuator_layout.addWidget(actuator_note)
        controls.addWidget(actuator, 0, 0)

        # Wheel motor.
        wheel_card = self._compact_card()
        wheel_card.setMinimumHeight(205)
        wheel_card.setMaximumHeight(225)
        wheel_layout = QVBoxLayout(wheel_card)
        wheel_layout.setContentsMargins(18, 17, 18, 17)
        wheel_layout.setSpacing(12)
        wheel_layout.addWidget(
            self._section_header(
                "Wheel motor",
                "Rotate the active lock wheel",
            )
        )
        wheel_form = QGridLayout()
        wheel_form.setHorizontalSpacing(10)
        self.wheel_direction_combo = QComboBox()
        self.wheel_direction_combo.addItems(["CW", "CCW"])
        self.wheel_steps = QSpinBox()
        self.wheel_steps.setRange(1, 2000)
        self.wheel_steps.setValue(WHEEL_STEPS_PER_DIGIT)
        self.wheel_jog_button = QPushButton("Run wheel jog")
        self.wheel_jog_button.setObjectName("Primary")
        self.wheel_jog_button.setMinimumHeight(42)
        self.wheel_jog_button.setAutoRepeat(False)
        wheel_form.addWidget(
            self._field("Direction", self.wheel_direction_combo), 0, 0
        )
        wheel_form.addWidget(
            self._field(
                f"Step count ({WHEEL_STEPS_PER_DIGIT} = 1 digit)",
                self.wheel_steps,
            ), 0, 1
        )
        wheel_layout.addLayout(wheel_form)
        wheel_layout.addWidget(self.wheel_jog_button)
        controls.addWidget(wheel_card, 0, 1)

        # Rail motor.
        rail_card = self._compact_card()
        rail_card.setMinimumHeight(205)
        rail_card.setMaximumHeight(225)
        rail_layout = QVBoxLayout(rail_card)
        rail_layout.setContentsMargins(18, 17, 18, 17)
        rail_layout.setSpacing(12)
        rail_layout.addWidget(
            self._section_header(
                "Rail motor",
                "Relative positioning for calibration",
            )
        )
        rail_form = QGridLayout()
        rail_form.setHorizontalSpacing(10)
        self.rail_direction_combo = QComboBox()
        self.rail_direction_combo.addItems(["FWD", "REV"])
        self.rail_steps = QSpinBox()
        self.rail_steps.setRange(1, 100000)
        self.rail_steps.setValue(1000)
        self.rail_jog_button = QPushButton("Run rail jog")
        self.rail_jog_button.setObjectName("Primary")
        self.rail_jog_button.setMinimumHeight(42)
        self.rail_jog_button.setAutoRepeat(False)
        rail_form.addWidget(
            self._field("Direction", self.rail_direction_combo), 0, 0
        )
        rail_form.addWidget(
            self._field("Step count", self.rail_steps), 0, 1
        )
        rail_layout.addLayout(rail_form)
        rail_layout.addWidget(self.rail_jog_button)
        controls.addWidget(rail_card, 0, 2)

        controls.setColumnStretch(0, 1)
        controls.setColumnStretch(1, 1)
        controls.setColumnStretch(2, 1)
        layout.addLayout(controls)

        safety = self._card()
        safety_layout = QHBoxLayout(safety)
        safety_layout.setContentsMargins(18, 15, 18, 15)
        safety_layout.setSpacing(14)
        safety_copy = QVBoxLayout()
        safety_copy.setSpacing(3)
        safety_title = QLabel("Safety controls")
        safety_title.setObjectName("SectionTitle")
        safety_note = QLabel(
            "Controlled STOP requests an orderly shutdown. Emergency stop aborts active waits and audio immediately."
        )
        safety_note.setObjectName("SectionHint")
        safety_note.setWordWrap(True)
        safety_copy.addWidget(safety_title)
        safety_copy.addWidget(safety_note)
        safety_layout.addLayout(safety_copy, 1)

        self.stop_button = QPushButton("Controlled STOP")
        self.stop_button.setObjectName("Danger")
        self.stop_button.setMinimumWidth(170)
        self.stop_button.setAutoRepeat(False)
        self.emergency_button = QPushButton("EMERGENCY STOP")
        self.emergency_button.setObjectName("Emergency")
        self.emergency_button.setMinimumWidth(260)
        self.emergency_button.setAutoRepeat(False)
        safety_layout.addWidget(self.stop_button)
        safety_layout.addWidget(self.emergency_button)
        layout.addWidget(safety)
        layout.addStretch()

        self.home_button.clicked.connect(self._home)
        self.servo_up_button.clicked.connect(self._servo_up)
        self.servo_down_button.clicked.connect(self._servo_down)
        self.wheel_jog_button.clicked.connect(self._wheel_jog)
        self.rail_jog_button.clicked.connect(self._rail_jog)
        self.manual_code_transition_button.clicked.connect(
            self._manual_code_transition
        )
        self.stop_button.clicked.connect(self._normal_stop)
        self.emergency_button.clicked.connect(self._emergency_stop)
        return page


    def _build_collection_page(self) -> QWidget:
        page, page_layout = self._page_shell()

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)
        body_splitter.setHandleWidth(3)

        settings_content = QWidget()
        settings_content.setObjectName("ScrollContent")
        settings_content.setAttribute(
            Qt.WidgetAttribute.WA_StyledBackground, True
        )
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(0, 0, 8, 0)
        settings_layout.setSpacing(14)

        session_card = self._card()
        session_layout = QVBoxLayout(session_card)
        session_layout.setContentsMargins(17, 16, 17, 17)
        session_layout.setSpacing(11)
        session_layout.addWidget(
            self._section_header("Session metadata", "Saved with every sample")
        )
        self.session_id_edit = QLineEdit()
        self.lock_id_edit = QLineEdit()
        self.scenario_edit = QLineEdit()
        self.tape_edit = QLineEdit()
        self.microphone_edit = QLineEdit()
        self.gain_edit = QLineEdit()
        self.spring_edit = QLineEdit()

        session_grid = QGridLayout()
        session_grid.setHorizontalSpacing(10)
        session_grid.setVerticalSpacing(9)
        session_grid.setColumnStretch(0, 1)
        session_grid.setColumnStretch(1, 1)
        session_grid.setColumnMinimumWidth(0, 0)
        session_grid.setColumnMinimumWidth(1, 0)
        session_grid.addWidget(self._field("Session ID", self.session_id_edit), 0, 0, 1, 2)
        session_grid.addWidget(self._field("Lock ID", self.lock_id_edit), 1, 0)
        session_grid.addWidget(self._field("Scenario", self.scenario_edit), 1, 1)
        session_grid.addWidget(self._field("Tape version", self.tape_edit), 2, 0)
        session_grid.addWidget(self._field("Microphone position", self.microphone_edit), 2, 1)
        session_grid.addWidget(self._field("Focusrite gain", self.gain_edit), 3, 0)
        session_grid.addWidget(self._field("Spring setting", self.spring_edit), 3, 1)
        session_layout.addLayout(session_grid)
        settings_layout.addWidget(session_card)

        plan_card = self._card()
        plan_layout = QVBoxLayout(plan_card)
        plan_layout.setContentsMargins(17, 16, 17, 17)
        plan_layout.setSpacing(12)
        plan_layout.addWidget(
            self._section_header(
                "Acquisition plan",
                "Digit Scan collection and Decision Batch workflows",
            )
        )

        mode_card = self._soft_card()
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(12, 11, 12, 12)
        mode_layout.setSpacing(9)

        mode_badge = QLabel("Digit Scan acquisition")
        mode_badge.setObjectName("MetricLabel")
        mode_layout.addWidget(mode_badge)

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(9)
        mode_grid.setVerticalSpacing(9)
        self.collection_mode_combo = QComboBox()
        self.collection_mode_combo.addItem(
            "Digit scan — ten one-digit transitions",
            "digit_scan",
        )
        self.tension_combo = QComboBox()
        self.tension_combo.addItem("Unspecified", "UNSPECIFIED")
        self.tension_combo.addItem("Unloaded", "UNLOADED")
        self.tension_combo.addItem("Loaded", "LOADED")
        mode_grid.addWidget(
            self._field("Collection mode", self.collection_mode_combo),
            0,
            0,
            1,
            2,
        )
        mode_grid.addWidget(
            self._field("Tension state", self.tension_combo),
            1,
            0,
            1,
            2,
        )
        mode_layout.addLayout(mode_grid)
        plan_layout.addWidget(mode_card)

        position_card = self._soft_card()
        position_layout = QVBoxLayout(position_card)
        position_layout.setContentsMargins(12, 11, 12, 12)
        position_layout.setSpacing(8)
        position_header = QHBoxLayout()
        position_title = QLabel("Current physical code")
        position_title.setObjectName("FieldLabel")
        self.position_status_label = QLabel("NOT SYNCHRONISED")
        self.position_status_label.setObjectName("ControlState")
        self.sync_code_button = QPushButton("Synchronise")
        position_header.addWidget(position_title)
        position_header.addStretch()
        position_header.addWidget(self.position_status_label)
        position_header.addWidget(self.sync_code_button)
        position_layout.addLayout(position_header)

        current_code_grid = QGridLayout()
        current_code_grid.setHorizontalSpacing(8)
        current_code_grid.setVerticalSpacing(0)
        self.current_digit_spins: list[QSpinBox] = []
        for wheel in range(1, 5):
            spin = QSpinBox()
            spin.setRange(0, 9)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setMinimumWidth(0)
            self.current_digit_spins.append(spin)
            current_code_grid.addWidget(self._field(f"W{wheel}", spin), 0, wheel - 1)
            current_code_grid.setColumnStretch(wheel - 1, 1)
        position_layout.addLayout(current_code_grid)
        position_hint = QLabel(
            "Set the physical wheels to these digits, then press Synchronise. "
            "STOP, a failed run, or manual wheel jog invalidates the tracked code."
        )
        position_hint.setObjectName("SectionHint")
        position_hint.setWordWrap(True)
        position_layout.addWidget(position_hint)
        plan_layout.addWidget(position_card)

        self.wheel_checks: list[OrderedCollectCheckBox] = []
        self._wheel_collection_order = []
        wheel_grid = QGridLayout()
        wheel_grid.setHorizontalSpacing(9)
        wheel_grid.setVerticalSpacing(9)
        for wheel in range(1, 5):
            tile = self._soft_card()
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(11, 10, 11, 10)
            tile_layout.setSpacing(7)
            row_header = QHBoxLayout()
            title = QLabel(f"Wheel {wheel}")
            title.setObjectName("FieldLabel")
            check = OrderedCollectCheckBox("Collect")
            check.setChecked(False)
            self.wheel_checks.append(check)
            check.toggled.connect(
                lambda checked, wheel_index=wheel: self._wheel_collect_toggled(
                    wheel_index, checked
                )
            )
            row_header.addWidget(title)
            row_header.addStretch()
            row_header.addWidget(check)
            tile_layout.addLayout(row_header)
            wheel_grid.addWidget(tile, (wheel - 1) // 2, (wheel - 1) % 2)
        plan_layout.addLayout(wheel_grid)
        self._refresh_wheel_order_badges()

        plan_options = QGridLayout()
        self.collection_direction = QComboBox()
        self.collection_direction.addItems(["CW", "CCW"])
        self.repetitions_spin = QSpinBox()
        self.repetitions_spin.setRange(1, 100)
        self.repetitions_spin.setValue(3)
        self.digit_steps_spin = QSpinBox()
        self.digit_steps_spin.setRange(1, 2000)
        self.digit_steps_spin.setValue(WHEEL_STEPS_PER_DIGIT)
        self.digit_steps_spin.setSuffix(" steps")
        self.digit_steps_spin.setToolTip(
            "Motor steps for one visible digit. Default calibration is "
            f"{WHEEL_STEPS_PER_DIGIT}. This value is sent to the ESP32 for every Digit Scan movement."
        )
        self.digit_steps_spin.valueChanged.connect(self._digit_steps_changed)
        plan_options.addWidget(
            self._field("Direction", self.collection_direction),
            0,
            0,
        )
        plan_options.addWidget(
            self._field("Repetitions", self.repetitions_spin),
            0,
            1,
        )
        plan_options.addWidget(
            self._field("Steps / digit", self.digit_steps_spin),
            0,
            2,
        )
        plan_layout.addLayout(plan_options)

        self.keep_contact_check = QCheckBox(
            "Keep drive head down between consecutive digits on the same wheel"
        )
        self.keep_contact_check.setChecked(True)
        self.keep_contact_check.setToolTip(
            "When enabled, a 10-digit scan lowers the servo once, records each digit as a separate WAV, "
            "keeps contact between candidates, then raises before changing wheel or returning control."
        )
        plan_layout.addWidget(self.keep_contact_check)

        self.generate_plan_button = QPushButton("Generate acquisition plan")
        self.generate_plan_button.setObjectName("Primary")
        self.generate_plan_button.setMinimumHeight(38)
        plan_layout.addWidget(self.generate_plan_button)
        settings_layout.addWidget(plan_card)

        csv_card = self._card()
        csv_layout = QVBoxLayout(csv_card)
        csv_layout.setContentsMargins(17, 16, 17, 17)
        csv_layout.setSpacing(10)
        csv_layout.addWidget(
            self._section_header(
                "Plan-driven Batch",
                "Digit Scan true-gate collection or Binding Scan prefix/binding-state probes",
            )
        )

        self.csv_batch_mode_combo = QComboBox()
        self.csv_batch_mode_combo.addItem("Digit Scan Decision", "digit_scan")
        self.csv_batch_mode_combo.addItem("Binding Scan", "binding_scan")
        csv_layout.addWidget(self._field("Batch mode", self.csv_batch_mode_combo))

        csv_path_row = QHBoxLayout()
        self.csv_batch_path_edit = QLineEdit()
        self.csv_batch_path_edit.setReadOnly(True)
        self.csv_batch_import_button = QPushButton("Import plan")
        self.csv_batch_template_button = QPushButton("Save mode template")
        csv_path_row.addWidget(self.csv_batch_path_edit, 1)
        csv_path_row.addWidget(self.csv_batch_import_button)
        csv_path_row.addWidget(self.csv_batch_template_button)
        csv_layout.addLayout(csv_path_row)

        self.csv_batch_summary_label = QLabel("No plan-driven batch loaded")
        self.csv_batch_summary_label.setObjectName("SectionHint")
        self.csv_batch_summary_label.setWordWrap(True)
        csv_layout.addWidget(self.csv_batch_summary_label)

        self.csv_batch_password_guard_label = QLabel(
            "PLAN PASSWORD  —    |    APP CORRECT  —"
        )
        self.csv_batch_password_guard_label.setWordWrap(True)
        self.csv_batch_password_guard_label.setStyleSheet(
            "background:#2b2113;color:#ffd58a;border:1px solid #7a5a22;"
            "border-radius:9px;padding:9px 11px;font-weight:800;font-size:11pt;"
        )
        csv_layout.addWidget(self.csv_batch_password_guard_label)

        truth_box = QGroupBox("Known lock combination — password guard / metadata truth")
        truth_layout = QGridLayout(truth_box)
        truth_layout.setContentsMargins(10, 10, 10, 10)
        truth_layout.setHorizontalSpacing(8)
        truth_layout.setVerticalSpacing(5)
        truth_hint = QLabel(
            "Editable. These digits are the known lock combination and are stored with every plan-driven run. "
            "Binding Scan still preserves the exact planned physical start code, including deliberately wrong prefixes."
        )
        truth_hint.setObjectName("SectionHint")
        truth_hint.setWordWrap(True)
        truth_layout.addWidget(truth_hint, 0, 0, 1, 4)
        self.decision_true_digit_spins: list[QSpinBox] = []
        for wheel in range(1, 5):
            spin = QSpinBox()
            spin.setRange(0, 9)
            spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
            spin.setMinimumWidth(52)
            self.decision_true_digit_spins.append(spin)
            spin.valueChanged.connect(self._update_csv_password_guard_label)
            truth_layout.addWidget(self._field(f"W{wheel}", spin), 1, wheel - 1)
        csv_layout.addWidget(truth_box)

        csv_actions = QGridLayout()
        csv_actions.setHorizontalSpacing(8)
        csv_actions.setVerticalSpacing(8)
        self.csv_batch_start_button = QPushButton("Start Digit Scan Batch")
        self.csv_batch_start_button.setObjectName("Primary")
        self.csv_batch_pause_button = QPushButton("Pause after current")
        self.csv_batch_resume_selected_button = QPushButton("Start / resume from selected")
        self.csv_batch_delete_last_button = QPushButton("Delete last")
        self.csv_batch_delete_last_button.setObjectName("Danger")
        self.csv_batch_cancel_button = QPushButton("Cancel Plan Batch")
        self.csv_batch_cancel_button.setObjectName("Danger")
        csv_actions.addWidget(self.csv_batch_start_button, 0, 0, 1, 2)
        csv_actions.addWidget(self.csv_batch_pause_button, 1, 0)
        csv_actions.addWidget(self.csv_batch_resume_selected_button, 1, 1)
        csv_actions.addWidget(self.csv_batch_delete_last_button, 2, 0)
        csv_actions.addWidget(self.csv_batch_cancel_button, 2, 1)
        csv_actions.setColumnStretch(0, 1)
        csv_actions.setColumnStretch(1, 1)
        csv_layout.addLayout(csv_actions)
        settings_layout.addWidget(csv_card)

        audio_card = self._card()
        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(17, 16, 17, 17)
        audio_layout.setSpacing(11)
        audio_layout.addWidget(
            self._section_header("Audio and output", "Timing, storage and batch rules")
        )
        timing_grid = QGridLayout()
        self.pre_roll_spin = QDoubleSpinBox()
        self.pre_roll_spin.setRange(0.0, 10.0)
        self.pre_roll_spin.setSingleStep(0.1)
        self.pre_roll_spin.setSuffix(" s")
        self.post_roll_spin = QDoubleSpinBox()
        self.post_roll_spin.setRange(0.0, 10.0)
        self.post_roll_spin.setSingleStep(0.1)
        self.post_roll_spin.setSuffix(" s")
        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 30.0)
        self.pause_spin.setSingleStep(0.1)
        self.pause_spin.setSuffix(" s")
        timing_grid.addWidget(self._field("Pre-roll", self.pre_roll_spin), 0, 0)
        timing_grid.addWidget(self._field("Post-roll", self.post_roll_spin), 0, 1)
        timing_grid.addWidget(self._field("Digit interval", self.pause_spin), 0, 2)
        audio_layout.addLayout(timing_grid)

        self.dataset_edit = QLineEdit()
        self.browse_dataset_button = QPushButton("Browse")
        dataset_row = QHBoxLayout()
        dataset_row.addWidget(self.dataset_edit, 1)
        dataset_row.addWidget(self.browse_dataset_button)
        dataset_field = QWidget()
        dataset_field_layout = QVBoxLayout(dataset_field)
        dataset_field_layout.setContentsMargins(0, 0, 0, 0)
        dataset_field_layout.setSpacing(5)
        dataset_label = QLabel("Dataset folder")
        dataset_label.setObjectName("FieldLabel")
        dataset_field_layout.addWidget(dataset_label)
        dataset_field_layout.addLayout(dataset_row)
        audio_layout.addWidget(dataset_field)

        self.stop_rejected_check = QCheckBox("Stop batch when a sample is rejected")
        audio_layout.addWidget(self.stop_rejected_check)
        settings_layout.addWidget(audio_card)
        settings_layout.addStretch()

        settings_scroll = self._scroll_wrap(settings_content)
        settings_scroll.setMinimumWidth(360)
        settings_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        body_splitter.addWidget(settings_scroll)

        right = QWidget()
        right.setObjectName("ScrollContent")
        right.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(14)

        stats = QGridLayout()
        stats.setHorizontalSpacing(10)
        card, self.total_metric = self._metric_card("Planned runs", "0")
        stats.addWidget(card, 0, 0)
        card, self.valid_metric = self._metric_card("Valid", "0")
        stats.addWidget(card, 0, 1)
        card, self.rejected_metric = self._metric_card("Rejected", "0")
        stats.addWidget(card, 0, 2)
        card, self.failed_metric = self._metric_card("Failed", "0")
        stats.addWidget(card, 0, 3)
        right_layout.addLayout(stats)

        table_card = self._card()
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(16, 15, 16, 16)
        table_layout.setSpacing(10)
        table_layout.addWidget(
            self._section_header("Run queue", "Each row saves one WAV and metadata record")
        )
        self.plan_table = QTableWidget(0, 9)
        self.plan_table.setHorizontalHeaderLabels(
            [
                "Run",
                "Action",
                "Code before",
                "Code after",
                "Wheel",
                "Direction",
                "Steps",
                "Repeat",
                "Status",
            ]
        )
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.plan_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.setAlternatingRowColors(True)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.verticalHeader().setDefaultSectionSize(32)
        header = self.plan_table.horizontalHeader()
        # Avoid ResizeToContents: large batch previews otherwise trigger repeated full-table scans.
        preview_widths = [220, 150, 86, 86, 58, 78, 64, 68]
        for column, width in enumerate(preview_widths):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(column, width)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        table_layout.addWidget(self.plan_table, 1)
        right_layout.addWidget(table_card, 1)

        run_card = self._card()
        run_layout = QVBoxLayout(run_card)
        run_layout.setContentsMargins(16, 13, 16, 14)
        run_layout.setSpacing(9)
        state_row = QHBoxLayout()
        self.collection_state_label = QLabel("No plan generated")
        self.collection_state_label.setObjectName("SectionTitle")
        self.counter_label = QLabel("Valid 0 | Rejected 0 | Failed 0")
        self.counter_label.setObjectName("SectionHint")
        state_row.addWidget(self.collection_state_label)
        state_row.addStretch()
        state_row.addWidget(self.counter_label)
        run_layout.addLayout(state_row)
        self.collection_progress = QProgressBar()
        self.collection_progress.setRange(0, 1)
        self.collection_progress.setValue(0)
        run_layout.addWidget(self.collection_progress)

        actions = QHBoxLayout()
        self.start_collection_button = QPushButton("Start batch")
        self.start_collection_button.setObjectName("Primary")
        self.single_collection_button = QPushButton("Collect selected")
        self.stop_collection_button = QPushButton("Stop collection")
        self.stop_collection_button.setObjectName("Danger")
        self.open_dataset_button = QPushButton("Open dataset")
        self.review_latest_button = QPushButton("Review latest")
        self.review_latest_button.setObjectName("Secondary")
        actions.addWidget(self.start_collection_button, 1)
        actions.addWidget(self.single_collection_button)
        actions.addWidget(self.stop_collection_button)
        actions.addWidget(self.review_latest_button)
        actions.addWidget(self.open_dataset_button)
        run_layout.addLayout(actions)
        right_layout.addWidget(run_card)

        body_splitter.addWidget(right)
        body_splitter.setStretchFactor(0, 4)
        body_splitter.setStretchFactor(1, 6)
        body_splitter.setSizes([460, 760])
        page_layout.addWidget(body_splitter, 1)

        self.collection_mode_combo.currentIndexChanged.connect(
            self._collection_mode_changed
        )
        self.generate_plan_button.clicked.connect(self._generate_plan)
        self.csv_batch_mode_combo.currentIndexChanged.connect(self._csv_batch_mode_changed)
        self.csv_batch_import_button.clicked.connect(self._import_csv_batch_plan)
        self.csv_batch_template_button.clicked.connect(self._save_csv_batch_template)
        self.csv_batch_start_button.clicked.connect(self._start_csv_batch)
        self.csv_batch_pause_button.clicked.connect(self._pause_csv_batch)
        self.csv_batch_resume_selected_button.clicked.connect(self._start_csv_from_selected)
        self.csv_batch_delete_last_button.clicked.connect(self._delete_last_csv_candidate)
        self.csv_batch_cancel_button.clicked.connect(self._cancel_csv_batch)
        self.start_collection_button.clicked.connect(self._start_collection)
        self.single_collection_button.clicked.connect(self._start_selected_collection)
        self.stop_collection_button.clicked.connect(self._emergency_stop)
        self.browse_dataset_button.clicked.connect(self._browse_dataset)
        self.open_dataset_button.clicked.connect(self._open_dataset)
        self.review_latest_button.clicked.connect(self._open_latest_review)
        self.sync_code_button.clicked.connect(self._synchronise_position)
        for spin in self.current_digit_spins:
            spin.valueChanged.connect(self._position_fields_changed)

        self._collection_mode_changed()
        self._set_position_valid(False)
        return page


    def _build_signal_review_page(self) -> QWidget:
        page, layout = self._page_shell()
        self.signal_review_panel = SignalReviewPanel(
            dataset_provider=self._resolved_dataset_path,
            log=self.append_log,
            parent=page,
        )
        layout.addWidget(self.signal_review_panel, 1)
        return page


    def _build_recognition_page(self) -> QWidget:
        page, layout = self._page_shell()
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)

        hero = self._card()
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(20, 15, 20, 15)
        hero_layout.setSpacing(16)

        copy = QVBoxLayout()
        copy.setSpacing(4)
        title = QLabel("TRUE-GATE MAIN v8 ACCURACY")
        title.setObjectName("PageTitle")
        description = QLabel(
            "Frozen B01–B07 accuracy ensemble for W1 / W2 / W4. Primary mode: supervised unknown-lock recognition with a human checkpoint after every full circle."
        )
        description.setObjectName("PageSubtitle")
        description.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(description)

        self.recognition_model_badge = QLabel()
        self.recognition_model_badge.setObjectName("Pill")
        if self._true_gate_engine is not None:
            self.recognition_model_badge.setText("MODEL READY  •  FROZEN")
            self.recognition_model_badge.setStyleSheet(
                "background:#102b24;color:#b7f7df;border:1px solid #25634f;"
                "border-radius:13px;padding:5px 10px;font-weight:700;"
            )
        else:
            self.recognition_model_badge.setText("MODEL ERROR")
            self.recognition_model_badge.setStyleSheet(
                "background:#351821;color:#ffd1d8;border:1px solid #8d3446;"
                "border-radius:13px;padding:5px 10px;font-weight:700;"
            )
        copy.addWidget(self.recognition_model_badge, 0, Qt.AlignmentFlag.AlignLeft)
        hero_layout.addLayout(copy, 1)

        model_card = self._soft_card()
        model_card.setMinimumWidth(275)
        model_card.setMaximumWidth(330)
        model_layout = QVBoxLayout(model_card)
        model_layout.setContentsMargins(14, 11, 14, 11)
        model_layout.setSpacing(3)
        model_title = QLabel("Frozen model identity")
        model_title.setObjectName("SectionTitle")
        model_layout.addWidget(model_title)
        if self._true_gate_engine is not None:
            source_sha = self._true_gate_engine.source_model_sha256
            runtime_sha = self._true_gate_engine.runtime_sha256
            model_lines = [
                "Training   B01–B07 only",
                f"Source     {source_sha[:12]}…",
                f"Runtime    {runtime_sha[:12]}…",
                "Wheels      W1 / W2 / W4",
            ]
            self.recognition_model_detail = QLabel("\n".join(model_lines))
            self.recognition_model_detail.setToolTip(
                f"Source model SHA-256:\n{source_sha}\n\nRuntime NPZ SHA-256:\n{runtime_sha}"
            )
        else:
            self.recognition_model_detail = QLabel(
                self._true_gate_model_error or "Frozen model could not be loaded."
            )
        self.recognition_model_detail.setObjectName("SectionHint")
        self.recognition_model_detail.setWordWrap(True)
        model_layout.addWidget(self.recognition_model_detail)
        hero_layout.addWidget(model_card)
        layout.addWidget(hero)

        self.recognition_workspace = QFrame()
        self.recognition_workspace.setObjectName("RecognitionWorkspace")
        self.recognition_workspace.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        recognition_workspace_layout = QVBoxLayout(self.recognition_workspace)
        recognition_workspace_layout.setContentsMargins(0, 0, 0, 0)
        recognition_workspace_layout.setSpacing(0)

        recognition_tab_rail = QFrame()
        recognition_tab_rail.setObjectName("RecognitionTabRail")
        recognition_tab_layout = QHBoxLayout(recognition_tab_rail)
        recognition_tab_layout.setContentsMargins(10, 0, 10, 0)
        recognition_tab_layout.setSpacing(2)

        self.recognition_auto_tab_button = QPushButton("Automatic Recognition")
        self.recognition_auto_tab_button.setObjectName("RecognitionTab")
        self.recognition_auto_tab_button.setCheckable(True)
        self.recognition_offline_tab_button = QPushButton("Offline Validation")
        self.recognition_offline_tab_button.setObjectName("RecognitionTab")
        self.recognition_offline_tab_button.setCheckable(True)
        self.recognition_tab_group = QButtonGroup(self)
        self.recognition_tab_group.setExclusive(True)
        self.recognition_tab_group.addButton(self.recognition_auto_tab_button, 0)
        self.recognition_tab_group.addButton(self.recognition_offline_tab_button, 1)
        self.recognition_auto_tab_button.setChecked(True)
        recognition_tab_layout.addWidget(self.recognition_auto_tab_button)
        recognition_tab_layout.addWidget(self.recognition_offline_tab_button)
        recognition_tab_layout.addStretch(1)
        recognition_workspace_layout.addWidget(recognition_tab_rail)

        self.recognition_stack = QStackedWidget()
        self.recognition_stack.setObjectName("RecognitionStack")
        self.recognition_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        recognition_workspace_layout.addWidget(self.recognition_stack, 1)

        # -------- Automatic recognition tab --------
        auto_tab = QWidget()
        auto_tab.setObjectName("RecognitionPane")
        auto_tab_layout = QVBoxLayout(auto_tab)
        auto_tab_layout.setContentsMargins(18, 16, 18, 16)
        auto_tab_layout.setSpacing(12)

        auto_card = QFrame()
        auto_card.setObjectName("RecognitionSection")
        auto_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        auto_layout = QVBoxLayout(auto_card)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(12)
        auto_layout.addWidget(
            self._section_header(
                "Unknown-lock recognition",
                "W1 → W2 → W4 with a human checkpoint after every complete 10-WAV circle. Top-1 is tried first. If the full W3 sweep fails and any wheel margin is below the fixed retry threshold, the App performs one fresh randomized recognition pass before using ranked fallback. W3 uses the frozen Physical Unlock Detector v1 as an automatic stop trigger.",
            )
        )

        auto_session_row = QHBoxLayout()
        auto_session_row.setSpacing(10)
        auto_session_label = QLabel("Auto session")
        auto_session_label.setObjectName("FieldLabel")
        self.auto_recognition_session_edit = QLineEdit(
            "AUTO_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        self.auto_recognition_session_edit.setMinimumWidth(240)
        self.auto_recognition_new_session_button = QPushButton("New ID")
        self.auto_recognition_start_button = QPushButton("Start supervised recognition")
        self.auto_recognition_start_button.setObjectName("Primary")
        self.auto_recognition_stop_button = QPushButton("Stop workflow")
        self.auto_recognition_stop_button.setObjectName("Danger")
        self.auto_recognition_stop_button.setEnabled(False)
        auto_session_row.addWidget(auto_session_label)
        auto_session_row.addWidget(self.auto_recognition_session_edit, 1)
        auto_session_row.addWidget(self.auto_recognition_new_session_button)
        auto_session_row.addWidget(self.auto_recognition_start_button)
        auto_session_row.addWidget(self.auto_recognition_stop_button)
        auto_layout.addLayout(auto_session_row)

        auto_status_band = QFrame()
        auto_status_band.setObjectName("RecognitionStatusBand")
        auto_status_layout = QGridLayout(auto_status_band)
        auto_status_layout.setContentsMargins(10, 8, 10, 8)
        auto_status_layout.setHorizontalSpacing(8)
        auto_status_layout.setVerticalSpacing(7)
        self.auto_recognition_state_label = QLabel("IDLE")
        self.auto_recognition_state_label.setObjectName("ControlState")
        self.auto_recognition_code_label = QLabel("Current code: not synchronised")
        self.auto_recognition_code_label.setObjectName("ControlState")
        self.auto_recognition_circle_label = QLabel("Next circle: —")
        self.auto_recognition_circle_label.setObjectName("ControlState")
        self.auto_recognition_prediction_label = QLabel("Predicted: W1 ?   W2 ?   W3 ?   W4 ?")
        self.auto_recognition_prediction_label.setObjectName("ControlState")
        auto_status_layout.addWidget(self.auto_recognition_state_label, 0, 0)
        auto_status_layout.addWidget(self.auto_recognition_code_label, 0, 1)
        auto_status_layout.addWidget(self.auto_recognition_circle_label, 1, 0)
        auto_status_layout.addWidget(self.auto_recognition_prediction_label, 1, 1)
        auto_status_layout.setColumnStretch(0, 1)
        auto_status_layout.setColumnStretch(1, 1)
        auto_layout.addWidget(auto_status_band)

        self.auto_recognition_protocol_label = QLabel(
            "Unknown password: never requested or used. Before each A circle confirm a fresh loaded-shackle reseat. "
            "Order: CCW-A → CCW-B → CW-A → CW-B. After each full circle choose Re-record or Continue. "
            "For W3, the App continuously records one WAV per CCW digit, checks Unlock Detector v1 after each movement, and stops only on a detector trigger or after 10 positions. Audio only triggers the pause; the operator confirms whether the lock is physically open. "
            f"If Top-1 fails and the minimum W1/W2/W4 margin is below {AUTO_RETRY_MARGIN_THRESHOLD:.2f}, one fresh randomized pass is run (maximum {AUTO_MAX_RECOGNITION_PASSES} passes). Ranked Top-2 fallback is retained only after that bounded retry logic. Each AUTO result folder contains a full JSONL flow log and final run summary."
        )
        self.auto_recognition_protocol_label.setObjectName("SectionHint")
        self.auto_recognition_protocol_label.setWordWrap(True)
        auto_layout.addWidget(self.auto_recognition_protocol_label)

        self.auto_recognition_table = QTableWidget(3, 6)
        self.auto_recognition_table.setHorizontalHeaderLabels(
            ["Wheel", "Top-1", "Top-2", "Top-3", "Margin", "State"]
        )
        self.auto_recognition_table.verticalHeader().setVisible(False)
        self.auto_recognition_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.auto_recognition_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.auto_recognition_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.auto_recognition_table.setMinimumHeight(205)
        self.auto_recognition_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.auto_recognition_table.setStyleSheet(
            "QTableWidget { border: 1px solid #1d2a39; border-radius: 10px; }"
            "QHeaderView::section { border-top: 0; }"
        )
        for row, wheel in enumerate(AUTO_WHEELS):
            values = [f"W{wheel}", "—", "—", "—", "—", "WAITING"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.auto_recognition_table.setItem(row, column, item)
        auto_layout.addWidget(self.auto_recognition_table, 1)

        self.auto_recognition_status_label = QLabel(
            "Synchronise the visible physical code in Data Collection, connect ESP32 + audio, apply normal shackle tension, then start."
        )
        self.auto_recognition_status_label.setObjectName("SectionHint")
        self.auto_recognition_status_label.setWordWrap(True)
        auto_layout.addWidget(self.auto_recognition_status_label)
        auto_tab_layout.addWidget(auto_card, 1)

        self.auto_recognition_new_session_button.clicked.connect(self._auto_new_session_id)
        self.auto_recognition_start_button.clicked.connect(self._start_or_resume_auto_recognition)
        self.auto_recognition_stop_button.clicked.connect(self._stop_auto_recognition)

        # -------- Offline validation tab --------
        offline_tab = QWidget()
        offline_tab.setObjectName("RecognitionPane")
        offline_layout = QVBoxLayout(offline_tab)
        offline_layout.setContentsMargins(18, 16, 18, 16)
        offline_layout.setSpacing(12)

        control_card = self._card()
        control_layout = QVBoxLayout(control_card)
        control_layout.setContentsMargins(18, 15, 18, 16)
        control_layout.setSpacing(10)
        control_layout.addWidget(
            self._section_header(
                "Offline validation / saved-session scoring",
                "Optional research tool for completed MAIN-v8-compatible sessions.",
            )
        )

        session_row = QHBoxLayout()
        session_label = QLabel("Session")
        session_label.setObjectName("FieldLabel")
        self.recognition_session_combo = QComboBox()
        self.recognition_session_combo.setEditable(True)
        self.recognition_session_combo.setMinimumWidth(280)
        self.recognition_use_collection_button = QPushButton("Use collection session")
        self.recognition_refresh_button = QPushButton("Refresh")
        self.recognition_score_button = QPushButton("Score session")
        self.recognition_score_button.setObjectName("Primary")
        self.recognition_open_results_button = QPushButton("Open results")
        self.recognition_open_results_button.setEnabled(False)
        session_row.addWidget(session_label)
        session_row.addWidget(self.recognition_session_combo, 1)
        session_row.addWidget(self.recognition_use_collection_button)
        session_row.addWidget(self.recognition_refresh_button)
        session_row.addWidget(self.recognition_score_button)
        session_row.addWidget(self.recognition_open_results_button)
        control_layout.addLayout(session_row)

        self.recognition_protocol_label = QLabel(
            "Prediction is computed first from audio + known direction + wheel identity. Stored correct digits are attached only afterwards for accuracy reporting."
        )
        self.recognition_protocol_label.setObjectName("SectionHint")
        self.recognition_protocol_label.setWordWrap(True)
        control_layout.addWidget(self.recognition_protocol_label)
        offline_layout.addWidget(control_card)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)
        profile_card, self.recognition_profiles_metric = self._metric_card("Profiles scored", "—")
        top1_card, self.recognition_top1_metric = self._metric_card("Top-1 accuracy", "—")
        top2_card, self.recognition_top2_metric = self._metric_card("Top-2 accuracy", "—")
        top3_card, self.recognition_top3_metric = self._metric_card("Top-3 accuracy", "—")
        metrics.addWidget(profile_card, 0, 0)
        metrics.addWidget(top1_card, 0, 1)
        metrics.addWidget(top2_card, 0, 2)
        metrics.addWidget(top3_card, 0, 3)
        offline_layout.addLayout(metrics)

        result_card = self._card()
        result_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(16, 14, 16, 16)
        result_layout.setSpacing(9)
        header = QHBoxLayout()
        result_header_label = QLabel("Profile-level results")
        result_header_label.setObjectName("SectionTitle")
        header.addWidget(result_header_label)
        header.addStretch()
        self.recognition_wheel_summary = QLabel("W1 —   |   W2 —   |   W4 —")
        self.recognition_wheel_summary.setObjectName("SectionHint")
        header.addWidget(self.recognition_wheel_summary)
        result_layout.addLayout(header)

        self.recognition_table = QTableWidget(0, 9)
        self.recognition_table.setHorizontalHeaderLabels(
            ["Profile", "Wheel", "True", "Top-1", "Top-2", "Top-3", "Rank", "Margin", "Status"]
        )
        self.recognition_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recognition_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recognition_table.setAlternatingRowColors(True)
        self.recognition_table.verticalHeader().setVisible(False)
        self.recognition_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.recognition_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.recognition_table.setMinimumHeight(260)
        self.recognition_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        result_layout.addWidget(self.recognition_table, 1)

        self.recognition_status_label = QLabel(
            "No session scored yet. Complete a MAIN-v8-compatible Digit Scan batch, then select its session ID above."
        )
        self.recognition_status_label.setObjectName("SectionHint")
        self.recognition_status_label.setWordWrap(True)
        result_layout.addWidget(self.recognition_status_label)
        offline_layout.addWidget(result_card, 1)

        self.recognition_stack.addWidget(auto_tab)
        self.recognition_stack.addWidget(offline_tab)
        self.recognition_stack.setCurrentIndex(0)
        self.recognition_tab_group.idClicked.connect(self.recognition_stack.setCurrentIndex)
        layout.addWidget(self.recognition_workspace, 1)

        self.recognition_refresh_button.clicked.connect(self._refresh_recognition_sessions)
        self.recognition_use_collection_button.clicked.connect(self._use_collection_session_for_recognition)
        self.recognition_score_button.clicked.connect(self._score_recognition_session)
        self.recognition_open_results_button.clicked.connect(self._open_recognition_results)
        self.recognition_score_button.setEnabled(self._true_gate_engine is not None)
        self._refresh_recognition_sessions()
        return page

