from __future__ import annotations

from datetime import datetime
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import (
    QThread,
    QTimer,
    Qt,
    Slot,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
)

from app_backend import PadlockBackend
from decision_batch import (
    DecisionBatchRow,
    DecisionBatchFinalizer,
    DecisionProgressStore,
    decision_candidate_specs,
    load_decision_batch_csv,
    write_decision_batch_template,
    write_binding_scan_template,
)
from app_settings import APP_DIR, AppSettings
from app_workers import CollectionWorker
from models import (
    ActionType,
    RunRequest,
    RunResult,
    RunStatus,
)
from auto_recognition import (
    AUTO_COMPONENTS,
    AUTO_MAX_RECOGNITION_PASSES,
    AUTO_RETRY_MARGIN_THRESHOLD,
    AUTO_WHEELS,
    AutoRecognitionError,
    AutoRecognitionStore,
    PrefixHypothesis,
    build_top2_prefix_hypotheses,
    circle_quality_summary,
    delete_result_runs,
    profile_id_for,
    randomized_restart_code,
    recognition_margin_summary,
    validate_session_id,
)
from unlock_detector_v1 import (
    DRMS_THRESHOLD as UNLOCK_DRMS_THRESHOLD,
    POST_END_MS as UNLOCK_POST_END_MS,
    PRE_END_MS as UNLOCK_PRE_END_MS,
    RMS_THRESHOLD as UNLOCK_RMS_THRESHOLD,
    detect_unlock_files,
)
from app_theme import APP_STYLE
from app_dialogs import (
    CircleReviewDialog,
    CodeTransitionDialog,
    _themed_choice,
    _themed_information,
    _themed_item_choice,
    _themed_question,
    _themed_warning,
)
from app_ui import MainWindowUiMixin
from app_recognition_validation import RecognitionValidationMixin
from app_device_control import DeviceControlMixin
from app_task_runtime import TaskRuntimeMixin
from app_window_support import WindowSupportMixin

# Load recognition defensively so data collection still works if its runtime is unavailable.
_TRUE_GATE_IMPORT_ERROR = ""
try:
    from true_gate_inference import (
        TrueGateInferenceEngine,
    )
except Exception as _true_gate_import_exc:
    TrueGateInferenceEngine = None  # type: ignore[assignment]
    _TRUE_GATE_IMPORT_ERROR = (
        f"{type(_true_gate_import_exc).__name__}: {_true_gate_import_exc}"
    )


class MainWindow(
    MainWindowUiMixin,
    RecognitionValidationMixin,
    DeviceControlMixin,
    TaskRuntimeMixin,
    WindowSupportMixin,
    QMainWindow,
):
    SIGNAL_REVIEW_PAGE_INDEX = 3

    PAGE_INFO = [
        ("◈", "Devices", "Connection and system health"),
        ("⌁", "Manual Control", "Direct hardware positioning and diagnostics"),
        ("◉", "Data Collection", "Configure, capture and monitor datasets"),
        ("∿", "Signal Review", "Waveform, spectrogram and recording quality"),
        ("◇", "Recognition", "Supervised automatic recognition + frozen validation"),
    ]

    def __init__(self) -> None:
        super().__init__()

        self.settings = AppSettings.load()
        self.backend = PadlockBackend()

        self._threads: list[QThread] = []
        self._workers: list[Any] = []
        self._requests: list[RunRequest] = []
        self._active_row_map: list[int] = []
        self._collection_running = False
        self._task_running = False
        self._task_cooldown = False
        self._task_failed = False
        self._task_cancelled = False
        self._task_sequence = 0
        self._active_task_name = ""
        self._active_task_offline = False
        self._active_task_button: QPushButton | None = None
        self._active_task_button_text = ""
        self._active_task_thread: QThread | None = None
        self._active_task_worker: object | None = None
        self._collection_thread: QThread | None = None
        self._collection_worker: object | None = None
        self._emergency_thread: QThread | None = None
        self._emergency_worker: object | None = None
        self._last_busy_notice_at = 0.0
        self._task_started_at = 0.0
        self._emergency_running = False
        self._emergency_requested = False
        self._emergency_failed = False
        self._position_valid = False
        self._plan_start_code = ""
        self._latest_review_dir: Path | None = None
        self._wheel_collection_order: list[int] = []

        self._csv_batch_plan_path: Path | None = None
        self._csv_batch_decisions: list[DecisionBatchRow] = []
        self._csv_batch_task_type = "digit_scan"
        self._csv_batch_reseat_confirmed_keys: set[str] = set()
        self._csv_batch_active = False
        self._csv_batch_paused = False
        self._csv_batch_pause_requested = False
        self._csv_batch_decision_index = 0
        self._csv_batch_pending_advance = False
        self._csv_batch_table_rows: dict[tuple[int, int, int], int] = {}
        self._csv_batch_row_to_candidate: dict[int, tuple[int, int]] = {}
        self._csv_batch_finalizer = DecisionBatchFinalizer()
        self._csv_batch_progress = DecisionProgressStore()

        self._pending_log_lines: list[str] = []
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.timeout.connect(self._flush_logs)

        self._task_elapsed_timer = QTimer(self)
        self._task_elapsed_timer.setInterval(250)
        self._task_elapsed_timer.timeout.connect(
            self._update_task_elapsed
        )

        self._valid_count = 0
        self._rejected_count = 0
        self._failed_count = 0
        # Mirror every RunResult emitted during the active collection. AUTO
        # circle review reconciles this with the batch-completed result list so
        # a REJECTED/FAILED candidate cannot disappear from the checkpoint.
        self._active_collection_results: list[RunResult] = []

        # Frozen MAIN v8 runtime; the App performs inference only.
        self._true_gate_engine = None
        self._true_gate_model_error = _TRUE_GATE_IMPORT_ERROR
        self._recognition_last_result = None
        if TrueGateInferenceEngine is not None:
            try:
                self._true_gate_engine = TrueGateInferenceEngine()
            except Exception as exc:
                self._true_gate_model_error = f"{type(exc).__name__}: {exc}"

        # Unknown-lock recognition state. Ground truth is never supplied to the scorer.
        self._auto_recognition_active = False
        self._auto_recognition_paused = False
        self._auto_recognition_session = ""
        self._auto_store: AutoRecognitionStore | None = None
        self._auto_wheel_index = 0
        self._auto_component_index = 0
        self._auto_pending_results: list[RunResult] | None = None
        self._auto_current_start_digits: tuple[int, int, int, int] | None = None
        self._auto_predictions: dict[int, dict[str, object]] = {}
        self._auto_pending_transition: tuple[int, str] | None = None
        # Route scorer results through a QObject slot so GUI timers stay on the GUI thread.
        self._auto_scoring_profile_id = ""
        self._auto_scoring_wheel = 0
        self._auto_w3_positions_checked = 0
        self._auto_w3_initial_digit = -1
        self._auto_collection_kind = ""
        self._auto_w3_pending_action = ""
        self._auto_w3_pending_detection: dict[str, object] | None = None
        self._auto_w3_false_detections: list[dict[str, object]] = []
        self._auto_final_code = ""
        # Evidence-ranked Top-2 prefix fallback, built after W1/W2/W4 are scored.
        self._auto_prefix_hypotheses: list[PrefixHypothesis] = []
        self._auto_prefix_index = -1
        self._auto_prefix_history: list[dict[str, object]] = []
        self._auto_first_pass_failed = False
        # Fresh retry is bounded to one independent second recognition pass.
        self._auto_pass_number = 1
        self._auto_pass_history: list[dict[str, object]] = []
        self._auto_pass_start_code = ""
        self._auto_retry_random_code = ""
        self._auto_started_at = ""

        self._window_fitted_once = False
        self.setWindowTitle("Padlock Collector")
        self.resize(1540, 940)
        self.setMinimumSize(1080, 700)

        # Apply styling at QApplication scope so native top-level dialogs match the UI.
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(APP_STYLE)
        self.setStyleSheet(APP_STYLE)

        self._build_ui()
        self.log_box.document().setMaximumBlockCount(2500)
        self._apply_settings()
        self._refresh_devices()





    def _auto_new_session_id(self) -> None:
        if self._auto_recognition_active:
            self._show_error("Stop the current automatic-recognition workflow before changing Session ID.")
            return
        self.auto_recognition_session_edit.setText(
            "AUTO_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )

    def _update_auto_recognition_ui(self) -> None:
        if not hasattr(self, "auto_recognition_state_label"):
            return
        code_text = self._current_code_text() if hasattr(self, "current_digit_spins") else "----"
        sync_text = code_text if self._position_valid else f"{code_text} (NOT SYNCED)"
        self.auto_recognition_code_label.setText(f"Current code: {sync_text}")

        predictions = []
        for wheel in AUTO_WHEELS:
            item = self._auto_predictions.get(wheel, {})
            pred = item.get("top1")
            predictions.append("?" if pred is None else str(pred))
        hypothesis = self._auto_current_prefix_hypothesis()
        if hypothesis is not None:
            tie_note = " • evidence tie" if hypothesis.tied_with_previous else ""
            self.auto_recognition_prediction_label.setText(
                f"Search #{self._auto_prefix_index + 1}/{len(self._auto_prefix_hypotheses)}: "
                f"{hypothesis.prefix_text} • evidence {hypothesis.joint_score:.3f}{tie_note}"
            )
        else:
            self.auto_recognition_prediction_label.setText(
                f"Predicted: W1 {predictions[0]}   W2 {predictions[1]}   W3 ?   W4 {predictions[2]}"
            )

        if self._auto_recognition_active and self._auto_wheel_index < len(AUTO_WHEELS):
            wheel = AUTO_WHEELS[self._auto_wheel_index]
            if self._auto_component_index < len(AUTO_COMPONENTS):
                direction, repeat_id = AUTO_COMPONENTS[self._auto_component_index]
                self.auto_recognition_circle_label.setText(
                    f"Next circle: W{wheel} {direction}-{repeat_id} ({self._auto_component_index + 1}/4)"
                )
            else:
                self.auto_recognition_circle_label.setText(f"Next: score W{wheel} with frozen MAIN v8")
        elif self._auto_recognition_active and self._auto_wheel_index >= len(AUTO_WHEELS):
            if hypothesis is not None:
                self.auto_recognition_circle_label.setText(
                    f"Prefix {self._auto_prefix_index + 1}/{len(self._auto_prefix_hypotheses)} • W3 continuous unlock sweep"
                )
            else:
                self.auto_recognition_circle_label.setText("Next: W3 continuous unlock sweep")
        else:
            self.auto_recognition_circle_label.setText("Next circle: —")

        if self._auto_recognition_active:
            self.auto_recognition_state_label.setText(
                "PAUSED"
                if self._auto_recognition_paused
                else f"ACTIVE • PASS {self._auto_pass_number}/{AUTO_MAX_RECOGNITION_PASSES}"
            )
            self.auto_recognition_session_edit.setEnabled(False)
            self.auto_recognition_new_session_button.setEnabled(False)
            self.auto_recognition_start_button.setText(
                "Resume supervised recognition" if self._auto_recognition_paused else "Recognition running"
            )
            self.auto_recognition_stop_button.setEnabled(True)
        else:
            self.auto_recognition_state_label.setText("IDLE")
            self.auto_recognition_session_edit.setEnabled(True)
            self.auto_recognition_new_session_button.setEnabled(True)
            self.auto_recognition_start_button.setText("Start supervised recognition")
            self.auto_recognition_stop_button.setEnabled(False)

    def _set_auto_status(self, text: str) -> None:
        if hasattr(self, "auto_recognition_status_label"):
            self.auto_recognition_status_label.setText(text)
        self.append_log(f"AUTO RECOGNITION: {text}")
        if self._auto_store is not None:
            try:
                self._auto_store.append_flow_event(
                    "STATUS",
                    {
                        "pass_number": self._auto_pass_number,
                        "current_code": self._current_code_text(),
                        "message": str(text),
                    },
                )
            except Exception as exc:
                self.append_log(f"AUTO RECOGNITION flow-log status warning: {exc}")
        self._update_auto_recognition_ui()

    def _auto_reset_table(self) -> None:
        if not hasattr(self, "auto_recognition_table"):
            return
        for row, wheel in enumerate(AUTO_WHEELS):
            values = [f"W{wheel}", "—", "—", "—", "—", "WAITING"]
            for column, value in enumerate(values):
                item = self.auto_recognition_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.auto_recognition_table.setItem(row, column, item)
                item.setText(value)

    def _auto_current_prefix_hypothesis(self) -> PrefixHypothesis | None:
        if 0 <= self._auto_prefix_index < len(self._auto_prefix_hypotheses):
            return self._auto_prefix_hypotheses[self._auto_prefix_index]
        return None

    def _auto_prepare_prefix_search(self) -> None:
        """Freeze the current Top-2 cube into an evidence-ranked search queue."""
        hypotheses = build_top2_prefix_hypotheses(self._auto_predictions)
        if not hypotheses:
            raise AutoRecognitionError("MAIN v8 produced no Top-2 prefix hypotheses")
        self._auto_prefix_hypotheses = hypotheses
        self._auto_prefix_index = 0
        self._auto_prefix_history = []
        if self._auto_pass_number == 1:
            self._auto_first_pass_failed = False

        first = hypotheses[0]
        current = self._current_code_values()
        current_prefix = (int(current[0]), int(current[1]), int(current[3]))
        first_prefix = (first.w1, first.w2, first.w4)
        if current_prefix != first_prefix:
            raise AutoRecognitionError(
                "Top-1 physical prefix does not match the highest-evidence MAIN v8 hypothesis: "
                f"physical={current_prefix}, evidence={first_prefix}"
            )
        self._auto_update_prefix_table_state()
        self._auto_write_state(
            phase="PREFIX_QUEUE_READY",
            extra={
                "prefix_hypotheses": [item.to_dict() for item in hypotheses],
                "current_prefix_rank": 1,
                "current_prefix": first.prefix_text,
            },
        )

    def _auto_update_prefix_table_state(self) -> None:
        hypothesis = self._auto_current_prefix_hypothesis()
        if hypothesis is None or not hasattr(self, "auto_recognition_table"):
            return
        rank_by_wheel = {
            1: hypothesis.wheel_ranks[0],
            2: hypothesis.wheel_ranks[1],
            4: hypothesis.wheel_ranks[2],
        }
        for row, wheel in enumerate(AUTO_WHEELS):
            item = self.auto_recognition_table.item(row, 5)
            if item is None:
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.auto_recognition_table.setItem(row, 5, item)
            rank = int(rank_by_wheel[wheel])
            item.setText(f"ACTIVE • TOP-{rank}")

    def _auto_prefix_target_code(self, hypothesis: PrefixHypothesis) -> str:
        current = self._current_code_values()
        return f"{hypothesis.w1}{hypothesis.w2}{int(current[2])}{hypothesis.w4}"

    def _auto_mark_current_prefix_failed(self) -> PrefixHypothesis | None:
        hypothesis = self._auto_current_prefix_hypothesis()
        if hypothesis is None:
            return None
        already_recorded = any(
            int(item.get("rank", -1)) == hypothesis.rank
            and item.get("result") == "NO_UNLOCK"
            for item in self._auto_prefix_history
        )
        if not already_recorded:
            self._auto_prefix_history.append(
                {
                    **hypothesis.to_dict(),
                    "result": "NO_UNLOCK",
                    "w3_positions_checked": int(self._auto_w3_positions_checked),
                }
            )
        if self._auto_pass_number == 1 and self._auto_prefix_index == 0:
            self._auto_first_pass_failed = True
        self._auto_write_state(
            phase="PREFIX_REJECTED_BY_UNLOCK_TEST",
            extra={
                "failed_prefix": hypothesis.to_dict(),
                "prefix_search_history": list(self._auto_prefix_history),
                "first_pass_failed": self._auto_first_pass_failed,
            },
        )
        return hypothesis

    def _auto_has_next_prefix(self) -> bool:
        return self._auto_prefix_index + 1 < len(self._auto_prefix_hypotheses)

    def _auto_advance_to_next_prefix(self, *, skip_choice: bool = False) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        failed = self._auto_mark_current_prefix_failed()
        if failed is None or not self._auto_has_next_prefix():
            self._auto_finish(unlocked=False, final_code="")
            return

        next_index = self._auto_prefix_index + 1
        next_hypothesis = self._auto_prefix_hypotheses[next_index]
        tie_text = (
            "\n\nNOTE: this hypothesis is exactly tied in joint model evidence with the preceding one. "
            "The order inside an exact tie is deterministic only; it is not extra evidence for one wheel."
            if next_hypothesis.tied_with_previous
            else ""
        )
        if not skip_choice:
            choice = _themed_choice(
                self,
                "Current prefix rejected",
                (
                    f"Prefix {failed.prefix_text} was tested across all 10 W3 digits and did not unlock. "
                    "That is hard negative evidence for this complete prefix.\n\n"
                    f"Next ranked hypothesis: #{next_index + 1}/{len(self._auto_prefix_hypotheses)}  "
                    f"{next_hypothesis.prefix_text}\n"
                    f"Joint MAIN v8 evidence: {next_hypothesis.joint_score:.4f}\n"
                    f"Evidence loss from original Top-1 prefix: {next_hypothesis.evidence_loss:.4f}"
                    f"{tie_text}"
                ),
                primary_key="next",
                primary_text="Try next ranked prefix",
                secondary_key="finish",
                secondary_text="Finish as failure",
                cancel_text="Pause workflow",
            )
            if choice == "finish":
                self._auto_finish(unlocked=False, final_code="")
                return
            if choice != "next":
                self._auto_pause("Paused before switching to the next evidence-ranked prefix.")
                return

        target_code = self._auto_prefix_target_code(next_hypothesis)
        dialog = CodeTransitionDialog(
            self,
            current_code=self._current_code_text(),
            planned_code=target_code,
            next_key=(
                f"Fallback prefix #{next_index + 1}/{len(self._auto_prefix_hypotheses)} · "
                f"{next_hypothesis.prefix_text} · evidence {next_hypothesis.joint_score:.4f}"
            ),
        )
        dialog.exec()
        if not dialog.confirmed:
            self._auto_pause(
                f"Paused before fallback prefix {next_hypothesis.prefix_text} was physically confirmed."
            )
            return

        self._auto_prefix_index = next_index
        self._auto_w3_positions_checked = 0
        self._auto_w3_initial_digit = -1
        self._auto_w3_pending_action = ""
        self._auto_w3_pending_detection = None
        self._auto_update_prefix_table_state()
        self._auto_write_state(
            phase="FALLBACK_PREFIX_SET",
            extra={
                "current_prefix_rank": next_hypothesis.rank,
                "current_prefix": next_hypothesis.prefix_text,
                "joint_evidence": next_hypothesis.joint_score,
                "evidence_loss": next_hypothesis.evidence_loss,
                "prefix_search_history": list(self._auto_prefix_history),
            },
        )
        self._set_auto_status(
            f"Fallback prefix #{next_index + 1}/{len(self._auto_prefix_hypotheses)} "
            f"{next_hypothesis.prefix_text} is physically set and confirmed. Starting a fresh 10-position W3 unlock search."
        )
        QTimer.singleShot(0, self._auto_start_w3_search)

    def _auto_margin_summary(self) -> dict[str, object]:
        return recognition_margin_summary(
            self._auto_predictions,
            threshold=AUTO_RETRY_MARGIN_THRESHOLD,
        )

    def _auto_current_pass_record(self, *, outcome: str) -> dict[str, object]:
        margin_info = self._auto_margin_summary()
        top1_prefix = ""
        if all(wheel in self._auto_predictions for wheel in AUTO_WHEELS):
            top1_prefix = (
                f"{int(self._auto_predictions[1].get('top1', -1))}"
                f"{int(self._auto_predictions[2].get('top1', -1))}?"
                f"{int(self._auto_predictions[4].get('top1', -1))}"
            )
        return {
            "pass_number": int(self._auto_pass_number),
            "start_code": self._auto_pass_start_code,
            "end_code": self._current_code_text(),
            "outcome": str(outcome),
            "top1_prefix": top1_prefix or None,
            "predictions": {
                f"W{wheel}": dict(values)
                for wheel, values in self._auto_predictions.items()
            },
            "margin_summary": margin_info,
            "prefix_search_history": list(self._auto_prefix_history),
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _auto_record_current_pass(self, *, outcome: str) -> dict[str, object]:
        record = self._auto_current_pass_record(outcome=outcome)
        pass_number = int(record["pass_number"])
        replaced = False
        for index, existing in enumerate(self._auto_pass_history):
            if int(existing.get("pass_number", -1)) == pass_number:
                self._auto_pass_history[index] = record
                replaced = True
                break
        if not replaced:
            self._auto_pass_history.append(record)
        return record

    def _auto_begin_fresh_retry(self) -> None:
        """Start the single bounded fresh recognition retry after low-confidence failure."""
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        if self._auto_pass_number >= AUTO_MAX_RECOGNITION_PASSES:
            self._auto_w3_pending_action = "NO_UNLOCK"
            QTimer.singleShot(0, self._auto_prompt_w3_no_unlock)
            return
        if self._collection_running or self._task_running or self._task_cooldown:
            QTimer.singleShot(250, self._auto_begin_fresh_retry)
            return

        failed = self._auto_mark_current_prefix_failed()
        margin_info = self._auto_margin_summary()
        self._auto_record_current_pass(outcome="TOP1_NO_UNLOCK_LOW_MARGIN")

        current_code = self._current_code_text()
        if not self._auto_retry_random_code:
            target_digits = randomized_restart_code(self._current_code_values())
            self._auto_retry_random_code = "".join(str(v) for v in target_digits)
        target_code = self._auto_retry_random_code
        margins = margin_info.get("margins", {})
        min_margin = margin_info.get("min_margin")
        margin_text = "—" if min_margin is None else f"{float(min_margin):.3f}"

        self._auto_w3_pending_action = "FRESH_RETRY"
        self._auto_write_state(
            phase="FRESH_RETRY_RANDOMIZATION_REQUIRED",
            extra={
                "failed_prefix": failed.to_dict() if failed is not None else None,
                "from_pass": self._auto_pass_number,
                "to_pass": self._auto_pass_number + 1,
                "margins": margins,
                "min_margin": min_margin,
                "threshold": AUTO_RETRY_MARGIN_THRESHOLD,
                "current_code": current_code,
                "randomized_target_code": target_code,
            },
        )
        self._set_auto_status(
            f"Pass {self._auto_pass_number} Top-1 prefix failed W3 and minimum margin {margin_text} "
            f"is below {AUTO_RETRY_MARGIN_THRESHOLD:.2f}. Fresh randomized pass {self._auto_pass_number + 1}/"
            f"{AUTO_MAX_RECOGNITION_PASSES} is required before long fallback."
        )

        dialog = CodeTransitionDialog(
            self,
            current_code=current_code,
            planned_code=target_code,
            next_key=(
                f"Fresh randomized recognition pass {self._auto_pass_number + 1}/"
                f"{AUTO_MAX_RECOGNITION_PASSES} · min margin {margin_text} < "
                f"{AUTO_RETRY_MARGIN_THRESHOLD:.2f}. If the lock opens accidentally during randomization, "
                "do not confirm this target; reseat the lock and choose a new clean session."
            ),
        )
        dialog.exec()
        if not dialog.confirmed:
            self._auto_pause(
                f"Paused before randomized restart code {target_code} was physically confirmed."
            )
            return

        previous_pass = self._auto_pass_number
        self._auto_pass_number += 1
        self._auto_wheel_index = 0
        self._auto_component_index = 0
        self._auto_pending_results = None
        self._auto_current_start_digits = None
        self._auto_predictions = {}
        self._auto_pending_transition = None
        self._auto_scoring_profile_id = ""
        self._auto_scoring_wheel = 0
        self._auto_w3_positions_checked = 0
        self._auto_w3_initial_digit = -1
        self._auto_collection_kind = ""
        self._auto_w3_pending_action = ""
        self._auto_w3_pending_detection = None
        self._auto_final_code = ""
        self._auto_prefix_hypotheses = []
        self._auto_prefix_index = -1
        self._auto_prefix_history = []
        self._auto_pass_start_code = target_code
        self._auto_retry_random_code = ""
        self._auto_reset_table()
        self._auto_write_state(
            phase="FRESH_RETRY_PASS_STARTED",
            extra={
                "previous_pass": previous_pass,
                "pass_number": self._auto_pass_number,
                "randomized_start_code": target_code,
                "trigger_margin_summary": margin_info,
            },
        )
        self._set_auto_status(
            f"Randomized code {target_code} confirmed. Starting fresh recognition pass "
            f"{self._auto_pass_number}/{AUTO_MAX_RECOGNITION_PASSES} from W1 CCW-A."
        )
        self._update_auto_recognition_ui()
        QTimer.singleShot(0, self._auto_start_current_component)

    def _auto_prompt_evaluation_truth(self) -> str | None:
        text, ok = QInputDialog.getText(
            self,
            "Optional evaluation label",
            (
                "For success-rate testing only, enter the actual 4-digit combination now.\n"
                "This prompt appears only after recognition has finished; the value is never supplied to MAIN v8 or the Unlock Detector.\n\n"
                "Leave blank or press Cancel to skip."
            ),
        )
        if not ok or not str(text).strip():
            return None
        value = str(text).strip()
        if len(value) != 4 or not value.isdigit():
            _themed_warning(
                self,
                "Evaluation label skipped",
                "The optional evaluation combination must contain exactly four digits. Nothing was saved as ground truth.",
            )
            return None
        return value

    def _auto_write_final_report(
        self,
        *,
        unlocked: bool,
        final_code: str,
        evaluation_true_code: str | None,
    ) -> None:
        store = self._auto_store
        if store is None:
            return
        pass_history = list(self._auto_pass_history)
        first_pass_success = bool(
            pass_history
            and str(pass_history[0].get("outcome", "")).startswith("UNLOCKED")
        )
        full_success: bool | None = None
        if evaluation_true_code is not None:
            full_success = bool(unlocked and final_code == evaluation_true_code)

        summary = {
            "workflow_version": "fresh_retry_v1_plus_unlock_v1",
            "started_at_local": self._auto_started_at or None,
            "finished_at_local": datetime.now().isoformat(timespec="seconds"),
            "outcome": "UNLOCKED" if unlocked else "NO_UNLOCK",
            "operator_confirmed_unlock": bool(unlocked),
            "detected_code": final_code if unlocked else None,
            "evaluation_true_code_posthoc": evaluation_true_code,
            "full_code_success_posthoc": full_success,
            "first_pass_success": first_pass_success,
            "passes_used": len(pass_history),
            "max_passes": AUTO_MAX_RECOGNITION_PASSES,
            "retry_policy": {
                "rule": "Top-1 full W3 sweep fails AND minimum W1/W2/W4 margin < threshold",
                "margin_threshold": AUTO_RETRY_MARGIN_THRESHOLD,
                "randomization": "all four displayed digits displaced by 2-8 positions before pass 2",
            },
            "passes": pass_history,
            "unlock_detector": {
                "name": "Physical Unlock Detector v1",
                "window_ms": [-UNLOCK_PRE_END_MS, UNLOCK_POST_END_MS],
                "rms_threshold": UNLOCK_RMS_THRESHOLD,
                "drms_threshold": UNLOCK_DRMS_THRESHOLD,
                "confirmed_detection": dict(self._auto_w3_pending_detection or {}) if unlocked else None,
                "false_detections": list(self._auto_w3_false_detections),
            },
            "model_source_sha256": (
                self._true_gate_engine.source_model_sha256
                if self._true_gate_engine is not None
                else ""
            ),
            "correct_combination_supplied_to_inference": False,
            "flow_log_file": store.flow_log_path.name,
            "console_log_file": store.console_log_path.name,
        }

        lines = [
            "AUTOMATIC RECOGNITION FLOW REPORT",
            f"Session: {self._auto_recognition_session}",
            f"Outcome: {'UNLOCKED' if unlocked else 'NO UNLOCK'}",
            f"Detected code: {final_code if unlocked else '—'}",
            f"Post-hoc true code: {evaluation_true_code or 'not supplied'}",
            f"Post-hoc full-code success: {'—' if full_success is None else ('YES' if full_success else 'NO')}",
            f"Passes used: {len(pass_history)}/{AUTO_MAX_RECOGNITION_PASSES}",
            f"Retry threshold: min wheel margin < {AUTO_RETRY_MARGIN_THRESHOLD:.2f}",
            "",
        ]
        for record in pass_history:
            pnum = int(record.get("pass_number", 0) or 0)
            lines.append(f"PASS {pnum}")
            lines.append(f"  Start code: {record.get('start_code') or '—'}")
            lines.append(f"  End code: {record.get('end_code') or '—'}")
            lines.append(f"  Outcome: {record.get('outcome') or '—'}")
            lines.append(f"  Top-1 prefix: {record.get('top1_prefix') or '—'}")
            margin_summary = record.get("margin_summary") or {}
            if isinstance(margin_summary, dict):
                lines.append(f"  Margins: {margin_summary.get('margins')}")
                lines.append(f"  Minimum margin: {margin_summary.get('min_margin')}")
            preds = record.get("predictions") or {}
            if isinstance(preds, dict):
                for wheel in ("W1", "W2", "W4"):
                    pred = preds.get(wheel)
                    if isinstance(pred, dict):
                        lines.append(
                            f"  {wheel}: Top-1={pred.get('top1')} Top-3={pred.get('top3')} margin={pred.get('margin')}"
                        )
            lines.append("")
        lines.extend(
            [
                "FILES",
                f"  Full event log: {store.flow_log_path.name}",
                f"  Full console/hardware log: {store.console_log_path.name}",
                f"  Machine summary: {store.run_summary_path.name}",
                "  MAIN v8 profile/candidate exports remain in this same recognition_results folder.",
            ]
        )
        try:
            store.write_run_summary(summary, "\n".join(lines))
            store.append_flow_event(
                "FINAL_REPORT_WRITTEN",
                {
                    "outcome": summary["outcome"],
                    "detected_code": summary["detected_code"],
                    "evaluation_true_code_posthoc": evaluation_true_code,
                    "full_code_success_posthoc": full_success,
                },
            )
        except Exception as exc:
            self.append_log(f"AUTO RECOGNITION final report warning: {exc}")

    def _auto_write_state(self, *, phase: str, extra: dict[str, object] | None = None) -> None:
        store = self._auto_store
        if store is None:
            return
        predictions = {
            f"W{wheel}": dict(values)
            for wheel, values in self._auto_predictions.items()
        }
        payload: dict[str, object] = {
            "version": 3,
            "workflow": "MAIN_v8_fresh_retry_v1_plus_unlock_v1",
            "phase": phase,
            "active": self._auto_recognition_active,
            "paused": self._auto_recognition_paused,
            "wheel_index": self._auto_wheel_index,
            "component_index": self._auto_component_index,
            "current_code": self._current_code_text(),
            "recognition_pass": {
                "current": self._auto_pass_number,
                "maximum": AUTO_MAX_RECOGNITION_PASSES,
                "pass_start_code": self._auto_pass_start_code,
                "history": list(self._auto_pass_history),
                "pending_randomized_code": self._auto_retry_random_code or None,
                "margin_policy": self._auto_margin_summary(),
            },
            "predictions": predictions,
            "prefix_search": {
                "current_index": self._auto_prefix_index,
                "hypotheses": [item.to_dict() for item in self._auto_prefix_hypotheses],
                "history": list(self._auto_prefix_history),
                "first_pass_failed": self._auto_first_pass_failed,
            },
            "final_code": self._auto_final_code,
            "unlock_detector": {
                "name": "Physical Unlock Detector v1",
                "channel": "audio.wav / contact mic",
                "direction": "CCW",
                "window_ms": [-UNLOCK_PRE_END_MS, UNLOCK_POST_END_MS],
                "rms_threshold": UNLOCK_RMS_THRESHOLD,
                "drms_threshold": UNLOCK_DRMS_THRESHOLD,
                "decision_rule": "RMS > threshold AND dRMS > threshold",
                "positions_checked": self._auto_w3_positions_checked,
                "pending_action": self._auto_w3_pending_action,
                "pending_detection": self._auto_w3_pending_detection,
                "false_detections": list(self._auto_w3_false_detections),
            },
            "model_source_sha256": (
                self._true_gate_engine.source_model_sha256
                if self._true_gate_engine is not None
                else ""
            ),
            "correct_combination_supplied_to_inference": False,
        }
        if extra:
            payload.update(extra)
        try:
            store.save_state(payload)
            store.append_flow_event(
                phase,
                {
                    "pass_number": self._auto_pass_number,
                    "current_code": self._current_code_text(),
                    "wheel_index": self._auto_wheel_index,
                    "component_index": self._auto_component_index,
                    "details": dict(extra or {}),
                },
            )
        except Exception as exc:
            self.append_log(f"AUTO RECOGNITION state/flow-log save warning: {exc}")

    def _start_or_resume_auto_recognition(self) -> None:
        if self._auto_recognition_active:
            if not self._auto_recognition_paused:
                self._show_busy_notice()
                return
            if self._collection_running or self._task_running or self._task_cooldown:
                self._show_busy_notice()
                return
            self._auto_recognition_paused = False
            self._update_auto_recognition_ui()
            if self._auto_pending_transition is not None:
                QTimer.singleShot(0, self._auto_show_prediction_transition)
            elif self._auto_wheel_index >= len(AUTO_WHEELS):
                if self._auto_w3_pending_action == "TRIGGER":
                    QTimer.singleShot(0, self._auto_confirm_w3_trigger)
                elif self._auto_w3_pending_action == "NO_UNLOCK":
                    QTimer.singleShot(0, self._auto_prompt_w3_no_unlock)
                elif self._auto_w3_pending_action == "FRESH_RETRY":
                    QTimer.singleShot(0, self._auto_begin_fresh_retry)
                else:
                    QTimer.singleShot(0, self._auto_start_w3_search)
            elif self._auto_component_index >= len(AUTO_COMPONENTS):
                QTimer.singleShot(0, self._auto_score_current_wheel)
            else:
                QTimer.singleShot(0, self._auto_start_current_component)
            return

        if self._true_gate_engine is None:
            self._show_error(self._true_gate_model_error or "MAIN v8 could not be loaded.")
            return
        if not self.backend.connected:
            self._show_error("Connect the ESP32 and Focusrite before automatic recognition.")
            return
        if self._collection_running or self._task_running or self._task_cooldown or self._csv_batch_active:
            self._show_busy_notice()
            return
        if not self._position_valid:
            self._show_error(
                "Synchronise the visible physical four-digit code in Data Collection first. "
                "The correct combination can remain unknown; the App only needs the CURRENT displayed digits."
            )
            return

        try:
            session_id = validate_session_id(self.auto_recognition_session_edit.text())
            store = AutoRecognitionStore(self._resolved_dataset_path(), session_id)
            store.ensure_new_session()
        except Exception as exc:
            self._show_error(str(exc))
            return

        answer = _themed_question(
            self,
            "Start supervised recognition",
            (
                f"Current synchronised code: {self._current_code_text()}\n\n"
                "The correct password is never requested or used. MAIN v8 will scan W1 → W2 → W4. "
                "Every 10-WAV circle stops for your Re-record / Continue decision, and every A circle requires a fresh loaded reseat. "
                "After scoring, Top-1 is tried first. W3 then runs a continuous CCW 10-position sweep with one WAV per digit. "
                "Physical Unlock Detector v1 only pauses the sweep; you still confirm the lock is actually open. "
                f"If the Top-1 prefix fails and the minimum wheel margin is below {AUTO_RETRY_MARGIN_THRESHOLD:.2f}, the App will randomize all four displayed digits and perform one fresh recognition pass before any long fallback search. "
                "The correct password is still never used by acquisition or inference. A full machine-readable flow log is saved automatically."
            ),
            yes_text="Start recognition",
            no_text="Not now",
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        self._auto_recognition_active = True
        self._auto_recognition_paused = False
        self._auto_recognition_session = session_id
        self._auto_store = store
        self._auto_wheel_index = 0
        self._auto_component_index = 0
        self._auto_pending_results = None
        self._auto_current_start_digits = None
        self._auto_predictions = {}
        self._auto_pending_transition = None
        self._auto_w3_positions_checked = 0
        self._auto_w3_initial_digit = -1
        self._auto_collection_kind = ""
        self._auto_w3_pending_action = ""
        self._auto_w3_pending_detection = None
        self._auto_w3_false_detections = []
        self._auto_final_code = ""
        self._auto_prefix_hypotheses = []
        self._auto_prefix_index = -1
        self._auto_prefix_history = []
        self._auto_first_pass_failed = False
        self._auto_pass_number = 1
        self._auto_pass_history = []
        self._auto_pass_start_code = self._current_code_text()
        self._auto_retry_random_code = ""
        self._auto_started_at = datetime.now().isoformat(timespec="seconds")
        self._auto_reset_table()
        self._auto_write_state(
            phase="STARTED",
            extra={
                "pass_number": self._auto_pass_number,
                "pass_start_code": self._auto_pass_start_code,
                "retry_margin_threshold": AUTO_RETRY_MARGIN_THRESHOLD,
                "max_passes": AUTO_MAX_RECOGNITION_PASSES,
            },
        )
        self._set_auto_status(
            f"Session {session_id} started · pass 1/{AUTO_MAX_RECOGNITION_PASSES}. Correct combination is unknown to the App. Preparing W1 CCW-A."
        )
        self._update_controls()
        QTimer.singleShot(0, self._auto_start_current_component)

    def _stop_auto_recognition(self) -> None:
        if not self._auto_recognition_active:
            return
        if self._collection_running:
            answer = _themed_question(
                self,
                "Stop automatic recognition",
                "A circle is currently recording. Stop the hardware and abort this recognition workflow?",
                yes_text="Stop workflow",
                no_text="Keep running",
                danger_yes=True,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
            self._auto_write_state(phase="STOP_REQUESTED_DURING_CIRCLE")
            self._auto_recognition_active = False
            self._auto_recognition_paused = False
            self._auto_pending_results = None
            self._emergency_stop()
        else:
            self._auto_recognition_active = False
            self._auto_recognition_paused = False
            self._auto_write_state(phase="STOPPED_BY_OPERATOR")
            self._auto_pending_results = None
            self._auto_pending_transition = None
            self._set_auto_status("Workflow stopped by operator. Existing accepted circles remain saved; use a new Session ID for a clean run.")
            self._update_controls()
        self._update_auto_recognition_ui()

    def _auto_pause(self, text: str) -> None:
        self._auto_recognition_paused = True
        self._auto_write_state(phase="PAUSED", extra={"reason": text})
        self._set_auto_status(text + " Click Resume supervised recognition when ready.")
        self._update_controls()

    def _auto_start_current_component(self) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        if self._collection_running or self._task_running or self._task_cooldown:
            QTimer.singleShot(250, self._auto_start_current_component)
            return
        if self._auto_wheel_index >= len(AUTO_WHEELS):
            self._auto_start_w3_search()
            return
        if self._auto_component_index >= len(AUTO_COMPONENTS):
            self._auto_score_current_wheel()
            return
        if not self.backend.connected:
            self._auto_pause("ESP32/audio connection is not available.")
            return
        if not self._position_valid:
            self._auto_pause("Tracked physical code is not synchronised.")
            return

        wheel = AUTO_WHEELS[self._auto_wheel_index]
        direction, repeat_id = AUTO_COMPONENTS[self._auto_component_index]
        code = self._current_code_text()

        # A is the independently reseated observation for each direction.  B
        # follows A without a forced reseat, matching MAIN-v8 acquisition.
        if repeat_id == "A":
            answer = _themed_question(
                self,
                f"Fresh loaded reseat · W{wheel} {direction}-A",
                (
                    f"Physical code: {code}\n\n"
                    "Fully release and reseat the shackle, restore the normal loaded tension, and visually confirm all four digits before recording."
                ),
                yes_text="Load confirmed",
                no_text="Pause",
            )
            if answer is not QMessageBox.StandardButton.Yes:
                self._auto_pause(f"Paused before W{wheel} {direction}-A reseat confirmation.")
                return

        start_digits = tuple(self._current_code_values())
        try:
            requests = self.backend.build_auto_recognition_requests(
                session_id=self._auto_recognition_session,
                wheel_index=wheel,
                direction=direction,
                current_digits=start_digits,
                profile_id=profile_id_for(
                    self._auto_recognition_session, wheel, self._auto_pass_number
                ),
                repeat_id=repeat_id,
                lock_id=self.lock_id_edit.text().strip(),
                scenario=self.scenario_edit.text().strip(),
                tape_version=self.tape_edit.text().strip(),
                microphone_position=self.microphone_edit.text().strip(),
                focusrite_gain=self.gain_edit.text().strip(),
                spring_setting=self.spring_edit.text().strip(),
                dataset_dir=self._resolved_dataset_path(),
                digit_steps=self.digit_steps_spin.value(),
            )
        except Exception as exc:
            self._auto_pause(f"Could not build W{wheel} {direction}-{repeat_id}: {exc}")
            return

        self._auto_current_start_digits = start_digits
        self._auto_pending_results = None
        self._auto_collection_kind = "MAIN_CIRCLE"
        self._set_auto_status(
            f"Recording W{wheel} {direction}-{repeat_id}: 10 one-digit WAVs from code {code}. The App will stop after this circle."
        )
        self._auto_write_state(
            phase="RECORDING_CIRCLE",
            extra={"wheel": wheel, "direction": direction, "repeat_id": repeat_id, "start_code": code},
        )
        self._launch_collection(
            requests=requests,
            row_map=[-1] * len(requests),
            force_stop_on_rejected=True,
            pause_between_runs_s_override=self.pause_spin.value(),
            keep_contact_override=True,
        )

    def _auto_review_current_circle(self) -> None:
        if not self._auto_recognition_active:
            return

        # Reconcile the batch-completed result list with the exact per-run
        # results that drove the live status UI. A rejected/failed item seen by
        # either path must survive into the human checkpoint and re-record path.
        merged_by_run: dict[str, RunResult] = {}
        for item in list(self._auto_pending_results or []) + list(self._active_collection_results):
            if isinstance(item, RunResult):
                merged_by_run[item.request.run_id] = item
        results = list(merged_by_run.values())

        if self._auto_wheel_index >= len(AUTO_WHEELS):
            return
        wheel = AUTO_WHEELS[self._auto_wheel_index]
        direction, repeat_id = AUTO_COMPONENTS[self._auto_component_index]
        start_digits = self._auto_current_start_digits
        if start_digits is None:
            self._auto_pause("Internal error: circle start code was not recorded.")
            return
        start_code = "".join(str(v) for v in start_digits)
        summary = circle_quality_summary(results)

        list_valid = int(summary.get("valid") or 0)
        list_rejected = int(summary.get("rejected") or 0)
        list_failed = int(summary.get("failed") or 0)
        if (
            list_valid != self._valid_count
            or list_rejected != self._rejected_count
            or list_failed != self._failed_count
        ):
            self.append_log(
                "AUTO RECOGNITION circle result reconciliation: "
                f"result-list V/R/F={list_valid}/{list_rejected}/{list_failed}, "
                f"live V/R/F={self._valid_count}/{self._rejected_count}/{self._failed_count}. "
                "Using fail-safe review counts."
            )

        summary["valid"] = max(list_valid, int(self._valid_count))
        summary["rejected"] = max(list_rejected, int(self._rejected_count))
        summary["failed"] = max(list_failed, int(self._failed_count))
        summary["count"] = len(results)

        code_matches = bool(self._position_valid and self._current_code_text() == start_code)
        summary["all_valid"] = bool(
            len(results) == 10
            and int(summary["valid"]) == 10
            and int(summary["rejected"]) == 0
            and int(summary["failed"]) == 0
            and code_matches
        )
        if not code_matches:
            self.append_log(
                f"AUTO RECOGNITION circle code check failed: expected return to {start_code}, tracked {self._current_code_text()}"
            )

        dialog = CircleReviewDialog(
            self,
            wheel=wheel,
            direction=direction,
            repeat_id=repeat_id,
            start_code=start_code,
            summary=summary,
        )
        dialog.exec()

        if dialog.choice == CircleReviewDialog.RETRY:
            try:
                deleted = delete_result_runs(self._resolved_dataset_path(), results)
                self.append_log(
                    f"AUTO RECOGNITION: operator rejected W{wheel} {direction}-{repeat_id}; deleted {deleted} run folder(s)"
                )
            except Exception as exc:
                self._auto_pause(f"Could not safely delete rejected circle: {exc}")
                return
            self._auto_pending_results = None
            self._auto_write_state(
                phase="CIRCLE_RETRY",
                extra={
                    "wheel": wheel,
                    "direction": direction,
                    "repeat_id": repeat_id,
                    "operator_choice": "RE_RECORD",
                    "quality_summary": dict(summary),
                },
            )
            if (not self._position_valid) or self._current_code_text() != start_code:
                restore = CodeTransitionDialog(
                    self,
                    current_code=self._current_code_text(),
                    planned_code=start_code,
                    next_key=f"Restore W{wheel} {direction}-{repeat_id} start before re-record",
                )
                restore.exec()
                if not restore.confirmed:
                    self._auto_pause(
                        f"Paused before re-record. Restore and visually confirm physical code {start_code}."
                    )
                    return
            QTimer.singleShot(0, self._auto_start_current_component)
            return

        if dialog.choice != CircleReviewDialog.CONTINUE:
            self._auto_pause(f"Circle review did not complete for W{wheel} {direction}-{repeat_id}.")
            return

        self._auto_write_state(
            phase="CIRCLE_REVIEW_ACCEPTED",
            extra={
                "wheel": wheel,
                "direction": direction,
                "repeat_id": repeat_id,
                "start_code": start_code,
                "operator_choice": "CONTINUE",
                "quality_summary": dict(summary),
            },
        )

        if self._auto_store is None:
            self._auto_pause("Internal error: automatic-recognition store is unavailable.")
            return
        try:
            output = self._auto_store.write_component(
                wheel=wheel,
                direction=direction,
                repeat_id=repeat_id,
                start_digits=start_digits,
                results=results,
                pass_number=self._auto_pass_number,
            )
        except Exception as exc:
            self._auto_pause(f"Could not accept W{wheel} {direction}-{repeat_id}: {exc}")
            return

        self.append_log(f"AUTO RECOGNITION accepted W{wheel} {direction}-{repeat_id}: {output}")
        self._auto_pending_results = None
        self._auto_component_index += 1
        if self._auto_component_index < len(AUTO_COMPONENTS):
            self._auto_write_state(
                phase="CIRCLE_ACCEPTED",
                extra={"wheel": wheel, "direction": direction, "repeat_id": repeat_id},
            )
            QTimer.singleShot(0, self._auto_start_current_component)
            return

        self._auto_component_index = len(AUTO_COMPONENTS)
        self._auto_write_state(phase="WHEEL_COMPONENTS_COMPLETE", extra={"wheel": wheel})
        QTimer.singleShot(0, self._auto_score_current_wheel)

    def _auto_score_current_wheel(self) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        if self._true_gate_engine is None:
            self._auto_pause("MAIN v8 runtime is not available.")
            return
        if self._auto_wheel_index >= len(AUTO_WHEELS):
            self._auto_start_w3_search()
            return
        wheel = AUTO_WHEELS[self._auto_wheel_index]
        profile_id = profile_id_for(
            self._auto_recognition_session, wheel, self._auto_pass_number
        )
        engine = self._true_gate_engine
        dataset_root = self._resolved_dataset_path()
        self._set_auto_status(f"Running frozen MAIN v8 for W{wheel}. Correct combination remains unknown to the model.")

        # Use a QObject slot: post-prediction UI work must execute on the GUI thread.
        self._auto_scoring_profile_id = profile_id
        self._auto_scoring_wheel = wheel

        started = self._start_task(
            lambda log, root=dataset_root, sid=self._auto_recognition_session, model=engine: model.score_session(
                root,
                sid,
                save_results=True,
                log=log,
            ),
            self._auto_score_task_completed,
            f"MAIN v8 automatic recognition — W{wheel}",
            allow_when_disconnected=True,
        )
        if not started:
            self._auto_pause(f"Could not start MAIN v8 scoring for W{wheel}.")

    @Slot(object)
    def _auto_score_task_completed(self, result: object) -> None:
        """Receive MAIN-v8 worker output on the GUI thread and continue workflow."""
        profile_id = self._auto_scoring_profile_id
        wheel = int(self._auto_scoring_wheel or 0)
        self._auto_scoring_profile_id = ""
        self._auto_scoring_wheel = 0
        if not profile_id or wheel not in AUTO_WHEELS:
            self._auto_pause(
                "MAIN v8 scoring finished, but the expected automatic-recognition profile was lost."
            )
            return
        self._auto_score_result(result, profile_id, wheel)

    def _auto_score_result(self, result: object, profile_id: str, wheel: int) -> None:
        if not self._auto_recognition_active:
            return
        profiles = getattr(result, "profiles", ())
        matches = [
            item
            for item in profiles
            if getattr(item, "profile_id", "") == profile_id
            and int(getattr(item, "wheel", 0) or 0) == wheel
            and getattr(item, "status", "") == "SCORED"
        ]
        if len(matches) != 1:
            self._auto_pause(
                f"MAIN v8 did not return exactly one scored profile for W{wheel}. Check recognition results/logs."
            )
            return
        profile = matches[0]
        pred = getattr(profile, "pred_digit", None)
        if pred is None:
            self._auto_pause(f"MAIN v8 returned no Top-1 digit for W{wheel}.")
            return
        top2 = tuple(int(v) for v in getattr(profile, "top2", ()) or ())
        top3 = tuple(int(v) for v in getattr(profile, "top3", ()) or ())
        margin = getattr(profile, "margin", None)
        fused_scores = tuple(
            (int(digit), float(score))
            for digit, score in (getattr(profile, "fused_scores", ()) or ())
        )
        if len(fused_scores) != 10:
            self._auto_pause(
                f"MAIN v8 returned incomplete fused candidate evidence for W{wheel}; Top-2 fallback cannot be built safely."
            )
            return
        self._auto_predictions[wheel] = {
            "top1": int(pred),
            "top2": list(top2),
            "top3": list(top3),
            "margin": None if margin is None else float(margin),
            "fused_scores": list(fused_scores),
        }

        row = list(AUTO_WHEELS).index(wheel)
        values = [
            f"W{wheel}",
            str(int(pred)),
            " / ".join(str(v) for v in top2) if top2 else "—",
            " / ".join(str(v) for v in top3) if top3 else "—",
            "—" if margin is None else f"{float(margin):.3f}",
            "PREDICTED",
        ]
        for column, value in enumerate(values):
            item = self.auto_recognition_table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.auto_recognition_table.setItem(row, column, item)
            item.setText(value)

        current = self._current_code_values()
        target = list(current)
        target[wheel - 1] = int(pred)
        target_code = "".join(str(v) for v in target)
        self._auto_pending_transition = (wheel, target_code)
        self._auto_write_state(
            phase="WHEEL_PREDICTED",
            extra={
                "wheel": wheel,
                "top1": int(pred),
                "top2": list(top2),
                "top3": list(top3),
                "margin": margin,
                "fused_scores": list(fused_scores),
            },
        )
        self._set_auto_status(
            f"W{wheel} prediction ready: Top-1={int(pred)}, Top-3={list(top3)}, margin={'—' if margin is None else f'{float(margin):.3f}'}. Human-confirm the move to {target_code}."
        )
        QTimer.singleShot(500, self._auto_show_prediction_transition)

    def _auto_show_prediction_transition(self) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        if self._auto_pending_transition is None:
            return
        if self._task_running or self._collection_running or self._task_cooldown:
            QTimer.singleShot(250, self._auto_show_prediction_transition)
            return
        wheel, target_code = self._auto_pending_transition
        prediction = self._auto_predictions.get(wheel, {})
        top3 = prediction.get("top3", [])
        margin = prediction.get("margin")
        current_code = self._current_code_text()
        dialog = CodeTransitionDialog(
            self,
            current_code=current_code,
            planned_code=target_code,
            next_key=(
                f"AUTO W{wheel} Top-1={prediction.get('top1')} | Top-3={top3} | "
                f"margin={'—' if margin is None else f'{float(margin):.3f}'}"
            ),
        )
        dialog.exec()
        if not dialog.confirmed:
            self._auto_pause(
                f"Paused after W{wheel} prediction. The predicted target is {target_code}; physical confirmation was not completed."
            )
            return

        self._auto_pending_transition = None
        row = list(AUTO_WHEELS).index(wheel)
        state_item = self.auto_recognition_table.item(row, 5)
        if state_item is not None:
            state_item.setText("SET + CONFIRMED")
        self._auto_write_state(phase="PREDICTED_WHEEL_SET", extra={"wheel": wheel, "confirmed_code": target_code})
        self._auto_wheel_index += 1
        self._auto_component_index = 0
        self._update_auto_recognition_ui()
        if self._auto_wheel_index < len(AUTO_WHEELS):
            next_wheel = AUTO_WHEELS[self._auto_wheel_index]
            self._set_auto_status(
                f"W{wheel} Top-1 is physically set and confirmed. Preparing W{next_wheel}; its A scan will require a fresh loaded reseat."
            )
            QTimer.singleShot(0, self._auto_start_current_component)
        else:
            try:
                self._auto_prepare_prefix_search()
            except Exception as exc:
                self._auto_pause(f"Could not build evidence-ranked Top-2 fallback queue: {exc}")
                return
            current_hypothesis = self._auto_current_prefix_hypothesis()
            if current_hypothesis is None:
                self._auto_pause("Internal error: prefix search queue is empty after W4 scoring.")
                return
            self._set_auto_status(
                f"W1/W2/W4 Top-1 digits are set. Prefix #1/{len(self._auto_prefix_hypotheses)} "
                f"{current_hypothesis.prefix_text} has joint evidence {current_hypothesis.joint_score:.4f}. "
                "Starting the continuous W3 CCW sweep with Physical Unlock Detector v1."
            )
            QTimer.singleShot(0, self._auto_start_w3_search)

    def _auto_start_w3_search(self) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        if self._collection_running or self._task_running or self._task_cooldown:
            QTimer.singleShot(250, self._auto_start_w3_search)
            return
        if not self.backend.connected:
            self._auto_pause("ESP32/audio connection is not available for W3 unlock search.")
            return
        if not self._position_valid:
            self._auto_pause("Tracked physical code is not synchronised before W3 unlock search.")
            return
        if self.pre_roll_spin.value() + 1e-9 < UNLOCK_PRE_END_MS / 1000.0:
            self._auto_pause(
                f"Unlock Detector v1 requires at least {UNLOCK_PRE_END_MS:.0f} ms pre-roll."
            )
            return
        if self.post_roll_spin.value() + 1e-9 < UNLOCK_POST_END_MS / 1000.0:
            self._auto_pause(
                f"Unlock Detector v1 requires at least {UNLOCK_POST_END_MS:.0f} ms post-roll."
            )
            return

        if self._auto_w3_positions_checked == 0 and self._auto_w3_initial_digit < 0:
            current_code = self._current_code_text()
            hypothesis = self._auto_current_prefix_hypothesis()
            prefix_text = (
                hypothesis.prefix_text
                if hypothesis is not None
                else f"{current_code[0]}{current_code[1]}?{current_code[3]}"
            )
            precheck = _themed_choice(
                self,
                "W3 continuous unlock sweep",
                (
                    f"Prefix {prefix_text} is now physically set.\n"
                    f"Current code: {current_code}\n\n"
                    "If the shackle already opened while the final prefix wheel was being set, finish now. "
                    "Otherwise begin the continuous W3 CCW sweep. This is the only pre-sweep check; there are no per-digit confirmation popups."
                ),
                primary_key="begin",
                primary_text="Begin continuous W3 sweep",
                secondary_key="unlocked",
                secondary_text="Already open — finish",
                cancel_text="Pause workflow",
            )
            if precheck == "unlocked":
                self._auto_finish(unlocked=True, final_code=current_code)
                return
            if precheck != "begin":
                self._auto_pause("Paused before the W3 continuous unlock sweep.")
                return
            self._auto_w3_initial_digit = self._current_code_values()[2]
        self._auto_wheel_index = len(AUTO_WHEELS)
        self._auto_w3_pending_action = ""
        self._auto_w3_pending_detection = None
        self._update_auto_recognition_ui()

        remaining = 10 - int(self._auto_w3_positions_checked)
        if remaining <= 0:
            self._auto_w3_pending_action = "NO_UNLOCK"
            QTimer.singleShot(0, self._auto_prompt_w3_no_unlock)
            return

        hypothesis = self._auto_current_prefix_hypothesis()
        prefix_text = (
            hypothesis.prefix_text
            if hypothesis is not None
            else f"{self._current_code_text()[0]}{self._current_code_text()[1]}?{self._current_code_text()[3]}"
        )
        prefix_rank = hypothesis.rank if hypothesis is not None else 0
        try:
            requests = self.backend.build_auto_unlock_search_requests(
                session_id=self._auto_recognition_session,
                current_digits=tuple(self._current_code_values()),
                lock_id=self.lock_id_edit.text().strip(),
                scenario=self.scenario_edit.text().strip(),
                tape_version=self.tape_edit.text().strip(),
                microphone_position=self.microphone_edit.text().strip(),
                focusrite_gain=self.gain_edit.text().strip(),
                spring_setting=self.spring_edit.text().strip(),
                dataset_dir=self._resolved_dataset_path(),
                moves=remaining,
                move_index_offset=self._auto_w3_positions_checked,
                prefix_rank=prefix_rank,
                prefix_text=prefix_text,
                pass_number=self._auto_pass_number,
                direction="CCW",
                digit_steps=self.digit_steps_spin.value(),
            )
        except Exception as exc:
            self._auto_pause(f"Could not build W3 Unlock Detector v1 sweep: {exc}")
            return

        def stop_after_result(_index: int, result: RunResult) -> str | None:
            if result.output_dir is None:
                return "UNLOCK_DETECTOR_ERROR: run has no output directory"
            try:
                detection = detect_unlock_files(
                    Path(result.output_dir) / "audio.wav",
                    Path(result.output_dir) / "events.csv",
                )
            except Exception as exc:
                return f"UNLOCK_DETECTOR_ERROR: {type(exc).__name__}: {exc}"
            if detection.detected:
                return (
                    "UNLOCK_DETECTOR_V1_TRIGGER "
                    f"RMS={detection.rms:.5f} dRMS={detection.drms:.5f}"
                )
            return None

        start_code = self._current_code_text()
        end_move = self._auto_w3_positions_checked + remaining
        self._auto_pending_results = None
        self._auto_collection_kind = "W3_UNLOCK_SWEEP"
        self._set_auto_status(
            f"W3 continuous CCW sweep for prefix {prefix_text}: positions "
            f"{self._auto_w3_positions_checked + 1}-{end_move}/10 from code {start_code}. "
            "Each digit is saved as its own WAV. Unlock Detector v1 checks every SCAN_END and stops before the next digit if triggered."
        )
        self._auto_write_state(
            phase="W3_UNLOCK_SWEEP_RECORDING",
            extra={
                "prefix_rank": prefix_rank,
                "prefix": prefix_text,
                "segment_start_code": start_code,
                "segment_positions_before": self._auto_w3_positions_checked,
                "segment_planned_moves": remaining,
            },
        )
        self._launch_collection(
            requests=requests,
            row_map=[-1] * len(requests),
            force_stop_on_rejected=True,
            pause_between_runs_s_override=0.0,
            keep_contact_override=True,
            stop_after_result_override=stop_after_result,
        )

    def _auto_process_w3_sweep_results(self) -> None:
        if not self._auto_recognition_active:
            return
        results = list(self._auto_pending_results or [])
        self._auto_pending_results = None
        self._auto_collection_kind = ""
        if not results:
            self._auto_pause("W3 unlock sweep returned no recorded movement.")
            return

        metrics: list[dict[str, object]] = []
        trigger: dict[str, object] | None = None
        detector_error = ""
        for result in results:
            if result.status is not RunStatus.VALID:
                detector_error = (
                    f"W3 movement {result.request.decision_move_index} ended as {result.status.value}."
                )
                break
            if result.output_dir is None:
                detector_error = f"W3 movement {result.request.decision_move_index} has no saved output directory."
                break
            try:
                detection = detect_unlock_files(
                    Path(result.output_dir) / "audio.wav",
                    Path(result.output_dir) / "events.csv",
                )
            except Exception as exc:
                detector_error = (
                    f"Unlock Detector v1 could not score movement {result.request.decision_move_index}: "
                    f"{type(exc).__name__}: {exc}"
                )
                break
            item = {
                "move_index": int(result.request.decision_move_index),
                "run_id": result.request.run_id,
                "before_code": result.request.current_code_before,
                "after_code": result.request.current_code_after,
                "w3_digit": int(result.request.end_digit),
                "rms": float(detection.rms),
                "drms": float(detection.drms),
                "peak": float(detection.peak),
                "clipping_ratio": float(detection.clipping_ratio),
                "detected": bool(detection.detected),
            }
            metrics.append(item)
            if detection.detected and trigger is None:
                trigger = dict(item)

        self._auto_w3_positions_checked += len(results)
        if self._auto_w3_positions_checked > 10:
            self._auto_pause("Internal error: W3 unlock sweep exceeded 10 positions.")
            return

        hypothesis = self._auto_current_prefix_hypothesis()
        self._auto_write_state(
            phase="W3_UNLOCK_SWEEP_SEGMENT_COMPLETE",
            extra={
                "prefix_rank": hypothesis.rank if hypothesis is not None else None,
                "prefix": hypothesis.prefix_text if hypothesis is not None else None,
                "positions_checked": self._auto_w3_positions_checked,
                "segment_results": metrics,
                "detector_error": detector_error or None,
            },
        )

        if detector_error:
            self._auto_pause(detector_error + " The sweep was stopped conservatively; do not continue automatically.")
            return

        if trigger is not None:
            self._auto_w3_pending_detection = trigger
            self._auto_w3_pending_action = "TRIGGER"
            self._set_auto_status(
                f"Possible physical unlock detected at W3={trigger['w3_digit']} "
                f"(RMS {float(trigger['rms']):.4f}, dRMS {float(trigger['drms']):.4f}). Waiting for operator confirmation."
            )
            QTimer.singleShot(0, self._auto_confirm_w3_trigger)
            return

        if self._auto_w3_positions_checked >= 10:
            if self._auto_w3_initial_digit >= 0 and self._current_code_values()[2] != self._auto_w3_initial_digit:
                self._auto_pause(
                    "W3 completed 10 movements but did not return to its recorded start digit. Re-synchronise before continuing."
                )
                return
            self._auto_w3_pending_action = "NO_UNLOCK"
            self._set_auto_status(
                "W3 completed all 10 positions with no Unlock Detector v1 trigger. Operator chooses retry, next ranked prefix, or stop."
            )
            QTimer.singleShot(0, self._auto_prompt_w3_no_unlock)
            return

        # A partial W3 segment is valid only when the synchronous detector stopped the batch.
        self._auto_pause(
            "W3 sweep stopped before 10 positions but no valid Unlock Detector v1 trigger was reconstructed."
        )

    def _auto_confirm_w3_trigger(self) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        trigger = self._auto_w3_pending_detection
        if not trigger:
            self._auto_pause("Unlock confirmation was requested without a detector result.")
            return
        current_code = self._current_code_text()
        hypothesis = self._auto_current_prefix_hypothesis()
        prefix_text = hypothesis.prefix_text if hypothesis is not None else f"{current_code[0]}{current_code[1]}?{current_code[3]}"
        remaining = max(0, 10 - self._auto_w3_positions_checked)
        choice = _themed_choice(
            self,
            "Possible physical unlock detected",
            (
                f"Ranked prefix: {prefix_text}\n"
                f"Current physical code: {current_code}\n"
                f"Possible unlock at W3 = {trigger['w3_digit']}\n\n"
                f"Unlock Detector v1: RMS={float(trigger['rms']):.5f} "
                f"(>{UNLOCK_RMS_THRESHOLD:.2f}), dRMS={float(trigger['drms']):.5f} "
                f"(>{UNLOCK_DRMS_THRESHOLD:.2f})\n"
                f"Remaining W3 positions if this is false: {remaining}\n\n"
                "Audio is only the stop trigger. Confirm the padlock physically."
            ),
            primary_key="unlocked",
            primary_text="Unlocked — finish",
            secondary_key="continue",
            secondary_text="False detection — continue",
            cancel_text="Pause workflow",
        )
        if choice == "unlocked":
            self._auto_w3_pending_action = ""
            self._auto_finish(unlocked=True, final_code=current_code)
            return
        if choice == "continue":
            false_record = {
                **trigger,
                "prefix_rank": hypothesis.rank if hypothesis is not None else None,
                "prefix": prefix_text,
                "operator_result": "FALSE_DETECTION",
            }
            self._auto_w3_false_detections.append(false_record)
            self._auto_w3_pending_detection = None
            self._auto_w3_pending_action = ""
            self._auto_write_state(
                phase="W3_UNLOCK_FALSE_DETECTION",
                extra={
                    "false_detection": false_record,
                    "positions_checked": self._auto_w3_positions_checked,
                },
            )
            if self._auto_w3_positions_checked >= 10:
                self._auto_w3_pending_action = "NO_UNLOCK"
                QTimer.singleShot(0, self._auto_prompt_w3_no_unlock)
            else:
                self._set_auto_status(
                    f"Operator rejected the unlock trigger at W3={trigger['w3_digit']}. Continuing the remaining {10 - self._auto_w3_positions_checked} W3 position(s)."
                )
                QTimer.singleShot(0, self._auto_start_w3_search)
            return
        self._auto_w3_pending_action = "TRIGGER"
        self._auto_pause("Paused at an Unlock Detector v1 trigger before physical confirmation.")

    def _auto_prompt_w3_no_unlock(self) -> None:
        if not self._auto_recognition_active or self._auto_recognition_paused:
            return
        hypothesis = self._auto_current_prefix_hypothesis()
        current_code = self._current_code_text()
        prefix_text = hypothesis.prefix_text if hypothesis is not None else f"{current_code[0]}{current_code[1]}?{current_code[3]}"

        margin_info = self._auto_margin_summary()
        low_confidence = bool(margin_info.get("low_confidence"))
        is_top1_prefix = self._auto_prefix_index == 0
        can_fresh_retry = self._auto_pass_number < AUTO_MAX_RECOGNITION_PASSES
        if is_top1_prefix and can_fresh_retry and low_confidence:
            min_margin = margin_info.get("min_margin")
            self._auto_w3_pending_action = "FRESH_RETRY"
            self._auto_write_state(
                phase="LOW_CONFIDENCE_TOP1_FAILED",
                extra={
                    "prefix": prefix_text,
                    "margin_summary": margin_info,
                    "next_action": "FRESH_RANDOMIZED_RECOGNITION_PASS",
                },
            )
            self._set_auto_status(
                f"Top-1 prefix {prefix_text} completed all 10 W3 positions with no unlock. "
                f"Minimum wheel margin {'—' if min_margin is None else f'{float(min_margin):.3f}'} "
                f"is below the fixed {AUTO_RETRY_MARGIN_THRESHOLD:.2f} retry threshold, so the App will discard this pass ranking and run one fresh randomized recognition pass."
            )
            QTimer.singleShot(0, self._auto_begin_fresh_retry)
            return

        has_fallback = self._auto_has_next_prefix()
        secondary_text = "Try next ranked prefix" if has_fallback else "Finish as failure"
        choice = _themed_choice(
            self,
            "No physical unlock detected",
            (
                f"Prefix {prefix_text} completed all 10 W3 positions.\n"
                "No Unlock Detector v1 trigger was operator-confirmed as a real opening.\n\n"
                f"Recognition pass: {self._auto_pass_number}/{AUTO_MAX_RECOGNITION_PASSES}. "
                "The fresh-retry rule was not triggered (either confidence was above threshold or the retry pass has already been used). "
                "Retry the W3 sweep if you suspect a recording/mechanical issue. Otherwise reject this complete prefix and continue the evidence-ranked fallback search."
            ),
            primary_key="retry",
            primary_text="Retry W3 sweep",
            secondary_key="next",
            secondary_text=secondary_text,
            cancel_text="Stop workflow",
        )
        if choice == "retry":
            self._auto_w3_positions_checked = 0
            self._auto_w3_initial_digit = -1
            self._auto_w3_pending_action = ""
            self._auto_w3_pending_detection = None
            self._auto_write_state(
                phase="W3_UNLOCK_RETRY_REQUESTED",
                extra={"prefix": prefix_text},
            )
            self._set_auto_status(f"Retrying the full W3 continuous sweep for prefix {prefix_text}.")
            QTimer.singleShot(0, self._auto_start_w3_search)
            return
        if choice == "next":
            self._auto_w3_pending_action = ""
            self._auto_w3_pending_detection = None
            if has_fallback:
                self._auto_advance_to_next_prefix(skip_choice=True)
            else:
                self._auto_mark_current_prefix_failed()
                self._auto_finish(unlocked=False, final_code="")
            return
        self._auto_w3_pending_action = "NO_UNLOCK"
        self._stop_auto_recognition()

    def _auto_finish(self, *, unlocked: bool, final_code: str) -> None:
        hypothesis = self._auto_current_prefix_hypothesis()
        if unlocked and hypothesis is not None:
            already_recorded = any(
                int(item.get("rank", -1)) == hypothesis.rank
                and item.get("result") == "UNLOCKED"
                for item in self._auto_prefix_history
            )
            if not already_recorded:
                self._auto_prefix_history.append(
                    {
                        **hypothesis.to_dict(),
                        "result": "UNLOCKED",
                        "w3_positions_checked": int(self._auto_w3_positions_checked),
                        "final_code": final_code,
                    }
                )

        pass_outcome = (
            "UNLOCKED_TOP1"
            if unlocked and self._auto_prefix_index == 0
            else "UNLOCKED_FALLBACK"
            if unlocked
            else "NO_UNLOCK"
        )
        self._auto_record_current_pass(outcome=pass_outcome)

        self._auto_final_code = final_code if unlocked else ""
        session = self._auto_recognition_session
        attempt_number = self._auto_prefix_index + 1 if hypothesis is not None else 0
        total_attempts = len(self._auto_prefix_hypotheses)
        first_pass_success = bool(
            self._auto_pass_history
            and str(self._auto_pass_history[0].get("outcome", "")) == "UNLOCKED_TOP1"
        )

        self._auto_recognition_active = False
        self._auto_recognition_paused = False
        confirmed_detection = dict(self._auto_w3_pending_detection or {}) if unlocked else None
        self._auto_write_state(
            phase="COMPLETED_UNLOCKED" if unlocked else "COMPLETED_NO_UNLOCK",
            extra={
                "unlocked": unlocked,
                "final_detected_code": final_code if unlocked else None,
                "confirmed_unlock_detection": confirmed_detection,
                "w3_positions_checked": self._auto_w3_positions_checked,
                "final_prefix_rank": hypothesis.rank if hypothesis is not None else None,
                "final_prefix": hypothesis.prefix_text if hypothesis is not None else None,
                "prefix_attempt_number": attempt_number,
                "prefix_attempts_available": total_attempts,
                "first_pass_success": first_pass_success,
                "first_pass_failed": self._auto_first_pass_failed,
                "recognition_passes_used": len(self._auto_pass_history),
                "recognition_pass_history": list(self._auto_pass_history),
                "prefix_search_history": list(self._auto_prefix_history),
            },
        )

        # Request optional truth only after inference and physical verification finish.
        evaluation_true_code = self._auto_prompt_evaluation_truth()
        self._auto_write_final_report(
            unlocked=unlocked,
            final_code=final_code if unlocked else "",
            evaluation_true_code=evaluation_true_code,
        )

        self._auto_pending_results = None
        self._auto_pending_transition = None
        self._auto_collection_kind = ""
        self._auto_w3_pending_action = ""
        self._auto_w3_pending_detection = None
        self._update_auto_recognition_ui()
        self._update_controls()

        if unlocked:
            if first_pass_success:
                search_note = "First recognition pass Top-1 prefix succeeded."
            elif self._auto_pass_number > 1 and self._auto_prefix_index == 0:
                search_note = (
                    f"Fresh randomized recognition pass {self._auto_pass_number}/"
                    f"{AUTO_MAX_RECOGNITION_PASSES} Top-1 prefix succeeded."
                )
            else:
                search_note = (
                    f"Unlocked on pass {self._auto_pass_number} evidence-ranked prefix attempt "
                    f"{attempt_number}/{total_attempts}."
                )
            self._set_auto_status(
                f"UNLOCK CONFIRMED by operator. Detected combination: {final_code}. {search_note} Session {session} is complete."
            )
            _themed_information(
                self,
                "Automatic recognition complete",
                (
                    f"Operator confirmed the lock opened.\n\n"
                    f"Detected combination: {final_code}\n"
                    f"{search_note}\n"
                    f"Session: {session}"
                ),
            )
        else:
            tested = sum(1 for item in self._auto_prefix_history if item.get("result") == "NO_UNLOCK")
            self._set_auto_status(
                f"No unlock confirmed. Tested {tested} evidence-ranked prefix hypothesis/hypotheses. Session {session} ended without a full-code success."
            )
            _themed_warning(
                self,
                "Automatic recognition did not unlock",
                (
                    f"No operator-confirmed unlock was found after testing {tested} ranked prefix hypothesis/hypotheses.\n\n"
                    "Each rejected prefix was eliminated only after all 10 W3 digits failed."
                ),
            )
































    def _generate_plan(self) -> None:
        try:
            requests = self._create_requests()
        except Exception as exc:
            self._show_error(str(exc))
            return

        self._requests = requests
        self._plan_start_code = self._current_code_text()
        self._populate_plan_table()
        self.append_log(
            f"Generated {len(self._requests)} acquisition runs "
            f"from code {self._plan_start_code}"
        )
        self._update_controls()

    def _populate_plan_table(self) -> None:
        self.plan_table.setRowCount(len(self._requests))
        for row, request in enumerate(self._requests):
            if request.action_type == ActionType.PROBE.value:
                action_label = "Micro probe"
            elif request.action_type == ActionType.WIDE_PROBE.value:
                action_label = "Wide local probe"
            elif request.action_type == ActionType.BINDING_SWEEP.value:
                action_label = "Binding sweep"
            elif request.action_type == ActionType.BINDING_REFERENCE_SWEEP.value:
                action_label = "Binding reference"
            else:
                action_label = "Digit move"
            values = [
                request.run_id,
                action_label,
                request.current_code_before,
                request.current_code_after,
                str(request.wheel_index),
                request.direction,
                str(request.expected_final_step),
                str(request.repetition),
                "Pending",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {4, 5, 6, 7}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.plan_table.setItem(row, column, item)

        self.collection_progress.setRange(0, max(1, len(self._requests)))
        self.collection_progress.setValue(0)
        self.collection_state_label.setText(
            f"Plan ready: {len(self._requests)} run(s)"
        )
        self._valid_count = 0
        self._rejected_count = 0
        self._failed_count = 0
        self._update_counter()
        if hasattr(self, "total_metric"):
            self.total_metric.setText(str(len(self._requests)))

    def _csv_batch_mode_changed(self) -> None:
        mode = str(self.csv_batch_mode_combo.currentData() or "digit_scan")
        self._csv_batch_task_type = mode
        if mode == "binding_scan":
            self.csv_batch_start_button.setText("Start Binding Scan Batch")
            self.csv_batch_summary_label.setText(
                "Binding Scan mode — import a binding_scan plan. Each probed wheel is one full 10-movement scan, saved as 10 WAVs."
            )
        else:
            self.csv_batch_start_button.setText("Start Digit Scan Batch")
            self.csv_batch_summary_label.setText(
                "Digit Scan mode — import a true-gate Decision Batch plan."
            )

        # Clear a loaded plan when the operator changes workflow mode.
        if self._csv_batch_decisions and any(
            decision.task_type != mode for decision in self._csv_batch_decisions
        ):
            self._csv_batch_plan_path = None
            self._csv_batch_decisions = []
            self.csv_batch_path_edit.clear()
            self.plan_table.setRowCount(0)
            self.total_metric.setText("0")
            self._update_csv_password_guard_label()

    def _import_csv_batch_plan(self) -> None:
        if self._csv_batch_active or self._collection_running or self._task_running:
            self._show_busy_notice()
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import plan-driven batch",
            str(APP_DIR),
            "Batch plans (*.xlsx *.csv);;Excel workbooks (*.xlsx);;CSV files (*.csv);;All files (*)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            decisions = load_decision_batch_csv(path)
        except Exception as exc:
            self._show_error(str(exc))
            return

        task_type = decisions[0].task_type
        if any(decision.task_type != task_type for decision in decisions):
            self._show_error("A plan cannot mix Digit Scan and Binding Scan rows.")
            return

        self._csv_batch_task_type = task_type
        self._csv_batch_reseat_confirmed_keys.clear()
        mode_index = self.csv_batch_mode_combo.findData(task_type)
        if mode_index >= 0:
            self.csv_batch_mode_combo.blockSignals(True)
            self.csv_batch_mode_combo.setCurrentIndex(mode_index)
            self.csv_batch_mode_combo.blockSignals(False)
        self.csv_batch_start_button.setText(
            "Start Binding Scan Batch" if task_type == "binding_scan" else "Start Digit Scan Batch"
        )

        self._csv_batch_plan_path = path
        self._csv_batch_decisions = decisions
        self.csv_batch_path_edit.setText(str(path))
        planned_runs = sum(decision.planned_runs for decision in decisions)

        password_sequence: list[str] = []
        for decision in decisions:
            expected = decision.expected_password
            if expected and (not password_sequence or password_sequence[-1] != expected):
                password_sequence.append(expected)
        password_text = (
            " | Password blocks: " + " → ".join(password_sequence)
            if password_sequence
            else " | No plan password guard declared"
        )
        direction_counts = {"CW": 0, "CCW": 0}
        for decision in decisions:
            direction_counts[decision.direction] = direction_counts.get(decision.direction, 0) + 1

        if task_type == "binding_scan":
            valid_prefix = sum(decision.prefix_valid == 1 for decision in decisions)
            invalid_prefix = len(decisions) - valid_prefix
            expected_counts: dict[int, int] = {}
            for decision in decisions:
                expected_counts[decision.expected_binding_wheel] = (
                    expected_counts.get(decision.expected_binding_wheel, 0) + 1
                )
            label_text = ", ".join(
                ("NONE" if wheel == 0 else f"W{wheel}") + f"={count}"
                for wheel, count in sorted(expected_counts.items())
            )
            probe_text = sorted({decision.scan_order for decision in decisions})
            probe_summary = " / ".join(
                "→".join(f"W{wheel}" for wheel in order) for order in probe_text
            )
            self.csv_batch_summary_label.setText(
                f"Binding Scan: {len(decisions)} row(s), {planned_runs} WAVs | "
                f"CW {direction_counts.get('CW', 0)}, CCW {direction_counts.get('CCW', 0)} | "
                f"prefix VALID {valid_prefix}, INVALID {invalid_prefix} | "
                f"labels {label_text} | probe order {probe_summary}"
                + password_text
            )
        else:
            stage_counts = {40: 0, 30: 0, 20: 0, 10: 0}
            for decision in decisions:
                stage_counts[decision.planned_runs] = stage_counts.get(decision.planned_runs, 0) + 1
            self.csv_batch_summary_label.setText(
                f"Digit Scan: {len(decisions)} enabled decision row(s), {planned_runs} WAVs | "
                f"CW {direction_counts.get('CW', 0)} decision(s), CCW {direction_counts.get('CCW', 0)} decision(s) | "
                f"40-way {stage_counts.get(40, 0)}, 30-way {stage_counts.get(30, 0)}, "
                f"20-way {stage_counts.get(20, 0)}, 10-way {stage_counts.get(10, 0)}"
                + password_text
            )

        self._csv_batch_decision_index = 0
        self._update_csv_password_guard_label()
        self._populate_csv_batch_table()
        self.append_log(f"Imported {decisions[0].workflow_label} plan: {path}")
        self._update_controls()

    def _save_csv_batch_template(self) -> None:
        mode = str(self.csv_batch_mode_combo.currentData() or "digit_scan")
        default_name = (
            "binding_scan_plan_template.csv"
            if mode == "binding_scan"
            else "decision_batch_plan_template.csv"
        )
        title = (
            "Save Binding Scan CSV template"
            if mode == "binding_scan"
            else "Save Decision Batch CSV template"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(APP_DIR / default_name),
            "CSV files (*.csv)",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        try:
            if mode == "binding_scan":
                write_binding_scan_template(path)
            else:
                write_decision_batch_template(path)
        except Exception as exc:
            self._show_error(str(exc))
            return
        self.append_log(f"Saved {'Binding Scan' if mode == 'binding_scan' else 'Decision Batch'} template: {path}")

    def _populate_csv_batch_table(self) -> None:
        self._requests = []
        self._csv_batch_table_rows = {}
        self._csv_batch_row_to_candidate = {}
        rows = sum(decision.planned_runs for decision in self._csv_batch_decisions)

        # Suspend painting and signals while filling large batch preview tables.
        table = self.plan_table
        table.setUpdatesEnabled(False)
        table.blockSignals(True)
        table.setSortingEnabled(False)
        try:
            table.clearContents()
            table.setRowCount(rows)
            row = 0
            for decision_index, decision in enumerate(self._csv_batch_decisions):
                # Use the App's editable Correct combination for preview/runtime labels.
                decision = self._decision_with_ui_truth(decision)
                self._csv_batch_decisions[decision_index] = decision
                for spec in decision_candidate_specs(decision):
                    wheel = int(spec["wheel"])
                    move_index = int(spec["move_index"])
                    candidate_index = int(spec["candidate_index"])
                    self._csv_batch_table_rows[(decision_index, wheel, move_index)] = row
                    self._csv_batch_row_to_candidate[row] = (decision_index, candidate_index)
                    action_label = "Binding Scan" if decision.is_binding_scan else "Decision Digit Scan"
                    status_label = "Binding Pending" if decision.is_binding_scan else "Decision Pending"
                    values = [
                        f"{decision.key}/C{candidate_index:02d}",
                        action_label,
                        str(spec["before_code"]),
                        str(spec["after_code"]),
                        str(wheel),
                        decision.direction,
                        str(self.digit_steps_spin.value()),
                        decision.repeat_id,
                        status_label,
                    ]
                    for column, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        if column in {4, 5, 6, 7}:
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        if column == 8:
                            item.setToolTip(
                                f"workflow={decision.task_type}; profile={decision.profile_id}; group={decision.group_id}; "
                                f"active/probe={decision.active_wheels}; scan_order={decision.scan_order}; "
                                f"direction={decision.direction}; prefix_stage={decision.prefix_stage}; "
                                f"prefix_valid={decision.prefix_valid}; expected_binding_wheel={decision.expected_binding_wheel}; "
                                f"plan row={decision.source_row}"
                            )
                        table.setItem(row, column, item)
                    row += 1
        finally:
            table.blockSignals(False)
            table.setUpdatesEnabled(True)
            table.viewport().update()

        self.collection_progress.setRange(0, max(1, rows))
        self.collection_progress.setValue(0)
        label = "Binding Scan" if self._csv_batch_task_type == "binding_scan" else "Digit Scan"
        self.collection_state_label.setText(
            f"{label} plan ready: {len(self._csv_batch_decisions)} row(s), {rows} WAV(s)"
        )
        self._valid_count = 0
        self._rejected_count = 0
        self._failed_count = 0
        self._update_counter()
        self.total_metric.setText(str(rows))

    def _selected_csv_candidate(self) -> tuple[int, int] | None:
        row = self.plan_table.currentRow()
        if row < 0:
            return None
        return self._csv_batch_row_to_candidate.get(row)

    def _decision_true_digits_from_ui(self) -> tuple[int, int, int, int]:
        values = tuple(int(spin.value()) for spin in self.decision_true_digit_spins)
        return values  # type: ignore[return-value]

    def _decision_true_code_from_ui(self) -> str:
        return "".join(str(v) for v in self._decision_true_digits_from_ui())

    def _plan_password_for_guard(self, decision: DecisionBatchRow | None = None) -> str | None:
        if decision is not None:
            return decision.expected_password
        if not self._csv_batch_decisions:
            return None
        index = min(
            max(0, self._csv_batch_decision_index),
            len(self._csv_batch_decisions) - 1,
        )
        return self._csv_batch_decisions[index].expected_password

    def _update_csv_password_guard_label(self, _value: int = 0) -> None:
        if not hasattr(self, "csv_batch_password_guard_label"):
            return
        current = self._decision_true_code_from_ui()
        expected = self._plan_password_for_guard()
        if expected is None:
            self.csv_batch_password_guard_label.setText(
                f"PLAN PASSWORD  not declared    |    APP CORRECT  {current}"
            )
            self.csv_batch_password_guard_label.setStyleSheet(
                "background:#2b2113;color:#ffd58a;border:1px solid #7a5a22;"
                "border-radius:9px;padding:9px 11px;font-weight:800;font-size:11pt;"
            )
            return
        if current == expected:
            self.csv_batch_password_guard_label.setText(
                f"PLAN PASSWORD  {expected}    |    APP CORRECT  {current}    ✓ READY"
            )
            self.csv_batch_password_guard_label.setStyleSheet(
                "background:#123329;color:#9ff0c9;border:1px solid #2b7458;"
                "border-radius:9px;padding:9px 11px;font-weight:800;font-size:11pt;"
            )
        else:
            self.csv_batch_password_guard_label.setText(
                f"PLAN PASSWORD  {expected}    |    APP CORRECT  {current}    ✗ MISMATCH"
            )
            self.csv_batch_password_guard_label.setStyleSheet(
                "background:#451b24;color:#ffc4cf;border:2px solid #b9465b;"
                "border-radius:9px;padding:9px 11px;font-weight:900;font-size:11pt;"
            )

    def _require_csv_password_match(
        self,
        decision: DecisionBatchRow,
        *,
        action: str,
    ) -> bool:
        expected = decision.expected_password
        current = self._decision_true_code_from_ui()
        self._update_csv_password_guard_label()
        if expected is None:
            # Accept legacy plans without an expected password.
            return True
        if current == expected:
            return True

        self._csv_batch_paused = True
        self._csv_batch_pause_requested = False
        if hasattr(self, "csv_batch_pause_button"):
            self.csv_batch_pause_button.setText("Resume")
        if hasattr(self, "collection_state_label"):
            self.collection_state_label.setText(
                f"PASSWORD MISMATCH — plan {expected}, App {current}"
            )
        if hasattr(self, "csv_batch_summary_label"):
            self.csv_batch_summary_label.setText(
                f"PAUSED: change Correct Combination to {expected} before {decision.key}"
            )
        self.append_log(
            f"PASSWORD GUARD blocked {action}: {decision.key} expects {expected}, "
            f"but App Correct Combination is {current}"
        )
        _themed_warning(
            self,
            "PASSWORD MISMATCH — collection blocked",
            (
                f"The next plan block requires password {expected}.\n\n"
                f"App Correct Combination is still {current}.\n\n"
                f"Collection has been PAUSED before {decision.key}.\n"
                f"Change the physical lock AND the App Correct Combination to {expected}, "
                "then press Resume.\n\n"
                "No candidate from this Decision has been recorded."
            ),
        )
        self._update_controls()
        return False

    def _decision_with_ui_truth(self, decision: DecisionBatchRow) -> DecisionBatchRow:
        """Use the editable UI combination as runtime truth without corrupting planned backgrounds."""
        true_digits = self._decision_true_digits_from_ui()
        if decision.is_binding_scan or decision.preserve_inactive_start:
            # Binding Scan preserves planned prefix states, including intentionally wrong prefixes.
            start_digits = decision.start_digits
        else:
            active = set(decision.active_wheels)
            start_digits = tuple(
                decision.start_digits[index] if (index + 1) in active else true_digits[index]
                for index in range(4)
            )
        return replace(
            decision,
            true_digits=true_digits,
            start_digits=start_digits,  # type: ignore[arg-type]
        )

    def _show_decision_transition(self, decision: DecisionBatchRow) -> bool:
        """Move to the next planned physical code with mandatory human verification.

        A/B repeats with the same start code are deliberately left untouched so
        their mechanical state is not unnecessarily reset.  Whenever the next
        Decision requires a different code, collection pauses and opens the
        transition assistant.  The batch cannot continue until the operator has
        visually confirmed the physical four-wheel code.
        """
        next_index = self._csv_batch_decision_index + 1
        if next_index >= len(self._csv_batch_decisions):
            code = self._current_code_text()
            self.csv_batch_summary_label.setText(
                f"{decision.key} complete — final physical code {code}"
            )
            return True

        next_planned = self._csv_batch_decisions[next_index]

        # Preserve the original sequential-binding consistency check.
        same_chain = bool(
            next_planned.profile_id == decision.profile_id
            and next_planned.repeat_id == decision.repeat_id
        )
        if (
            not decision.is_binding_scan
            and same_chain
            and not decision.preserve_inactive_start
        ):
            wheel = int(decision.binding_wheel)
            expected_active = set(decision.active_wheels) - {wheel}
            if set(next_planned.active_wheels) != expected_active:
                self._show_error(
                    f"Plan mismatch after {decision.key}.\n\n"
                    f"You confirmed W{wheel} as binding, so the next Decision must have "
                    f"active wheels {sorted(expected_active)}.\n"
                    f"The next CSV row has {list(next_planned.active_wheels)}.\n\n"
                    "Collection is paused so the next state cannot be mislabeled."
                )
                return False

        next_runtime = self._decision_with_ui_truth(next_planned)
        target_code = next_runtime.start_code
        current_code = self._current_code_text()

        # Some paired observations require reseating without changing the displayed code.
        if next_planned.force_reseat_before:
            self._csv_batch_paused = True
            self.csv_batch_pause_button.setText("Resume")
            self.collection_state_label.setText(
                f"Full release/reseat required before {next_planned.key} ({next_planned.direction})"
            )
            self.csv_batch_summary_label.setText(
                f"PAUSED FOR REQUIRED RESEAT: keep/restore code {target_code}, then confirm"
            )
            self._update_controls()
            answer = _themed_question(
                self,
                "Required mechanical reseat",
                (
                    f"Before {next_planned.key} ({next_planned.direction}), fully release/reseat the shackle/load.\n\n"
                    f"Required physical start code: {target_code}\n\n"
                    "Do the reseat now. Click Yes only after the mechanical load has been freshly reseated. "
                    "The App will still require the physical code to be correct before recording."
                ),
            )
            if answer is not QMessageBox.StandardButton.Yes:
                self.append_log(
                    f"Required reseat before {next_planned.key} was not confirmed; batch remains paused"
                )
                self._csv_batch_paused = True
                self.csv_batch_pause_button.setText("Resume")
                self._update_controls()
                return False
            self.append_log(
                f"Operator confirmed full mechanical reseat before {next_planned.key} ({next_planned.direction})"
            )
            self._csv_batch_reseat_confirmed_keys.add(next_planned.key)
            # If the code is already correct, reseating alone satisfies the transition.
            if current_code == target_code and self._position_valid:
                self._csv_batch_paused = False
                self.csv_batch_pause_button.setText("Pause after current")
                self.csv_batch_summary_label.setText(
                    f"Reseat confirmed; code {target_code} already correct; preparing {next_planned.key}"
                )
                self._update_controls()
                return True

        # Preserve contact state between A/B repeats when the plan requests it.
        if current_code == target_code and self._position_valid:
            self.csv_batch_summary_label.setText(
                f"{decision.key} complete — next {next_planned.key} uses the same code {target_code}; no repositioning"
            )
            self.append_log(
                f"Code transition skipped: {current_code} already matches next Decision {next_planned.key}"
            )
            return True

        self._csv_batch_paused = True
        self.csv_batch_pause_button.setText("Resume")
        self.collection_state_label.setText(
            f"Set next physical code {current_code} → {target_code} before {next_planned.key} ({next_planned.direction})"
        )
        self.csv_batch_summary_label.setText(
            f"PAUSED FOR HUMAN-CHECKED CODE TRANSITION: {current_code} → {target_code}"
        )
        self._update_controls()

        dialog = CodeTransitionDialog(
            self,
            current_code=current_code,
            planned_code=target_code,
            next_key=next_planned.key,
        )
        result = dialog.exec()

        if result != QDialog.DialogCode.Accepted or not dialog.confirmed:
            self.append_log(
                f"Code transition to {target_code} was not confirmed; Decision Batch remains paused"
            )
            self.collection_state_label.setText(
                f"Decision Batch paused — physical code {target_code} not confirmed"
            )
            self.csv_batch_summary_label.setText(
                f"PAUSED: manually set and confirm {target_code} before {next_planned.key}"
            )
            self._csv_batch_paused = True
            self.csv_batch_pause_button.setText("Resume")
            self._update_controls()
            return False

        self._csv_batch_paused = False
        self.csv_batch_pause_button.setText("Pause after current")
        self.csv_batch_summary_label.setText(
            f"Human confirmed physical code {target_code}; preparing {next_planned.key}"
        )
        self.append_log(
            f"Human-confirmed physical code transition: {current_code} -> {target_code}"
        )
        self._update_controls()
        return True

    def _decision_final_dir(self, decision: DecisionBatchRow) -> Path:
        return (
            self._resolved_dataset_path()
            / decision.storage_root
            / self.session_id_edit.text().strip()
            / decision.key
        )

    def _start_csv_batch(self) -> None:
        if not self.backend.connected:
            self._show_error("Connect the ESP32 and Focusrite first.")
            return
        if self._collection_running or self._task_running:
            self._show_busy_notice()
            return
        if self._csv_batch_active and not self._csv_batch_paused:
            self._show_busy_notice()
            return
        if not self._csv_batch_decisions or self._csv_batch_plan_path is None:
            self._show_error("Import a valid Decision Batch plan first.")
            return
        if not self.session_id_edit.text().strip():
            self._show_error("Session ID cannot be empty.")
            return

        first_index = None
        for index, decision in enumerate(self._csv_batch_decisions):
            if not self._decision_final_dir(decision).exists():
                first_index = index
                break
        if first_index is None:
            _themed_information(
                self,
                "Plan-driven Batch",
                "All plan rows are already finalised.",
            )
            return

        first_decision = self._csv_batch_decisions[first_index]
        self._csv_batch_decision_index = first_index
        if not self._require_csv_password_match(
            first_decision, action="Decision Batch start"
        ):
            # Batch is not active yet; keep it idle but visibly blocked.
            self._csv_batch_paused = False
            self._update_controls()
            return

        planned_runs = sum(
            decision.planned_runs
            for decision in self._csv_batch_decisions[first_index:]
            if not self._decision_final_dir(decision).exists()
        )
        truth_text = "".join(str(v) for v in self._decision_true_digits_from_ui())
        workflow = "Binding Scan" if first_decision.is_binding_scan else "Digit Scan Decision"
        detail = (
            "Each probed wheel performs one full revolution as ten one-digit WAVs. "
            "Binding labels are scan-level only; there is no per-digit true-gate target."
            if first_decision.is_binding_scan
            else
            "Each Decision runs continuously with no manual wheel-by-wheel pause. "
            "Every one-digit movement is saved as its own WAV with true-gate labels in metadata."
        )
        answer = _themed_question(
            self,
            f"Start {workflow} Batch",
            (
                f"Start / resume from {self._csv_batch_decisions[first_index].key}?\n\n"
                f"Known lock combination: {truth_text}\n"
                f"Remaining planned WAVs: {planned_runs}.\n"
                f"{detail}\n\n"
                "Pause finishes the current WAV and stops before the next movement."
            ),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return

        self._csv_batch_active = True
        self._csv_batch_paused = False
        self._csv_batch_pause_requested = False
        self._csv_batch_decision_index = first_index
        self._csv_batch_pending_advance = False
        self.append_log(
            f"{'Binding Scan' if first_decision.is_binding_scan else 'Decision Batch'} started / resumed"
        )
        self._update_controls()
        QTimer.singleShot(0, self._prepare_csv_decision)

    def _prepare_csv_decision(self) -> None:
        if not self._csv_batch_active or self._csv_batch_paused:
            return
        while self._csv_batch_decision_index < len(self._csv_batch_decisions):
            decision = self._csv_batch_decisions[self._csv_batch_decision_index]
            if not self._decision_final_dir(decision).exists():
                break
            self._csv_batch_decision_index += 1
        if self._csv_batch_decision_index >= len(self._csv_batch_decisions):
            self._finish_csv_batch()
            return

        planned_decision = self._csv_batch_decisions[self._csv_batch_decision_index]
        if not self._require_csv_password_match(
            planned_decision,
            action=("next Binding Scan preparation" if planned_decision.is_binding_scan else "next Decision preparation"),
        ):
            return
        decision = self._decision_with_ui_truth(planned_decision)
        self._csv_batch_decisions[self._csv_batch_decision_index] = decision
        self._update_csv_password_guard_label()
        plan_file = self._csv_batch_plan_path or Path("")
        progress_payload = self._csv_batch_progress.load(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )
        progress_candidates = progress_payload.get("candidates", {})
        if isinstance(progress_candidates, dict) and progress_candidates:
            stored_binding = int(progress_payload.get("binding_wheel", decision.binding_wheel))
            stored_true = tuple(int(v) for v in progress_payload.get("true_digits", decision.true_digits))
            if stored_true != decision.true_digits:
                stored_text = "".join(str(v) for v in stored_true)
                current_text = "".join(str(v) for v in decision.true_digits)
                self._csv_batch_paused = True
                self.csv_batch_pause_button.setText("Resume")
                self.csv_batch_summary_label.setText(
                    f"PAUSED: existing progress for {decision.key} belongs to password {stored_text}"
                )
                self.collection_state_label.setText(
                    f"PROGRESS PASSWORD MISMATCH — stored {stored_text}, App {current_text}"
                )
                self.append_log(
                    f"PASSWORD GUARD: {decision.key} progress stores {stored_text}, "
                    f"App currently has {current_text}; UI password was NOT changed"
                )
                _themed_warning(
                    self,
                    "Existing progress uses a different password",
                    (
                        f"{decision.key} already has progress recorded with password {stored_text}.\n\n"
                        f"The App currently shows {current_text}.\n\n"
                        "The App will NOT overwrite your Correct Combination. "
                        "Use the matching password to resume this Decision, or use a new Session ID "
                        "if you intend to recollect it under another password."
                    ),
                )
                self._update_controls()
                return
            if decision.is_binding_scan:
                stored_stage = int(progress_payload.get("prefix_stage", decision.prefix_stage))
                stored_valid = int(progress_payload.get("prefix_valid", decision.prefix_valid))
                stored_expected = int(
                    progress_payload.get("expected_binding_wheel", decision.expected_binding_wheel)
                )
                if (
                    stored_stage != decision.prefix_stage
                    or stored_valid != decision.prefix_valid
                    or stored_expected != decision.expected_binding_wheel
                ):
                    self._csv_batch_paused = True
                    self.csv_batch_pause_button.setText("Resume")
                    self._show_error(
                        f"Existing Binding Scan progress for {decision.key} has different labels.\n\n"
                        f"Stored: stage={stored_stage}, valid={stored_valid}, expected_binding={stored_expected}\n"
                        f"Plan: stage={decision.prefix_stage}, valid={decision.prefix_valid}, "
                        f"expected_binding={decision.expected_binding_wheel}\n\n"
                        "Use the original plan or a new Session ID; labels will not be silently changed."
                    )
                    self._update_controls()
                    return
            elif stored_binding != decision.binding_wheel:
                decision = replace(decision, binding_wheel=stored_binding)
                self._csv_batch_decisions[self._csv_batch_decision_index] = decision
        start_index = self._csv_batch_progress.first_missing_index(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )
        if start_index is None:
            try:
                output = self._csv_batch_finalizer.finalise_decision(
                    dataset_dir=self._resolved_dataset_path(),
                    session_id=self.session_id_edit.text().strip(),
                    plan_file=plan_file,
                    decision=decision,
                    progress_store=self._csv_batch_progress,
                )
            except Exception as exc:
                self._show_error(f"Could not finalise {decision.key}:\n{exc}")
                self._csv_batch_paused = True
                self._update_controls()
                return
            self.append_log(f"Finalised Decision {decision.key}: {output}")
            if not self._show_decision_transition(decision):
                self._csv_batch_paused = True
                self.csv_batch_pause_button.setText("Resume")
                self._update_controls()
                return
            self._csv_batch_decision_index += 1
            QTimer.singleShot(0, self._prepare_csv_decision)
            return

        self._prompt_and_start_csv_from_index(start_index)

    def _prompt_and_start_csv_from_index(self, start_index: int) -> None:
        if not self._csv_batch_active:
            return
        decision = self._csv_batch_decisions[self._csv_batch_decision_index]
        if not self._require_csv_password_match(
            decision,
            action=("Binding Scan start prompt" if decision.is_binding_scan else "candidate start prompt"),
        ):
            return
        plan_file = self._csv_batch_plan_path or Path("")
        existing_records = self._csv_batch_progress.records(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )

        if (
            start_index == 1
            and not existing_records
            and decision.force_reseat_before
            and decision.key not in self._csv_batch_reseat_confirmed_keys
        ):
            answer = _themed_question(
                self,
                "Required mechanical reseat",
                (
                    f"Before {decision.key} ({decision.direction}), fully release/reseat the shackle/load.\n\n"
                    f"Required physical start code: {decision.start_code}\n\n"
                    "Click Yes only after the mechanical state has been freshly reseated and the displayed code is correct."
                ),
            )
            if answer is not QMessageBox.StandardButton.Yes:
                self._csv_batch_paused = True
                self.csv_batch_pause_button.setText("Resume")
                self._update_controls()
                return
            self._csv_batch_reseat_confirmed_keys.add(decision.key)
            self.append_log(f"Operator confirmed full mechanical reseat before {decision.key}")

        # Binding Scan labels are plan-defined; Digit Scan keeps the operator override.
        if not decision.is_binding_scan and start_index == 1 and not existing_records:
            wheel_options = [f"W{wheel}" for wheel in decision.active_wheels]
            default_text = f"W{decision.binding_wheel}"
            default_index = (
                wheel_options.index(default_text) if default_text in wheel_options else 0
            )
            selected, accepted = _themed_item_choice(
                self,
                f"Confirm binding wheel — {decision.key}",
                (
                    "First confirm the physical code for this Decision.\n"
                    "Then manually confirm the CURRENT binding wheel."
                ),
                wheel_options,
                default_index,
            )
            if not accepted:
                self._csv_batch_paused = True
                self._update_controls()
                return
            confirmed_wheel = int(str(selected).replace("W", ""))
            if confirmed_wheel != decision.binding_wheel:
                decision = replace(decision, binding_wheel=confirmed_wheel)
                self._csv_batch_decisions[self._csv_batch_decision_index] = decision
                self.append_log(
                    f"Binding label overridden for {decision.key}: W{confirmed_wheel}"
                )

        specs = decision_candidate_specs(decision)
        if start_index not in range(1, len(specs) + 1):
            self._show_error("Resume movement index is out of range.")
            return
        spec = specs[start_index - 1]
        remaining = decision.planned_runs - start_index + 1
        active_text = ", ".join(f"W{wheel}" for wheel in decision.active_wheels)
        scan_text = " → ".join(f"W{wheel}" for wheel in decision.scan_order)
        truth_text = "".join(str(v) for v in decision.true_digits)

        if decision.is_binding_scan:
            expected_text = (
                ("UNKNOWN / comparison" if decision.prefix_valid == 1 else "NONE / invalid-prefix")
                if decision.expected_binding_wheel == 0
                else f"W{decision.expected_binding_wheel}"
            )
            valid_text = "VALID" if decision.prefix_valid == 1 else "INVALID"
            title = f"Start {decision.planned_runs}-WAV Binding Scan — {decision.key}"
            body = (
                f"Physical code to set / confirm: {spec['before_code']}\n"
                f"Known lock combination: {truth_text}\n\n"
                f"Prefix stage: {decision.prefix_stage}\n"
                f"Prefix label: {valid_text}\n"
                f"Expected next binding label: {expected_text}\n\n"
                f"Probe wheels: {active_text}\n"
                f"Continuous probe order: {scan_text}\n"
                f"Direction: {decision.direction}\n\n"
                f"Resume WAV: {start_index}/{decision.planned_runs}\n"
                f"WAVs to record now: {remaining}\n\n"
                "After Yes, every probe wheel makes one full revolution as ten one-digit movements. "
                "Each movement is saved as its own WAV. There is NO per-digit true-gate target in Binding Scan. "
                "The prefix/binding label is stored at scan level."
            )
        else:
            title = f"Step 3 — Start {decision.planned_runs}-candidate Decision — {decision.key}"
            body = (
                f"Physical code to set / confirm: {spec['before_code']}\n"
                f"Training correct combination: {truth_text}\n\n"
                f"Active wheels: {active_text}\n"
                f"Continuous scan order: {scan_text}\n"
                f"Direction: {decision.direction}\n"
                f"Confirmed binding wheel: W{decision.binding_wheel}\n"
                f"Correct digit for W{decision.binding_wheel}: {decision.target_digit}\n\n"
                f"Resume candidate: {start_index}/{decision.planned_runs}\n"
                f"Candidates to record now: {remaining}\n\n"
                "After Yes, all remaining candidates run automatically. At the end the App will STOP, "
                "tell you which wheel to set to its correct digit, and only then move to the next "
                "binding-wheel confirmation."
            )

        answer = _themed_question(self, title, body)
        if answer is not QMessageBox.StandardButton.Yes:
            self._csv_batch_paused = True
            self.collection_state_label.setText(
                f"{'Binding Scan' if decision.is_binding_scan else 'Decision Batch'} paused before "
                f"{decision.key} C{start_index:02d}"
            )
            self._update_controls()
            return

        self._apply_current_code(str(spec["before_code"]), valid=True)
        self._csv_batch_paused = False
        self._csv_batch_pause_requested = False
        self._start_csv_decision_from_index(start_index)

    def _start_csv_decision_from_index(self, start_index: int) -> None:
        decision = self._csv_batch_decisions[self._csv_batch_decision_index]
        if not self._require_csv_password_match(
            decision,
            action=("actual Binding Scan recording start" if decision.is_binding_scan else "actual recording start"),
        ):
            return
        try:
            if decision.is_binding_scan:
                requests = self.backend.build_binding_scan_requests(
                    session_id=self.session_id_edit.text().strip(),
                    scan_order=decision.scan_order,
                    direction=decision.direction,
                    current_digits=list(decision.start_digits),
                    true_digits=list(decision.true_digits),
                    prefix_stage=decision.prefix_stage,
                    prefix_valid=decision.prefix_valid,
                    expected_binding_wheel=decision.expected_binding_wheel,
                    lock_id=self.lock_id_edit.text().strip(),
                    scenario=self.scenario_edit.text().strip(),
                    tape_version=self.tape_edit.text().strip(),
                    microphone_position=self.microphone_edit.text().strip(),
                    focusrite_gain=self.gain_edit.text().strip(),
                    spring_setting=self.spring_edit.text().strip(),
                    dataset_dir=self._resolved_dataset_path(),
                    start_candidate_index=start_index,
                    digit_steps=self.digit_steps_spin.value(),
                )
            else:
                requests = self.backend.build_continuous_decision_requests(
                    session_id=self.session_id_edit.text().strip(),
                    scan_order=decision.scan_order,
                    direction=decision.direction,
                    current_digits=list(decision.start_digits),
                    binding_wheel=decision.binding_wheel,
                    true_digits=list(decision.true_digits),
                    lock_id=self.lock_id_edit.text().strip(),
                    scenario=self.scenario_edit.text().strip(),
                    tape_version=self.tape_edit.text().strip(),
                    microphone_position=self.microphone_edit.text().strip(),
                    focusrite_gain=self.gain_edit.text().strip(),
                    spring_setting=self.spring_edit.text().strip(),
                    dataset_dir=self._resolved_dataset_path(),
                    start_candidate_index=start_index,
                    digit_steps=self.digit_steps_spin.value(),
                )
        except Exception as exc:
            self._show_error(str(exc))
            self._csv_batch_paused = True
            self._update_controls()
            return

        plan_id = self._csv_batch_plan_path.name if self._csv_batch_plan_path else ""
        active_mask = decision.active_mask
        annotated: list[RunRequest] = []
        row_map: list[int] = []
        for request in requests:
            if decision.is_binding_scan:
                expected_text = (
                    "NONE" if decision.expected_binding_wheel == 0
                    else f"W{decision.expected_binding_wheel}"
                )
                workflow_note = (
                    f"binding_scan; prefix_stage={decision.prefix_stage}; "
                    f"prefix_valid={decision.prefix_valid}; expected_binding={expected_text}; "
                    f"probe_wheel=W{request.wheel_index}"
                )
            else:
                workflow_note = (
                    f"binding=W{decision.binding_wheel}; target_digit={decision.target_digit}; "
                    f"target={request.decision_is_target}; "
                    f"true_gate_move={request.decision_is_true_gate_movement}"
                )

            annotated_request = replace(
                request,
                profile_id=decision.profile_id,
                group_id=decision.group_id,
                decision_id=decision.decision_id,
                decision_repeat_id=decision.repeat_id,
                decision_active_w1=active_mask[0],
                decision_active_w2=active_mask[1],
                decision_active_w3=active_mask[2],
                decision_active_w4=active_mask[3],
                decision_binding_confidence=decision.binding_confidence,
                batch_task_type=decision.task_type,
                binding_prefix_stage=decision.prefix_stage,
                binding_prefix_valid=decision.prefix_valid,
                binding_expected_wheel=decision.expected_binding_wheel,
                binding_probe_wheel=request.wheel_index if decision.is_binding_scan else 0,
                batch_plan_id=plan_id,
                batch_plan_source_row=decision.source_row,
                notes=(
                    f"{request.notes}; profile={decision.profile_id}; group={decision.group_id}; "
                    f"decision={decision.decision_id}; repeat={decision.repeat_id}; direction={decision.direction}; "
                    f"workflow={decision.task_type}; {workflow_note}; {decision.notes}"
                ).strip("; "),
            )
            annotated.append(annotated_request)
            row = self._csv_batch_table_rows[
                (
                    self._csv_batch_decision_index,
                    annotated_request.wheel_index,
                    annotated_request.decision_move_index,
                )
            ]
            row_map.append(row)
            run_item = self.plan_table.item(row, 0)
            if run_item is not None:
                run_item.setText(annotated_request.run_id)
            status_item = self.plan_table.item(row, 8)
            if status_item is not None:
                status_item.setText("Queued")

        workflow = "Binding Scan" if decision.is_binding_scan else "Decision"
        self.collection_state_label.setText(
            f"{decision.key}: {workflow} WAVs {start_index}-{decision.planned_runs}"
        )
        self._launch_collection(
            requests=annotated,
            row_map=row_map,
            force_stop_on_rejected=True,
            pause_between_runs_s_override=self.pause_spin.value(),
        )

    def _pause_csv_batch(self) -> None:
        if not self._csv_batch_active:
            return
        if self._csv_batch_paused and not self._collection_running:
            self._csv_batch_paused = False
            self.csv_batch_pause_button.setText("Pause after current")
            self._update_controls()
            self._prepare_csv_decision()
            return
        if not self._collection_running:
            self._csv_batch_paused = True
            self._update_controls()
            return
        if self._csv_batch_pause_requested:
            return
        self._csv_batch_pause_requested = True
        self.backend.request_graceful_batch_stop()
        self.csv_batch_pause_button.setText("Pausing…")
        self.collection_state_label.setText("Pause requested — finishing current WAV")
        self.append_log("Decision Batch pause requested after current run")
        self._update_controls()

    def _start_csv_from_selected(self) -> None:
        if self._collection_running or self._task_running:
            self._show_error("Pause or stop the current collection before choosing a resume point.")
            return
        selected = self._selected_csv_candidate()
        if selected is None:
            self._show_error("Select a Decision candidate row in the plan table first.")
            return
        decision_index, candidate_index = selected
        planned_decision = self._csv_batch_decisions[decision_index]
        self._csv_batch_decision_index = decision_index
        if not self._require_csv_password_match(
            planned_decision, action="resume from selected candidate"
        ):
            return
        decision = self._decision_with_ui_truth(planned_decision)
        self._csv_batch_decisions[decision_index] = decision
        if self._decision_final_dir(decision).exists():
            self._show_error(f"{decision.key} is already finalised. Use a new Session ID to recollect it.")
            return
        if not self.session_id_edit.text().strip():
            self._show_error("Session ID cannot be empty.")
            return

        plan_file = self._csv_batch_plan_path or Path("")
        valid = self._csv_batch_progress.valid_indices(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )
        missing_before = [i for i in range(1, candidate_index) if i not in valid]
        if missing_before:
            self._show_error(
                f"Cannot resume at candidate {candidate_index}: earlier candidates are missing. "
                f"First missing is {missing_before[0]}."
            )
            return

        recorded_records = self._csv_batch_progress.records(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )
        recorded_from_here = [
            int(record.get("candidate_index", 0))
            for record in recorded_records
            if int(record.get("candidate_index", 0)) >= candidate_index
        ]
        if recorded_from_here:
            answer = _themed_question(
                self,
                "Re-record from selected candidate",
                (
                    f"{len(recorded_from_here)} recorded candidate(s) at or after C{candidate_index:02d} "
                    "will be deleted before resuming. Continue?"
                ),
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
            deleted = self._csv_batch_progress.delete_from_index(
                dataset_dir=self._resolved_dataset_path(),
                session_id=self.session_id_edit.text().strip(),
                decision=decision,
                plan_file=plan_file,
                start_index=candidate_index,
            )
            self.append_log(f"Deleted {deleted} candidate run(s) from {decision.key} C{candidate_index:02d}")
            for row, mapping in self._csv_batch_row_to_candidate.items():
                if mapping[0] == decision_index and mapping[1] >= candidate_index:
                    item = self.plan_table.item(row, 8)
                    if item is not None:
                        item.setText("Decision Pending")
                        item.setForeground(QColor("#e9eef7"))

        self._csv_batch_active = True
        self._csv_batch_paused = False
        self._csv_batch_pause_requested = False
        self._csv_batch_decision_index = decision_index
        self._update_controls()
        self._prompt_and_start_csv_from_index(candidate_index)

    def _delete_last_csv_candidate(self) -> None:
        if not self._csv_batch_active or self._collection_running or not self._csv_batch_paused:
            self._show_error("Pause the Decision Batch first, then use Delete last.")
            return
        decision = self._csv_batch_decisions[self._csv_batch_decision_index]
        plan_file = self._csv_batch_plan_path or Path("")
        records = self._csv_batch_progress.records(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )
        if not records:
            self._show_error("There is no recorded candidate to delete in the current Decision.")
            return
        last_index = max(int(record.get("candidate_index", 0)) for record in records)
        spec = decision_candidate_specs(decision)[last_index - 1]
        answer = _themed_question(
            self,
            "Delete last candidate",
            (
                f"Delete {decision.key} candidate C{last_index:02d} "
                f"(W{spec['wheel']} {spec['from_digit']}→{spec['to_digit']})?\n\n"
                "Its raw run folder and progress entry will be removed."
            ),
        )
        if answer is not QMessageBox.StandardButton.Yes:
            return
        deleted = self._csv_batch_progress.delete_from_index(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
            start_index=last_index,
        )
        row = next(
            (
                table_row
                for table_row, mapping in self._csv_batch_row_to_candidate.items()
                if mapping == (self._csv_batch_decision_index, last_index)
            ),
            -1,
        )
        if row >= 0:
            self.plan_table.selectRow(row)
            item = self.plan_table.item(row, 8)
            if item is not None:
                item.setText("DELETED — re-record")
                item.setForeground(QColor("#ff7f91"))
        self.collection_state_label.setText(
            f"Deleted C{last_index:02d}; restore code {spec['before_code']} then resume from selected"
        )
        self.append_log(f"Deleted {deleted} run(s) from {decision.key} starting C{last_index:02d}")
        self._update_controls()

    def _advance_csv_batch(self) -> None:
        if not self._csv_batch_active:
            return
        decision = self._csv_batch_decisions[self._csv_batch_decision_index]
        plan_file = self._csv_batch_plan_path or Path("")

        if self._csv_batch_pause_requested:
            self._csv_batch_pause_requested = False
            self._csv_batch_paused = True
            missing = self._csv_batch_progress.first_missing_index(
                dataset_dir=self._resolved_dataset_path(),
                session_id=self.session_id_edit.text().strip(),
                decision=decision,
                plan_file=plan_file,
            )
            text = "complete" if missing is None else f"next C{missing:02d}"
            self.csv_batch_summary_label.setText(f"Paused: {decision.key}, {text}")
            self.collection_state_label.setText(f"Decision Batch paused — {decision.key}, {text}")
            self.csv_batch_pause_button.setText("Resume")
            self.append_log(f"Decision Batch paused at {decision.key}: {text}")
            self._update_controls()
            return

        missing = self._csv_batch_progress.first_missing_index(
            dataset_dir=self._resolved_dataset_path(),
            session_id=self.session_id_edit.text().strip(),
            decision=decision,
            plan_file=plan_file,
        )
        if missing is not None:
            self._csv_batch_paused = True
            self.csv_batch_pause_button.setText("Resume")
            row = next(
                (
                    table_row
                    for table_row, mapping in self._csv_batch_row_to_candidate.items()
                    if mapping == (self._csv_batch_decision_index, missing)
                ),
                -1,
            )
            if row >= 0:
                self.plan_table.selectRow(row)
            self.collection_state_label.setText(
                f"Decision stopped before C{missing:02d}; review/delete then resume"
            )
            self.csv_batch_summary_label.setText(
                f"Paused after rejected/failed run: {decision.key}, resume C{missing:02d}"
            )
            self._update_controls()
            return

        try:
            output = self._csv_batch_finalizer.finalise_decision(
                dataset_dir=self._resolved_dataset_path(),
                session_id=self.session_id_edit.text().strip(),
                plan_file=plan_file,
                decision=decision,
                progress_store=self._csv_batch_progress,
            )
        except Exception as exc:
            self._show_error(f"Decision {decision.key} finalisation failed:\n{exc}")
            self._csv_batch_paused = True
            self.csv_batch_pause_button.setText("Resume")
            self._update_controls()
            return

        self.append_log(f"Finalised Decision {decision.key}: {output}")
        if not self._show_decision_transition(decision):
            self._csv_batch_paused = True
            self.csv_batch_pause_button.setText("Resume")
            self.collection_state_label.setText(
                f"Decision Batch paused after {decision.key} — plan/state mismatch"
            )
            self._update_controls()
            return
        self._csv_batch_decision_index += 1
        self._csv_batch_paused = False
        self.csv_batch_pause_button.setText("Pause after current")
        QTimer.singleShot(0, self._prepare_csv_decision)

    def _finish_csv_batch(self) -> None:
        completed = sum(
            1 for decision in self._csv_batch_decisions if self._decision_final_dir(decision).exists()
        )
        planned_runs = sum(decision.planned_runs for decision in self._csv_batch_decisions)
        is_binding = bool(
            self._csv_batch_decisions and self._csv_batch_decisions[0].is_binding_scan
        )
        workflow = "Binding Scan" if is_binding else "Digit Scan Batch"
        self._csv_batch_active = False
        self._csv_batch_paused = False
        self._csv_batch_pause_requested = False
        self._csv_batch_pending_advance = False
        self.csv_batch_pause_button.setText("Pause after current")
        self.csv_batch_summary_label.setText(
            f"{workflow} completed: {completed} row(s), plan total {planned_runs} WAV(s)"
        )
        self._update_csv_password_guard_label()
        self.collection_state_label.setText(f"{workflow} completed")
        self.append_log(f"{workflow} completed: {completed} row(s)")
        if hasattr(self, "signal_review_panel"):
            self.signal_review_panel.refresh_runs(preserve_current=True)
        self._update_controls()
        _themed_information(
            self,
            f"{workflow} completed",
            f"Finalised {completed} plan row(s).",
        )

    def _cancel_csv_batch(self) -> None:
        was_active = self._csv_batch_active
        self._csv_batch_active = False
        self._csv_batch_paused = False
        self._csv_batch_pause_requested = False
        self._csv_batch_pending_advance = False
        self._csv_batch_reseat_confirmed_keys.clear()
        self.csv_batch_pause_button.setText("Pause after current")
        if was_active:
            self.csv_batch_summary_label.setText(
                f"{'Binding Scan' if self._csv_batch_task_type == 'binding_scan' else 'Digit Scan Batch'} cancelled"
            )
            self.collection_state_label.setText(
                f"{'Binding Scan' if self._csv_batch_task_type == 'binding_scan' else 'Digit Scan Batch'} cancelled"
            )
            self.append_log(
                f"{'Binding Scan' if self._csv_batch_task_type == 'binding_scan' else 'Digit Scan Batch'} cancelled"
            )
        if self._collection_running:
            self._emergency_stop()
        self._update_controls()

    def _refresh_wheel_order_badges(self) -> None:
        selected = {
            wheel
            for wheel, check in enumerate(self.wheel_checks, start=1)
            if check.isChecked()
        }
        self._wheel_collection_order = [
            wheel
            for wheel in self._wheel_collection_order
            if wheel in selected
        ]
        for wheel in range(1, 5):
            if wheel in selected and wheel not in self._wheel_collection_order:
                self._wheel_collection_order.append(wheel)

        order_map = {
            wheel: order
            for order, wheel in enumerate(self._wheel_collection_order, start=1)
        }
        for wheel, check in enumerate(self.wheel_checks, start=1):
            check.set_order_number(order_map.get(wheel))

    def _wheel_collect_toggled(self, wheel: int, checked: bool) -> None:
        if checked:
            if wheel not in self._wheel_collection_order:
                self._wheel_collection_order.append(wheel)
        else:
            self._wheel_collection_order = [
                value
                for value in self._wheel_collection_order
                if value != wheel
            ]
        self._refresh_wheel_order_badges()

        self._requests = []
        if hasattr(self, "plan_table"):
            self.plan_table.setRowCount(0)
            self.collection_state_label.setText(
                "Wheel selection/order changed"
            )
        self._update_controls()

    def _ordered_selected_wheels(self) -> list[int]:
        self._refresh_wheel_order_badges()
        if not self._wheel_collection_order:
            raise ValueError("Select at least one wheel to collect")
        return list(self._wheel_collection_order)

    def _create_requests(self) -> list[RunRequest]:
        if not self._position_valid:
            raise ValueError(
                "Synchronise the current physical code before generating a plan"
            )

        session_id = self.session_id_edit.text().strip()
        if not session_id:
            raise ValueError("Session ID cannot be empty")

        selected_wheels = self._ordered_selected_wheels()
        correct_digits = [-1, -1, -1, -1]
        current_digits = self._current_code_values()
        dataset_dir = self._resolved_dataset_path()
        mode = str(self.collection_mode_combo.currentData())
        common = dict(
            session_id=session_id,
            selected_wheels=selected_wheels,
            direction=self.collection_direction.currentText(),
            correct_digits=correct_digits,
            current_digits=current_digits,
            lock_id=self.lock_id_edit.text().strip(),
            scenario=self.scenario_edit.text().strip(),
            tape_version=self.tape_edit.text().strip(),
            microphone_position=self.microphone_edit.text().strip(),
            focusrite_gain=self.gain_edit.text().strip(),
            spring_setting=self.spring_edit.text().strip(),
            dataset_dir=dataset_dir,
        )

        return self.backend.build_digit_scan_requests(
            **common,
            repetitions=self.repetitions_spin.value(),
            tension_state=str(self.tension_combo.currentData()),
            digit_steps=self.digit_steps_spin.value(),
        )

    def _validate_plan_start(self, requests: list[RunRequest]) -> bool:
        if not self._position_valid:
            self._show_error("Synchronise the current physical code first.")
            return False
        if not requests:
            self._show_error("Generate a plan first.")
            return False

        expected = requests[0].current_code_before
        actual = self._current_code_text()
        if expected != actual:
            self._show_error(
                f"Plan expects physical code {expected}, but the app is synchronised "
                f"to {actual}. Regenerate the plan."
            )
            return False
        return True

    def _start_collection(self) -> None:
        if not self.backend.connected:
            self._show_error("Connect the ESP32 and Focusrite first.")
            return
        if self._collection_running or self._task_running:
            self._show_busy_notice()
            return

        try:
            fresh_requests = self._create_requests()
        except Exception as exc:
            self._show_error(str(exc))
            return

        if self._requests != fresh_requests:
            self._requests = fresh_requests
            self._plan_start_code = self._current_code_text()
            self._populate_plan_table()

        requests = list(self._requests)
        if not self._validate_plan_start(requests):
            return

        mode = str(self.collection_mode_combo.currentData())
        contact_note = (
            "Drive head stays down between same-wheel digits."
            if self.keep_contact_check.isChecked()
            else "Drive head raises after every digit."
        )
        mode_note = (
            "The selected wheels will each complete full ten-transition cycles "
            f"using {self.digit_steps_spin.value()} motor steps per digit and return to the starting code. "
            f"{contact_note}"
        )

        confirmation = _themed_question(
            self,
            "Start batch collection",
            (
                f"Run {len(requests)} sample(s) from code "
                f"{requests[0].current_code_before}?\n\n"
                f"{mode_note}\n\n"
                "Keep hands clear and ensure the 12 V supply is on."
            ),
        )
        if confirmation is not QMessageBox.StandardButton.Yes:
            return

        self._launch_collection(
            requests=requests,
            row_map=list(range(len(requests))),
        )

    def _start_selected_collection(self) -> None:
        if not self.backend.connected:
            self._show_error("Connect the ESP32 and Focusrite first.")
            return
        if self._collection_running or self._task_running:
            self._show_busy_notice()
            return
        if not self._requests:
            self._show_error("Generate a plan first.")
            return

        row = self.plan_table.currentRow()
        if row < 0 or row >= len(self._requests):
            self._show_error("Select one plan row first.")
            return

        request = self._requests[row]
        if not self._validate_plan_start([request]):
            return

        if request.action_type == ActionType.PROBE.value:
            action_text = (
                f"micro-probe wheel {request.wheel_index} at digit "
                f"{request.start_digit}"
            )
        elif request.action_type == ActionType.WIDE_PROBE.value:
            action_text = (
                f"wide-probe wheel {request.wheel_index} at digit "
                f"{request.start_digit}, ±{request.probe_amplitude} steps, "
                f"{request.probe_cycles} cycles"
            )
        elif request.action_type == ActionType.BINDING_SWEEP.value:
            action_text = (
                f"sweep wheel {request.wheel_index} one full CCW revolution "
                f"and return to digit {request.start_digit}"
            )
        elif request.action_type == ActionType.BINDING_REFERENCE_SWEEP.value:
            action_text = (
                f"reference-sweep wheel {request.wheel_index}: "
                f"{request.start_digit} → {request.end_digit}, avoiding the true gate"
            )
        else:
            action_text = (
                f"move wheel {request.wheel_index}: "
                f"{request.start_digit} → {request.end_digit}"
            )
        confirmation = _themed_question(
            self,
            "Collect selected sample",
            (
                f"Collect {request.run_id}: {action_text}?\n\n"
                f"Physical code must currently be {request.current_code_before}."
            ),
        )
        if confirmation is not QMessageBox.StandardButton.Yes:
            return

        self._launch_collection(
            requests=[request],
            row_map=[row],
        )

    def _launch_collection(
        self,
        *,
        requests: list[RunRequest],
        row_map: list[int],
        force_stop_on_rejected: bool | None = None,
        pause_between_runs_s_override: float | None = None,
        keep_contact_override: bool | None = None,
        stop_after_result_override: Callable[[int, RunResult], str | None] | None = None,
    ) -> None:
        self._collection_running = True
        self._active_row_map = row_map
        self._valid_count = 0
        self._rejected_count = 0
        self._failed_count = 0
        self._active_collection_results = []
        self._update_counter()
        self._update_controls()

        dataset_dir = Path(self.dataset_edit.text().strip()).expanduser()
        worker = CollectionWorker(
            self.backend,
            requests=requests,
            dataset_dir=dataset_dir,
            pre_roll_s=self.pre_roll_spin.value(),
            post_roll_s=self.post_roll_spin.value(),
            pause_between_runs_s=(
                self.pause_spin.value()
                if pause_between_runs_s_override is None
                else pause_between_runs_s_override
            ),
            stop_on_rejected=(
                self.stop_rejected_check.isChecked()
                if force_stop_on_rejected is None
                else force_stop_on_rejected
            ),
            keep_contact_between_digits=(
                self.keep_contact_check.isChecked()
                if keep_contact_override is None
                else bool(keep_contact_override)
            ),
            stop_after_result=stop_after_result_override,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        worker.log.connect(self.append_log)
        worker.state_changed.connect(self._collection_state_changed)
        worker.progress.connect(self._collection_progress_changed)
        worker.result_ready.connect(self._collection_result_ready)
        worker.completed.connect(self._collection_completed)
        worker.error.connect(self._task_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._collection_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.started.connect(worker.run)

        self._collection_thread = thread
        self._collection_worker = worker
        self._threads.append(thread)
        self._workers.append(worker)
        thread.start()

    @Slot(str)
    def _collection_state_changed(self, state: str) -> None:
        self.state_badge.setText(f"State  {state}")
        self.collection_state_label.setText(state)

    @Slot(int, int, object)
    def _collection_progress_changed(
        self,
        index: int,
        total: int,
        request: object,
    ) -> None:
        self.collection_progress.setRange(0, max(1, total))
        self.collection_progress.setValue(index - 1)
        if isinstance(request, RunRequest):
            if request.action_type == ActionType.PROBE.value:
                action_text = (
                    f"probe wheel {request.wheel_index} at {request.start_digit}"
                )
            elif request.action_type == ActionType.WIDE_PROBE.value:
                action_text = (
                    f"wide probe wheel {request.wheel_index} at "
                    f"{request.start_digit}, ±{request.probe_amplitude}, "
                    f"{request.probe_cycles} cycles"
                )
            elif request.action_type == ActionType.BINDING_SWEEP.value:
                action_text = (
                    f"binding sweep wheel {request.wheel_index}, "
                    f"full CCW revolution from {request.start_digit}"
                )
            elif request.action_type == ActionType.BINDING_REFERENCE_SWEEP.value:
                action_text = (
                    f"binding reference wheel {request.wheel_index}, "
                    f"{request.start_digit} → {request.end_digit}"
                )
            else:
                action_text = (
                    f"wheel {request.wheel_index}, "
                    f"{request.start_digit} → {request.end_digit}"
                )
            self.collection_state_label.setText(
                f"Run {index}/{total}: {action_text}"
            )
            local_row = index - 1
            row = (
                self._active_row_map[local_row]
                if 0 <= local_row < len(self._active_row_map)
                else local_row
            )
            if 0 <= row < self.plan_table.rowCount():
                self.plan_table.selectRow(row)
                item = self.plan_table.item(row, 8)
                if item is not None:
                    item.setText("Running")

    @Slot(int, object)
    def _collection_result_ready(self, row: int, result: object) -> None:
        if not isinstance(result, RunResult):
            return

        # Same result path that drives the live VALID / REJECTED display.
        if not any(
            item.request.run_id == result.request.run_id
            for item in self._active_collection_results
        ):
            self._active_collection_results.append(result)

        if result.output_dir is not None:
            self._latest_review_dir = Path(result.output_dir)

        if result.status is RunStatus.VALID:
            self._valid_count += 1
        elif result.status is RunStatus.REJECTED:
            self._rejected_count += 1
        else:
            self._failed_count += 1

        table_row = (
            self._active_row_map[row]
            if 0 <= row < len(self._active_row_map)
            else row
        )

        if 0 <= table_row < self.plan_table.rowCount():
            item = self.plan_table.item(table_row, 8)
            if item is not None:
                item.setText(result.status.value)
                if result.status is RunStatus.VALID:
                    item.setForeground(QColor("#66d9a8"))
                elif result.status is RunStatus.REJECTED:
                    item.setForeground(QColor("#f2c66d"))
                else:
                    item.setForeground(QColor("#ff7f91"))
                if result.error_message:
                    item.setToolTip(result.error_message)

        if self._csv_batch_active and self._csv_batch_plan_path is not None:
            try:
                decision = self._csv_batch_decisions[self._csv_batch_decision_index]
                self._csv_batch_progress.record_result(
                    dataset_dir=self._resolved_dataset_path(),
                    session_id=self.session_id_edit.text().strip(),
                    decision=decision,
                    plan_file=self._csv_batch_plan_path,
                    result=result,
                )
            except Exception as exc:
                self.append_log(f"Decision progress write failed: {exc}")
                self._csv_batch_pause_requested = True
                self.backend.request_graceful_batch_stop()

        if result.status in {RunStatus.VALID, RunStatus.REJECTED}:
            self._apply_current_code(
                result.request.current_code_after,
                valid=True,
            )
        else:
            self._set_position_valid(False)
            self.append_log(
                "Physical code is no longer trusted because a run did not "
                "complete normally"
            )

        self.collection_progress.setValue(row + 1)
        self._update_counter()

    @Slot(object)
    def _collection_completed(self, results: object) -> None:
        result_list = results if isinstance(results, list) else []
        count = len(result_list)
        failed = any(
            isinstance(item, RunResult)
            and item.status in {RunStatus.FAILED, RunStatus.ABORTED}
            for item in result_list
        )
        if failed:
            self._set_position_valid(False)
            self.collection_state_label.setText(
                "Batch completed with failure; re-synchronise code"
            )
        else:
            self.collection_state_label.setText(
                f"Batch completed at code {self._current_code_text()}"
            )
        self.append_log(f"Batch collection finished with {count} result(s)")
        if self._auto_recognition_active:
            self._auto_pending_results = [
                item for item in result_list if isinstance(item, RunResult)
            ]
        if self._csv_batch_active:
            self._csv_batch_pending_advance = True
        if hasattr(self, "signal_review_panel"):
            self.signal_review_panel.refresh_runs(preserve_current=True)
        self.state_badge.setText("State  IDLE")
        self.state_badge.setStyleSheet("")
        self._update_controls()


    @Slot()
    def _task_thread_finished(self) -> None:
        thread = self.sender()
        if thread is not self._active_task_thread:
            return
        worker = self._active_task_worker

        self._task_running = False
        self._task_elapsed_timer.stop()
        if thread is not None and thread in self._threads:
            self._threads.remove(thread)
        if worker is not None and worker in self._workers:
            self._workers.remove(worker)
        self._active_task_thread = None
        self._active_task_worker = None

        if self._active_task_button is not None:
            self._active_task_button.setText(
                self._active_task_button_text
            )
        self._active_task_button = None
        self._active_task_button_text = ""

        if self._task_cancelled:
            self.statusBar().showMessage("Operation stopped", 3500)
            self._set_operation_state(
                "warning",
                "Operation stopped",
                "The active command was cancelled by the emergency stop.",
            )
        elif self._task_failed:
            self.statusBar().showMessage("Operation failed", 5000)
        else:
            self.statusBar().showMessage("Ready")
            self._set_operation_state(
                "success",
                "Command completed",
                f"{self._active_task_name} finished successfully.",
            )

        self._active_task_name = ""
        self._active_task_offline = False
        self._task_started_at = 0.0
        if self._task_cancelled:
            self._emergency_requested = False
        self._task_cooldown = True
        self._update_controls()
        QTimer.singleShot(300, self._release_task_cooldown)
        if not self._task_failed and not self._task_cancelled:
            sequence = self._task_sequence
            QTimer.singleShot(
                1400,
                lambda value=sequence: self._reset_operation_state_if_idle(
                    value
                ),
            )

    @Slot()
    def _emergency_thread_finished(self) -> None:
        thread = self.sender()
        if thread is not self._emergency_thread:
            return
        worker = self._emergency_worker

        self._emergency_running = False
        if thread in self._threads:
            self._threads.remove(thread)
        if worker is not None and worker in self._workers:
            self._workers.remove(worker)
        self._emergency_thread = None
        self._emergency_worker = None

        if self._emergency_failed:
            self.statusBar().showMessage(
                "Emergency stop failed",
                5000,
            )
        else:
            self.statusBar().showMessage("Emergency stop sent", 3500)

        if not self._task_running and not self._emergency_failed:
            self._set_operation_state(
                "warning",
                "Emergency stop sent",
                "Hardware state must be checked before the next movement.",
            )
        self._update_controls()

    @Slot()
    def _collection_thread_finished(self) -> None:
        thread = self.sender()
        if thread is not self._collection_thread:
            return
        worker = self._collection_worker

        self._collection_running = False
        self._active_row_map = []
        if thread in self._threads:
            self._threads.remove(thread)
        if worker is not None and worker in self._workers:
            self._workers.remove(worker)
        self._collection_thread = None
        self._collection_worker = None
        pending_csv_advance = self._csv_batch_pending_advance
        self._csv_batch_pending_advance = False
        pending_auto_review = bool(
            self._auto_recognition_active and self._auto_pending_results is not None
        )
        self._update_controls()
        if pending_csv_advance and self._csv_batch_active:
            QTimer.singleShot(0, self._advance_csv_batch)
        elif pending_auto_review:
            if self._auto_collection_kind == "W3_UNLOCK_SWEEP":
                QTimer.singleShot(0, self._auto_process_w3_sweep_results)
            else:
                QTimer.singleShot(0, self._auto_review_current_circle)


























