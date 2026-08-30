"""Generic asynchronous task runtime and control-state updates for the GUI."""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QThread, QTimer, Slot
from PySide6.QtWidgets import QPushButton

from app_workers import TaskWorker


class TaskRuntimeMixin:
    def _start_connected_task(
        self,
        function: Any,
        on_result: Any,
        task_name: str,
        *,
        trigger_button: QPushButton | None = None,
    ) -> bool:
        if not self.backend.connected:
            self._show_error("Connect the ESP32 and Focusrite first.")
            return False
        return self._start_task(
            function,
            on_result,
            task_name,
            trigger_button=trigger_button,
        )

    def _start_task(
        self,
        function: Any,
        on_result: Any = None,
        task_name: str = "Working",
        allow_when_disconnected: bool = False,
        trigger_button: QPushButton | None = None,
    ) -> bool:
        if (
            self._task_running
            or self._collection_running
            or self._task_cooldown
        ):
            self._show_busy_notice()
            return False

        self._task_running = True
        self._task_failed = False
        self._task_cancelled = False
        self._task_sequence += 1
        if not self._emergency_running:
            self._emergency_requested = False
        self._active_task_name = task_name
        self._active_task_offline = bool(allow_when_disconnected)
        self._task_started_at = time.monotonic()
        self._active_task_button = trigger_button
        self._active_task_button_text = ""

        if trigger_button is not None:
            self._active_task_button_text = trigger_button.text()
            trigger_button.setText("Working…")
            trigger_button.setEnabled(False)

        self.statusBar().showMessage(task_name)
        self.append_log(f"{task_name} started")
        self._set_operation_state(
            "busy",
            task_name,
            (
                "Local analysis is running. Collection and manual controls are temporarily locked."
                if self._active_task_offline
                else "Command accepted. Manual controls are locked until the ESP32 confirms completion."
            ),
        )
        self._update_controls()
        self._task_elapsed_timer.start()

        thread = QThread(self)
        worker = TaskWorker(function)
        worker.moveToThread(thread)

        worker.log.connect(self.append_log)
        worker.error.connect(self._task_error)
        if on_result is not None:
            worker.result.connect(on_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        # Finalize only after QThread stops so worker references are not released early.
        thread.finished.connect(self._task_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)

        self._active_task_thread = thread
        self._active_task_worker = worker
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()
        return True


    def _release_task_cooldown(self) -> None:
        self._task_cooldown = False
        self._update_controls()

    def _reset_operation_state_if_idle(self, sequence: int) -> None:
        if (
            sequence == self._task_sequence
            and not self._task_running
            and not self._collection_running
            and not self._emergency_running
        ):
            self._set_operation_state(
                "ready",
                "Manual controls ready",
                "One hardware command is accepted at a time. Repeated clicks are ignored safely.",
            )

    @Slot(str)
    def _task_error(self, message: str) -> None:
        self.append_log(message)
        short = message.splitlines()[0] if message else "Unknown error"

        if self._auto_recognition_active:
            auto_critical = bool(
                self._collection_running
                or self._active_task_name.startswith("MAIN v8 automatic recognition")
                or self._active_task_name.startswith("W3 unlock trial")
            )
            if auto_critical:
                self._auto_recognition_paused = True
                if hasattr(self, "auto_recognition_status_label"):
                    self.auto_recognition_status_label.setText(
                        f"Automatic recognition paused by error: {short}. Inspect hardware/data, re-synchronise the physical code if needed, then Resume."
                    )
                self._auto_write_state(
                    phase="PAUSED_BY_ERROR",
                    extra={"error": short},
                )

        if (
            "SerialCancelledError" in message
            and self._emergency_requested
        ):
            self._task_cancelled = True
            self.statusBar().showMessage(
                "Operation cancelled by emergency stop",
                3500,
            )
            return

        self._task_failed = True
        if self._csv_batch_active and self._collection_running:
            self._csv_batch_paused = True
            self._csv_batch_pause_requested = False
            self._csv_batch_pending_advance = False
            if hasattr(self, "csv_batch_summary_label"):
                self.csv_batch_summary_label.setText(
                    f"{'Binding Scan' if self._csv_batch_task_type == 'binding_scan' else 'Digit Scan Batch'} paused by collection error"
                )
            self.append_log(
                f"{'Binding Scan' if self._csv_batch_task_type == 'binding_scan' else 'Digit Scan Batch'} paused because the collection worker failed"
            )
        self.statusBar().showMessage(short, 6000)
        self._set_operation_state(
            "error",
            "Command failed",
            short,
        )

        if (
            "SerialTimeoutError" in message
            or "SerialConnectionError" in message
            or "SerialProtocolError" in message
        ):
            self.work_splitter.setSizes([560, 360])

    @Slot(str)
    def _emergency_error(self, message: str) -> None:
        self._emergency_failed = True
        self.append_log(message)
        short = message.splitlines()[0] if message else "Unknown error"
        self.statusBar().showMessage(short, 6000)
        self._set_operation_state(
            "error",
            "Emergency stop failed",
            short,
        )


    def _update_controls(self) -> None:
        connected = self.backend.connected
        batch_blocks_manual = self._csv_batch_active and not self._csv_batch_paused
        auto_blocks_manual = self._auto_recognition_active and not self._auto_recognition_paused
        busy = (
            self._task_running
            or self._collection_running
            or self._task_cooldown
            or batch_blocks_manual
            or auto_blocks_manual
        )

        self.connect_button.setEnabled(not busy)
        self.disconnect_button.setEnabled(connected and not busy)
        self.refresh_devices_button.setEnabled(not busy and not connected)
        self.check_status_button.setEnabled(connected and not busy)
        self.limit_read_button.setEnabled(connected and not busy)
        self.reset_fault_button.setEnabled(connected and not busy)

        manual_buttons = [
            self.home_button,
            self.servo_up_button,
            self.servo_down_button,
            self.wheel_jog_button,
            self.rail_jog_button,
            self.manual_code_transition_button,
            self.stop_button,
            *self.goto_buttons,
        ]
        for button in manual_buttons:
            button.setEnabled(connected and not busy)

        for control in (
            self.wheel_direction_combo,
            self.wheel_steps,
            self.rail_direction_combo,
            self.rail_steps,
        ):
            control.setEnabled(connected and not busy)

        for control in (
            self.manual_code_current_edit,
            self.manual_code_target_edit,
            self.manual_code_digit_steps_spin,
        ):
            control.setEnabled(not busy)

        emergency_enabled = connected and not self._emergency_running
        self.emergency_button.setEnabled(emergency_enabled)
        self.sidebar_emergency.setEnabled(emergency_enabled)
        self.digit_steps_spin.setEnabled(
            not busy and not self._csv_batch_active
        )
        self.keep_contact_check.setEnabled(
            not busy and not self._csv_batch_active
        )
        self.generate_plan_button.setEnabled(
            not busy and self._position_valid and not self._auto_recognition_active
        )
        self.start_collection_button.setEnabled(
            connected
            and not busy
            and not self._csv_batch_active
            and not self._auto_recognition_active
            and self._position_valid
            and bool(self._requests)
        )
        self.single_collection_button.setEnabled(
            connected
            and not busy
            and not self._csv_batch_active
            and not self._auto_recognition_active
            and self._position_valid
            and bool(self._requests)
        )
        self.stop_collection_button.setEnabled(self._collection_running)
        if hasattr(self, "csv_batch_import_button"):
            csv_idle = (
                not self._csv_batch_active
                and not self._auto_recognition_active
                and not self._collection_running
                and not self._task_running
                and not self._task_cooldown
            )
            self.csv_batch_mode_combo.setEnabled(csv_idle)
            self.csv_batch_import_button.setEnabled(csv_idle)
            self.csv_batch_template_button.setEnabled(csv_idle)
            self.csv_batch_start_button.setEnabled(
                connected
                and csv_idle
                and bool(self._csv_batch_decisions)
            )
            self.csv_batch_pause_button.setEnabled(
                connected
                and self._csv_batch_active
                and (self._collection_running or self._csv_batch_paused)
                and not self._task_running
            )
            self.csv_batch_resume_selected_button.setEnabled(
                connected
                and bool(self._csv_batch_decisions)
                and not self._collection_running
                and not self._task_running
            )
            self.csv_batch_delete_last_button.setEnabled(
                self._csv_batch_active
                and self._csv_batch_paused
                and not self._collection_running
            )
            self.csv_batch_cancel_button.setEnabled(self._csv_batch_active)
        if hasattr(self, "review_latest_button"):
            self.review_latest_button.setEnabled(not self._collection_running)
        if hasattr(self, "recognition_score_button"):
            recognition_idle = not busy and not self._auto_recognition_active
            self.recognition_score_button.setEnabled(
                self._true_gate_engine is not None and recognition_idle
            )
            self.recognition_refresh_button.setEnabled(recognition_idle)
            self.recognition_use_collection_button.setEnabled(recognition_idle)
            self.recognition_session_combo.setEnabled(recognition_idle)
        if hasattr(self, "auto_recognition_start_button"):
            auto_idle_for_action = (
                not self._collection_running
                and not self._task_running
                and not self._task_cooldown
                and not self._csv_batch_active
            )
            self.auto_recognition_start_button.setEnabled(
                self._true_gate_engine is not None
                and self.backend.connected
                and auto_idle_for_action
                and (not self._auto_recognition_active or self._auto_recognition_paused)
            )
            self.auto_recognition_stop_button.setEnabled(self._auto_recognition_active)
            self._update_auto_recognition_ui()
