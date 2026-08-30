from __future__ import annotations

import json
import random
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from models import RunResult, RunStatus


AUTO_COMPONENTS: tuple[tuple[str, str], ...] = (
    ("CCW", "A"),
    ("CCW", "B"),
    ("CW", "A"),
    ("CW", "B"),
)
AUTO_WHEELS: tuple[int, ...] = (1, 2, 4)

# Retry policy v1.  This is intentionally a fixed, inspectable pilot rule rather
# than a learned/calibrated threshold.  A fresh randomized recognition pass is
# recommended only after the Top-1 prefix has completed a full W3 sweep with no
# physical unlock and at least one wheel margin falls below this value.
AUTO_RETRY_MARGIN_THRESHOLD = 0.20
AUTO_MAX_RECOGNITION_PASSES = 2


class AutoRecognitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrefixHypothesis:
    """One W1/W2/W4 prefix hypothesis for evidence-ranked fallback search.

    The score is the sum of the frozen MAIN-v8 fused candidate scores.  No
    wheel-specific priority or hand-written "W2 is harder" rule is used.
    """

    rank: int
    w1: int
    w2: int
    w4: int
    joint_score: float
    evidence_loss: float
    wheel_ranks: tuple[int, int, int]
    tied_with_previous: bool = False

    @property
    def prefix_text(self) -> str:
        return f"{self.w1}{self.w2}?{self.w4}"

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "prefix": self.prefix_text,
            "w1": self.w1,
            "w2": self.w2,
            "w4": self.w4,
            "joint_score": self.joint_score,
            "evidence_loss": self.evidence_loss,
            "wheel_ranks": list(self.wheel_ranks),
            "tied_with_previous": self.tied_with_previous,
        }


def build_top2_prefix_hypotheses(
    predictions: Mapping[int, Mapping[str, object]],
    *,
    tie_tolerance: float = 1e-12,
) -> list[PrefixHypothesis]:
    """Build the ranked Top-2 W1×W2×W4 hypothesis cube.

    Each wheel contributes exactly its two MAIN-v8 Top-2 candidates.  The
    combined evidence is additive because the three frozen wheel scorers return
    scan-normalised candidate scores.  Equal joint scores remain equal; a stable
    lexical order is used only so the hardware has a reproducible test order.
    The UI/log explicitly marks such ties so that deterministic ordering is not
    misrepresented as extra evidence.
    """

    per_wheel: dict[int, list[tuple[int, float, int]]] = {}
    for wheel in AUTO_WHEELS:
        item = predictions.get(wheel)
        if not item:
            raise AutoRecognitionError(f"Missing MAIN v8 prediction for W{wheel}")

        raw_top2 = item.get("top2")
        if not isinstance(raw_top2, Sequence) or isinstance(raw_top2, (str, bytes)):
            raise AutoRecognitionError(f"W{wheel} Top-2 candidates are unavailable")
        top2: list[int] = []
        for value in raw_top2:
            digit = int(value)
            if digit not in top2:
                top2.append(digit)
            if len(top2) == 2:
                break
        if len(top2) != 2:
            raise AutoRecognitionError(f"W{wheel} does not have two distinct Top-2 candidates")

        raw_scores = item.get("fused_scores")
        if not isinstance(raw_scores, Sequence) or isinstance(raw_scores, (str, bytes)):
            raise AutoRecognitionError(f"W{wheel} fused candidate scores are unavailable")
        score_map: dict[int, float] = {}
        for pair in raw_scores:
            try:
                digit, score = pair  # type: ignore[misc]
                score_map[int(digit)] = float(score)
            except Exception as exc:
                raise AutoRecognitionError(
                    f"W{wheel} contains an invalid fused-score entry: {pair!r}"
                ) from exc
        missing = [digit for digit in top2 if digit not in score_map]
        if missing:
            raise AutoRecognitionError(
                f"W{wheel} is missing fused evidence for candidate(s) {missing}"
            )
        per_wheel[wheel] = [
            (digit, score_map[digit], rank)
            for rank, digit in enumerate(top2, start=1)
        ]

    raw: list[dict[str, object]] = []
    for c1, c2, c4 in product(per_wheel[1], per_wheel[2], per_wheel[4]):
        d1, s1, r1 = c1
        d2, s2, r2 = c2
        d4, s4, r4 = c4
        raw.append(
            {
                "w1": d1,
                "w2": d2,
                "w4": d4,
                "joint_score": float(s1 + s2 + s4),
                "wheel_ranks": (r1, r2, r4),
            }
        )

    # Evidence score is the only substantive ordering key.  Prefix digits are
    # used strictly as a deterministic tie order, never as a confidence prior.
    raw.sort(
        key=lambda row: (
            -float(row["joint_score"]),
            int(row["w1"]),
            int(row["w2"]),
            int(row["w4"]),
        )
    )
    top_score = float(raw[0]["joint_score"])
    output: list[PrefixHypothesis] = []
    previous_score: float | None = None
    for index, row in enumerate(raw, start=1):
        score = float(row["joint_score"])
        tied = previous_score is not None and abs(score - previous_score) <= tie_tolerance
        output.append(
            PrefixHypothesis(
                rank=index,
                w1=int(row["w1"]),
                w2=int(row["w2"]),
                w4=int(row["w4"]),
                joint_score=score,
                evidence_loss=float(top_score - score),
                wheel_ranks=tuple(int(v) for v in row["wheel_ranks"]),
                tied_with_previous=tied,
            )
        )
        previous_score = score
    return output


def validate_session_id(value: str) -> str:
    session_id = str(value or "").strip()
    if not session_id:
        raise AutoRecognitionError("Automatic-recognition Session ID is empty")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", session_id):
        raise AutoRecognitionError(
            "Automatic-recognition Session ID may contain only letters, numbers, '_', '-' and '.'"
        )
    return session_id


def profile_id_for(session_id: str, wheel: int, pass_number: int = 1) -> str:
    pass_number = int(pass_number)
    if pass_number < 1:
        raise AutoRecognitionError("pass_number must be at least 1")
    return f"AUTO_{session_id}_P{pass_number}_W{int(wheel)}"


def decision_key_for(
    session_id: str,
    wheel: int,
    direction: str,
    repeat_id: str,
    pass_number: int = 1,
) -> str:
    pass_number = int(pass_number)
    if pass_number < 1:
        raise AutoRecognitionError("pass_number must be at least 1")
    return (
        f"AUTO_{session_id}_P{pass_number}_W{int(wheel)}_"
        f"{str(direction).upper()}_{str(repeat_id).upper()}"
    )


def recognition_margin_summary(
    predictions: Mapping[int, Mapping[str, object]],
    *,
    threshold: float = AUTO_RETRY_MARGIN_THRESHOLD,
) -> dict[str, object]:
    """Summarise the current pass margins without inventing missing confidence.

    A missing/non-numeric margin is treated as low-confidence so the retry path
    fails conservatively.  This helper is deliberately independent of truth.
    """
    margins: dict[str, float | None] = {}
    numeric: list[float] = []
    missing = False
    for wheel in AUTO_WHEELS:
        raw = predictions.get(wheel, {}).get("margin")
        if raw is None:
            margins[f"W{wheel}"] = None
            missing = True
            continue
        try:
            value = float(raw)
        except Exception:
            margins[f"W{wheel}"] = None
            missing = True
            continue
        margins[f"W{wheel}"] = value
        numeric.append(value)

    min_margin = min(numeric) if numeric else None
    low = bool(missing or min_margin is None or min_margin < float(threshold))
    return {
        "margins": margins,
        "min_margin": min_margin,
        "threshold": float(threshold),
        "low_confidence": low,
    }


def randomized_restart_code(current_digits: Sequence[int]) -> tuple[int, int, int, int]:
    """Generate a visibly different four-wheel start state for pass 2.

    Every wheel is displaced by 2-8 digits from its current value.  This avoids
    a nominal "retry" that repeats almost the same physical starting state,
    while keeping the procedure independent of the unknown correct combination.
    """
    if len(current_digits) != 4:
        raise AutoRecognitionError("current_digits must contain four digits")
    current = tuple(int(v) for v in current_digits)
    if any(v not in range(10) for v in current):
        raise AutoRecognitionError("current_digits must contain only digits 0-9")
    rng = random.SystemRandom()
    offsets = (2, 3, 4, 5, 6, 7, 8)
    return tuple((digit + rng.choice(offsets)) % 10 for digit in current)  # type: ignore[return-value]


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def delete_result_runs(dataset_root: Path, results: Iterable[RunResult]) -> int:
    """Delete only the raw/rejected folders produced by the supplied results.

    The safety checks deliberately refuse to delete outside dataset_root/raw or
    dataset_root/rejected.
    """
    root = Path(dataset_root).resolve()
    allowed_roots = [(root / "raw").resolve(), (root / "rejected").resolve()]
    deleted = 0
    for result in results:
        output = result.output_dir
        if output is None:
            continue
        path = Path(output).resolve()
        allowed = False
        for allowed_root in allowed_roots:
            try:
                path.relative_to(allowed_root)
                allowed = True
                break
            except ValueError:
                pass
        if not allowed:
            raise AutoRecognitionError(
                f"Refusing to delete a run outside dataset/raw or dataset/rejected: {path}"
            )
        if path.exists():
            shutil.rmtree(path)
            deleted += 1
    return deleted


def circle_quality_summary(results: Sequence[RunResult]) -> dict[str, object]:
    valid = [item for item in results if item.status is RunStatus.VALID]
    rejected = [item for item in results if item.status is RunStatus.REJECTED]
    failed = [
        item
        for item in results
        if item.status in {RunStatus.FAILED, RunStatus.ABORTED}
    ]

    target_peaks: list[float] = []
    target_clip: list[float] = []
    ref_peaks: list[float] = []
    ref_clip: list[float] = []
    for item in results:
        quality = item.quality
        if quality is None:
            continue
        target_peaks.append(float(getattr(quality, "target_peak", 0.0) or 0.0))
        target_clip.append(float(getattr(quality, "target_clipped_ratio", 0.0) or 0.0))
        ref_peaks.append(float(getattr(quality, "reference_peak", 0.0) or 0.0))
        ref_clip.append(float(getattr(quality, "reference_clipped_ratio", 0.0) or 0.0))

    return {
        "count": len(results),
        "valid": len(valid),
        "rejected": len(rejected),
        "failed": len(failed),
        "all_valid": len(results) == 10 and len(valid) == 10,
        "target_peak_max": max(target_peaks, default=0.0),
        "target_clip_max": max(target_clip, default=0.0),
        "reference_peak_max": max(ref_peaks, default=0.0),
        "reference_clip_max": max(ref_clip, default=0.0),
    }


class AutoRecognitionStore:
    def __init__(self, dataset_root: Path, session_id: str) -> None:
        self.dataset_root = Path(dataset_root).resolve()
        self.session_id = validate_session_id(session_id)

    @property
    def decision_session_dir(self) -> Path:
        return self.dataset_root / "decision_batches" / self.session_id

    @property
    def result_dir(self) -> Path:
        return self.dataset_root / "recognition_results" / self.session_id

    @property
    def state_path(self) -> Path:
        return self.result_dir / "AUTO_recognition_state.json"

    @property
    def flow_log_path(self) -> Path:
        return self.result_dir / "AUTO_flow_log.jsonl"

    @property
    def run_summary_path(self) -> Path:
        return self.result_dir / "AUTO_run_summary.json"

    @property
    def console_log_path(self) -> Path:
        return self.result_dir / "AUTO_console_log.txt"

    @property
    def flow_report_path(self) -> Path:
        return self.result_dir / "AUTO_flow_report.txt"

    def append_flow_event(self, event: str, payload: Mapping[str, object] | None = None) -> Path:
        self.result_dir.mkdir(parents=True, exist_ok=True)
        row: dict[str, object] = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": str(event),
        }
        if payload:
            row.update(dict(payload))
        with self.flow_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        return self.flow_log_path

    def append_console_line(self, line: str) -> Path:
        self.result_dir.mkdir(parents=True, exist_ok=True)
        with self.console_log_path.open("a", encoding="utf-8") as handle:
            handle.write(str(line).rstrip("\n") + "\n")
        return self.console_log_path

    def write_run_summary(self, payload: Mapping[str, object], report_text: str) -> tuple[Path, Path]:
        self.result_dir.mkdir(parents=True, exist_ok=True)
        data = dict(payload)
        data["session_id"] = self.session_id
        data["written_at_utc"] = datetime.now(timezone.utc).isoformat()
        tmp = self.run_summary_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.run_summary_path)
        self.flow_report_path.write_text(str(report_text).rstrip() + "\n", encoding="utf-8")
        return self.run_summary_path, self.flow_report_path

    def ensure_new_session(self) -> None:
        collisions = [
            self.dataset_root / "raw" / self.session_id,
            self.dataset_root / "rejected" / self.session_id,
            self.dataset_root / "decision_batches" / self.session_id,
            self.dataset_root / "recognition_results" / self.session_id,
        ]
        existing = [path for path in collisions if path.exists()]
        if existing:
            raise AutoRecognitionError(
                "This Session ID already has data. Use a new Session ID for a clean automatic-recognition run:\n"
                + "\n".join(str(path) for path in existing)
            )

    def write_component(
        self,
        *,
        wheel: int,
        direction: str,
        repeat_id: str,
        start_digits: Sequence[int],
        results: Sequence[RunResult],
        pass_number: int = 1,
    ) -> Path:
        wheel = int(wheel)
        direction = str(direction).upper()
        repeat_id = str(repeat_id).upper()
        if wheel not in AUTO_WHEELS:
            raise AutoRecognitionError(f"MAIN v8 automatic acquisition does not support W{wheel}")
        if direction not in {"CW", "CCW"}:
            raise AutoRecognitionError("direction must be CW or CCW")
        if repeat_id not in {"A", "B"}:
            raise AutoRecognitionError("repeat_id must be A or B")
        if len(start_digits) != 4 or any(int(v) not in range(10) for v in start_digits):
            raise AutoRecognitionError("start_digits must contain four digits 0-9")
        if len(results) != 10:
            raise AutoRecognitionError(
                f"A MAIN v8 component requires 10 WAVs; received {len(results)}"
            )
        if any(item.status is not RunStatus.VALID for item in results):
            raise AutoRecognitionError("A component can be accepted only when all 10 WAVs are VALID")

        pass_number = int(pass_number)
        if pass_number < 1:
            raise AutoRecognitionError("pass_number must be at least 1")
        profile_id = profile_id_for(self.session_id, wheel, pass_number)
        decision_key = decision_key_for(
            self.session_id, wheel, direction, repeat_id, pass_number
        )
        output_dir = self.decision_session_dir / decision_key
        if output_dir.exists():
            raise AutoRecognitionError(
                f"Accepted component already exists: {output_dir}. Use Re-record before accepting, or use a new Session ID."
            )
        output_dir.mkdir(parents=True, exist_ok=False)

        candidates: list[dict[str, object]] = []
        for index, result in enumerate(results, start=1):
            request = result.request
            if request.wheel_index != wheel:
                raise AutoRecognitionError(
                    f"Component W{wheel} contains a W{request.wheel_index} run"
                )
            if request.direction != direction:
                raise AutoRecognitionError(
                    f"Component {direction} contains a {request.direction} run"
                )
            if request.decision_move_index not in {0, index}:
                raise AutoRecognitionError(
                    f"Unexpected movement index {request.decision_move_index} in component"
                )
            if result.output_dir is None:
                raise AutoRecognitionError(f"Run {request.run_id} has no output directory")
            candidates.append(
                {
                    "candidate_index": index,
                    "run_id": request.run_id,
                    "status": result.status.value,
                    "output_dir": _safe_relative(Path(result.output_dir), self.dataset_root),
                    "direction": direction,
                    "wheel": wheel,
                    "scan_position": 1,
                    "move_index": index,
                    "before_code": request.current_code_before,
                    "after_code": request.current_code_after,
                    "from_digit": request.start_digit,
                    "to_digit": request.end_digit,
                    "is_true_gate_movement": 0,
                    "is_target": 0,
                    "binding_wheel": wheel,
                    "target_digit": -1,
                    "task_type": "digit_scan",
                    "prefix_stage": 0,
                    "prefix_valid": -1,
                    "expected_binding_wheel": 0,
                    "probe_wheel": 0,
                    "probe_binding_label": 1,
                    "recorded_at_utc": result.finished_at_utc
                    or datetime.now(timezone.utc).isoformat(),
                }
            )

        digits = sorted(int(item["to_digit"]) for item in candidates)
        if digits != list(range(10)):
            shutil.rmtree(output_dir, ignore_errors=True)
            raise AutoRecognitionError(
                f"Accepted component must visit each physical digit exactly once; got {digits}"
            )

        start_tuple = tuple(int(v) for v in start_digits)
        payload = {
            "version": 4,
            "task_type": "digit_scan",
            "profile_id": profile_id,
            "group_id": profile_id,
            "decision_id": f"AUTO_{self.session_id}_P{pass_number}_W{wheel}_{direction}",
            "repeat_id": repeat_id,
            "decision_key": decision_key,
            "session_id": self.session_id,
            "recognition_pass": pass_number,
            "start_digits": list(start_tuple),
            "start_code": "".join(str(v) for v in start_tuple),
            "active_wheels": [wheel],
            "active_mask": [1 if item == wheel else 0 for item in range(1, 5)],
            "scan_order": [wheel],
            "direction": direction,
            "force_reseat_before": repeat_id == "A",
            "movement_protocol": "supervised unknown-lock MAIN-v8 10-WAV Digit Scan",
            "binding_wheel": wheel,
            "binding_confidence": 0,
            "prefix_stage": 0,
            "prefix_valid": -1,
            "expected_binding_wheel": 0,
            "preserve_inactive_start": True,
            "true_digits": [-1, -1, -1, -1],
            "target_digit": -1,
            "planned_runs": 10,
            "plan_file": "AUTO_RECOGNITION_RUNTIME",
            "plan_source_row": 0,
            "notes": (
                f"Unknown-lock supervised automatic recognition pass {pass_number}. Correct combination was not supplied to acquisition or inference. "
                "The operator reviewed this full 10-WAV circle and selected Continue."
            ),
            "candidates": candidates,
            "finalised_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        try:
            (output_dir / "decision.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise
        return output_dir

    def save_state(self, payload: dict[str, object]) -> Path:
        self.result_dir.mkdir(parents=True, exist_ok=True)
        data = dict(payload)
        data["session_id"] = self.session_id
        data["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)
        return self.state_path
