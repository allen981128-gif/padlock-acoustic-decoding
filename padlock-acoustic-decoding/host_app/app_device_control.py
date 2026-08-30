"""Device connection and direct manual-control actions for the GUI."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread

from app_workers import TaskWorker


class DeviceControlMixin:
    def _refresh_devices(self) -> None:
        self._start_task(
            lambda log: self.backend.scan_devices(),
            on_result=self._populate_devices,
            task_name="Scanning devices",
            allow_when_disconnected=True,
        )

    def _populate_devices(self, result: object) -> None:
        serial_ports, audio_inputs = result  # type: ignore[misc]
        self.serial_combo.clear()
        self.audio_combo.clear()

        serial_match = -1
        for index, port in enumerate(serial_ports):
            text = port.device
            if port.description:
                text += f" — {port.description}"
            self.serial_combo.addItem(text, port)
            if port.device.lower() == self.settings.serial_port.lower():
                serial_match = index

        audio_match = -1
        for index, device in enumerate(audio_inputs):
            text = (
                f"{device.index}: {device.name} [{device.host_api}] "
                f"{device.max_input_channels} ch, "
                f"{device.default_sample_rate:.0f} Hz"
            )
            self.audio_combo.addItem(text, device)
            if device.index == self.settings.audio_device:
                audio_match = index

        if serial_match >= 0:
            self.serial_combo.setCurrentIndex(serial_match)
        if audio_match >= 0:
            self.audio_combo.setCurrentIndex(audio_match)

        self.append_log(
            f"Found {len(serial_ports)} serial port(s) and "
            f"{len(audio_inputs)} audio input(s)"
        )

    def _connect_devices(self) -> None:
        serial_info = self.serial_combo.currentData()
        audio_info = self.audio_combo.currentData()
        if serial_info is None or audio_info is None:
            self._show_error("Select both an ESP32 port and an audio input.")
            return

        self._start_task(
            lambda log: self.backend.connect(
                serial_info.device,
                audio_info.index,
                log,
            ),
            on_result=self._connection_ready,
            task_name="Connecting devices",
            allow_when_disconnected=True,
        )

    def _connection_ready(self, result: object) -> None:
        status, device_config = result  # type: ignore[misc]
        self.esp_badge.setText(f"ESP32  {self.backend.serial_port}")
        self.esp_badge.setStyleSheet(
            "background:#153b31;color:#a8f0d1;border:1px solid #25634f;border-radius:13px;padding:6px 11px;font-weight:700;"
        )
        self.audio_badge.setText(f"Audio  Device {self.backend.audio_device}")
        self.audio_badge.setStyleSheet(
            "background:#153b31;color:#a8f0d1;border:1px solid #25634f;border-radius:13px;padding:6px 11px;font-weight:700;"
        )
        self.sidebar_esp.setText(f"●  ESP32 {self.backend.serial_port}")
        self.sidebar_audio.setText(f"●  Audio device {self.backend.audio_device}")
        self.sidebar_esp.setStyleSheet("color:#7ee2b8;")
        self.sidebar_audio.setStyleSheet("color:#7ee2b8;")
        self._update_status(status, device_config)
        self._update_controls()

    def _disconnect_devices(self) -> None:
        if self._collection_running:
            self._show_error("Stop collection before disconnecting.")
            return

        self._start_task(
            lambda log: self.backend.disconnect(log),
            on_result=self._disconnection_ready,
            task_name="Disconnecting devices",
            allow_when_disconnected=True,
            trigger_button=self.disconnect_button,
        )

    def _disconnection_ready(self, _: object) -> None:
        self.esp_badge.setText("ESP32  Offline")
        self.audio_badge.setText("Audio  Not checked")
        self.esp_badge.setStyleSheet("")
        self.audio_badge.setStyleSheet("")
        self.sidebar_esp.setText("●  ESP32 offline")
        self.sidebar_audio.setText("●  Audio unchecked")
        self.sidebar_esp.setStyleSheet("color:#74849a;")
        self.sidebar_audio.setStyleSheet("color:#74849a;")
        self._clear_status()
        self._update_controls()

    def _refresh_status(self) -> None:
        self._start_connected_task(
            lambda log: self.backend.refresh_status(log),
            self._status_result,
            "Refreshing status",
        )

    def _read_limit(self) -> None:
        self._start_connected_task(
            lambda log: self.backend.read_limit(log),
            None,
            "Reading limit switch",
        )

    def _reset_fault(self) -> None:
        def reset_and_refresh(log: Any) -> object:
            self.backend.reset_fault(log)
            return self.backend.refresh_status(log)

        self._start_connected_task(
            reset_and_refresh,
            self._status_result,
            "Resetting fault",
        )

    def _home(self) -> None:
        self._start_connected_task(
            lambda log: self.backend.home(log),
            self._status_result,
            "Homing rail",
            trigger_button=self.home_button,
        )

    def _goto_wheel(self, wheel_index: int) -> None:
        self._start_connected_task(
            lambda log: self.backend.goto_wheel(wheel_index, log),
            self._status_result,
            f"Moving to wheel {wheel_index}",
            trigger_button=self.goto_buttons[wheel_index - 1],
        )

    def _servo_up(self) -> None:
        self._start_connected_task(
            lambda log: self.backend.servo_up(log),
            None,
            "Raising servo",
            trigger_button=self.servo_up_button,
        )

    def _servo_down(self) -> None:
        self._start_connected_task(
            lambda log: self.backend.servo_down(log),
            None,
            "Lowering servo",
            trigger_button=self.servo_down_button,
        )

    def _manual_code_transition(self) -> None:
        current_code = self.manual_code_current_edit.text().strip()
        target_code = self.manual_code_target_edit.text().strip()

        if len(current_code) != 4 or not current_code.isdigit():
            self._show_error("Current code must contain exactly four digits (0-9).")
            return
        if len(target_code) != 4 or not target_code.isdigit():
            self._show_error("Target code must contain exactly four digits (0-9).")
            return

        current_digits = [int(value) for value in current_code]
        target_digits = [int(value) for value in target_code]
        digit_steps = self.manual_code_digit_steps_spin.value()

        # A typed code is a human observation, so invalidate the tracked position.
        self._invalidate_position("manual automatic code adjustment")

        self._start_connected_task(
            lambda log: self.backend.transition_to_code(
                current_digits=current_digits,
                target_digits=target_digits,
                digit_steps=digit_steps,
                settle_delay_s=1.0,
                log=log,
            ),
            self._manual_code_transition_result,
            f"Adjusting code {current_code} -> {target_code}",
            trigger_button=self.manual_code_transition_button,
        )

    def _manual_code_transition_result(self, result: object) -> None:
        code = str(result).strip()
        if len(code) != 4 or not code.isdigit():
            self._set_position_valid(False)
            self.append_log(
                "Automatic code adjustment returned an invalid expected code; "
                "physical position remains unsynchronised"
            )
            return

        self._apply_current_code(code, valid=False)
        self.manual_code_target_edit.setText(code)
        self.append_log(
            f"Automatic code adjustment finished at expected code {code}; "
            "visually verify the lock before using the position for collection"
        )

    def _wheel_jog(self) -> None:
        direction = self.wheel_direction_combo.currentText()
        steps = self.wheel_steps.value()
        self._invalidate_position("manual wheel jog")
        self._start_connected_task(
            lambda log: self.backend.wheel_jog(direction, steps, log),
            None,
            f"Jogging wheel {direction} {steps} steps",
            trigger_button=self.wheel_jog_button,
        )

    def _rail_jog(self) -> None:
        direction = self.rail_direction_combo.currentText()
        steps = self.rail_steps.value()
        self._start_connected_task(
            lambda log: self.backend.rail_jog(direction, steps, log),
            self._status_result,
            f"Jogging rail {direction} {steps} steps",
            trigger_button=self.rail_jog_button,
        )

    def _normal_stop(self) -> None:
        self._invalidate_position("controlled STOP was requested")
        self._start_connected_task(
            lambda log: self.backend.stop(log),
            None,
            "Stopping hardware",
            trigger_button=self.stop_button,
        )

    def _emergency_stop(self) -> None:
        if self._emergency_running:
            self.statusBar().showMessage(
                "Emergency stop is already being sent",
                1800,
            )
            return

        self.append_log("EMERGENCY STOP requested")
        if self._auto_recognition_active:
            self._auto_recognition_paused = True
            self._auto_pending_results = None
            self._auto_write_state(
                phase="EMERGENCY_STOP",
                extra={"reason": "Global emergency stop requested"},
            )
            if hasattr(self, "auto_recognition_status_label"):
                self.auto_recognition_status_label.setText(
                    "Automatic recognition PAUSED by emergency stop. Re-synchronise the visible physical code before resuming."
                )
        if self._csv_batch_active:
            self._csv_batch_active = False
            self._csv_batch_pending_advance = False
            self._csv_batch_paused = False
            self._csv_batch_pause_requested = False
            if hasattr(self, "csv_batch_summary_label"):
                self.csv_batch_summary_label.setText("CSV batch aborted by emergency stop")
        self._invalidate_position("emergency STOP was requested")
        self._emergency_running = True
        self._emergency_requested = True
        self._emergency_failed = False
        self._task_sequence += 1
        if self._task_running:
            self._task_cancelled = True
        self.state_badge.setText("State  ABORTING")
        self.state_badge.setStyleSheet(
            "background:#4b1d27;color:#ffc0ca;border:1px solid #8d3446;"
            "border-radius:13px;padding:6px 11px;font-weight:700;"
        )
        self.statusBar().showMessage("Sending emergency stop")
        self._set_operation_state(
            "warning",
            "Emergency stop requested",
            "Cancelling the active wait and sending STOP to the ESP32.",
        )
        self._update_controls()

        thread = QThread(self)
        worker = TaskWorker(
            lambda log: self.backend.emergency_stop(log)
        )
        worker.moveToThread(thread)
        worker.log.connect(self.append_log)
        worker.error.connect(self._emergency_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        # Retain worker references until QThread stops; GUI cleanup stays on the GUI thread.
        thread.finished.connect(self._emergency_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)

        self._emergency_thread = thread
        self._emergency_worker = worker
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()
