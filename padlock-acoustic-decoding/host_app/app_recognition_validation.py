"""Offline MAIN-v8 validation controls used by the application window.

Automatic lock-opening orchestration remains in ``app_window.py``.  This mixin
only manages scoring of already-recorded sessions and presentation of the
validation result.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QTableWidgetItem


class RecognitionValidationMixin:
    """Offline validation actions for ``MainWindow``."""

    @staticmethod
    def _format_recognition_accuracy(metrics: dict[str, object], key: str) -> str:
        value = metrics.get(key)
        n = int(metrics.get("n") or 0)
        correct = int(metrics.get(f"{key}_correct") or 0)
        if value is None or n <= 0:
            return "—"
        return f"{correct}/{n}  {100.0 * float(value):.1f}%"


    def _refresh_recognition_sessions(self) -> None:
        if not hasattr(self, "recognition_session_combo"):
            return
        current = self.recognition_session_combo.currentText().strip()
        sessions: list[str] = []
        if self._true_gate_engine is not None:
            try:
                sessions = self._true_gate_engine.list_sessions(self._resolved_dataset_path())
            except Exception as exc:
                self.append_log(f"Recognition session refresh failed: {exc}")
        self.recognition_session_combo.blockSignals(True)
        self.recognition_session_combo.clear()
        self.recognition_session_combo.addItems(sessions)
        if current:
            index = self.recognition_session_combo.findText(current)
            if index >= 0:
                self.recognition_session_combo.setCurrentIndex(index)
            else:
                self.recognition_session_combo.setEditText(current)
        elif sessions:
            self.recognition_session_combo.setCurrentIndex(0)
        self.recognition_session_combo.blockSignals(False)


    def _use_collection_session_for_recognition(self) -> None:
        if not hasattr(self, "recognition_session_combo"):
            return
        session_id = self.session_id_edit.text().strip() if hasattr(self, "session_id_edit") else ""
        if not session_id:
            self._show_error("The Data Collection session ID is empty.")
            return
        self.recognition_session_combo.setEditText(session_id)


    def _score_recognition_session(self) -> None:
        if self._true_gate_engine is None:
            self._show_error(self._true_gate_model_error or "MAIN v8 could not be loaded.")
            return
        session_id = self.recognition_session_combo.currentText().strip()
        if not session_id:
            self._show_error("Select or enter a completed Decision Batch session ID first.")
            return
        dataset_root = self._resolved_dataset_path()
        engine = self._true_gate_engine
        self.recognition_status_label.setText(
            f"Scoring {session_id} with frozen MAIN v8. No model parameters will be changed."
        )
        self._start_task(
            lambda log, root=dataset_root, sid=session_id, model=engine: model.score_session(
                root,
                sid,
                save_results=True,
                log=log,
            ),
            self._recognition_score_result,
            f"MAIN v8 scoring — {session_id}",
            allow_when_disconnected=True,
            trigger_button=self.recognition_score_button,
        )


    @Slot(object)
    def _recognition_score_result(self, result: object) -> None:
        # Validate the worker result structurally to keep recognition optional at runtime.
        if not (
            hasattr(result, "profiles")
            and hasattr(result, "summary")
            and hasattr(result, "session_id")
        ):
            self._show_error("Recognition worker returned an unexpected result.")
            return
        self._recognition_last_result = result
        summary = result.summary
        overall = summary.get("overall", {})
        if not isinstance(overall, dict):
            overall = {}

        self.recognition_profiles_metric.setText(
            f"{int(summary.get('profiles_validated') or 0)} / {int(summary.get('profiles_scored') or 0)}"
        )
        self.recognition_top1_metric.setText(self._format_recognition_accuracy(overall, "top1"))
        self.recognition_top2_metric.setText(self._format_recognition_accuracy(overall, "top2"))
        self.recognition_top3_metric.setText(self._format_recognition_accuracy(overall, "top3"))

        by_wheel = summary.get("by_wheel", {})
        wheel_parts: list[str] = []
        if isinstance(by_wheel, dict):
            for wheel_name in ("W1", "W2", "W4"):
                metrics = by_wheel.get(wheel_name, {})
                if isinstance(metrics, dict):
                    wheel_parts.append(
                        f"{wheel_name} Top-1 {self._format_recognition_accuracy(metrics, 'top1')}"
                    )
        self.recognition_wheel_summary.setText("   |   ".join(wheel_parts) or "W1 —   |   W2 —   |   W4 —")

        self.recognition_table.setRowCount(len(result.profiles))
        for row, profile in enumerate(result.profiles):
            values = [
                profile.profile_id,
                f"W{profile.wheel}" if profile.wheel else "—",
                "—" if profile.true_digit is None else str(profile.true_digit),
                "—" if profile.pred_digit is None else str(profile.pred_digit),
                " / ".join(str(v) for v in profile.top2) if profile.top2 else "—",
                " / ".join(str(v) for v in profile.top3) if profile.top3 else "—",
                "—" if profile.true_rank is None else str(profile.true_rank),
                "—" if profile.margin is None else f"{profile.margin:.3f}",
                profile.status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {1, 2, 3, 6, 7, 8}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.recognition_table.setItem(row, column, item)
            if profile.status == "SCORED" and profile.true_rank is not None:
                status_item = self.recognition_table.item(row, 8)
                if status_item is not None:
                    if profile.true_rank == 1:
                        status_item.setText("TOP-1 HIT")
                    elif profile.true_rank <= 3:
                        status_item.setText(f"RANK {profile.true_rank}")
                    else:
                        status_item.setText(f"MISS • R{profile.true_rank}")

        errors = int(summary.get("errors_or_incomplete") or 0)
        validated = int(summary.get("profiles_validated") or 0)
        message = (
            f"{result.session_id}: {validated} validation profile(s) scored with stored truth. "
            f"Top-1 {self._format_recognition_accuracy(overall, 'top1')}; "
            f"Top-2 {self._format_recognition_accuracy(overall, 'top2')}; "
            f"Top-3 {self._format_recognition_accuracy(overall, 'top3')}."
        )
        if errors:
            message += f"  {errors} profile(s) were incomplete, unsupported or invalid and were excluded from accuracy."
        self.recognition_status_label.setText(message)
        self.recognition_open_results_button.setEnabled(result.result_csv is not None)
        self.append_log(message)


    def _open_recognition_results(self) -> None:
        result = self._recognition_last_result
        if result is None or result.result_csv is None:
            self._show_error("No saved recognition result is available yet.")
            return
        path = result.result_csv.parent
        if not path.exists():
            self._show_error(f"Recognition result folder no longer exists:\n{path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

