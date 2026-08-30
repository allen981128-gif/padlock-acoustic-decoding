from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from config import (
    BINDING_REFERENCE_SWEEP_SECTOR_STEPS,
    BINDING_REFERENCE_SWEEP_STEPS,
    WIDE_PROBE_MAX_AMPLITUDE_STEPS,
    WIDE_PROBE_MAX_CYCLES,
    WIDE_PROBE_MIN_AMPLITUDE_STEPS,
    WIDE_PROBE_MIN_CYCLES,
    WHEEL_STEPS_PER_DIGIT,
    WHEEL_STEPS_PER_REV,
)


class ControllerState(str, Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    HANDSHAKE = "HANDSHAKE"
    PREPARING = "PREPARING"
    WAITING_FOR_READY = "WAITING_FOR_READY"
    PRE_ROLL = "PRE_ROLL"
    WAITING_FOR_SCAN = "WAITING_FOR_SCAN"
    SCANNING = "SCANNING"
    PROBING = "PROBING"
    POST_ROLL = "POST_ROLL"
    SAVING = "SAVING"
    COMPLETED = "COMPLETED"
    ABORTING = "ABORTING"
    FAILED = "FAILED"


class MessageType(str, Enum):
    SYSTEM = "SYSTEM"
    CONFIG = "CONFIG"
    ACK = "ACK"
    STATE = "STATE"
    READY_TO_RECORD = "READY_TO_RECORD"
    EVENT = "EVENT"
    DONE = "DONE"
    ERROR = "ERROR"
    STATUS = "STATUS"
    LIMIT = "LIMIT"
    COMPLETED = "COMPLETED"
    DEBUG = "DEBUG"
    UNKNOWN = "UNKNOWN"


class EspEventType(str, Enum):
    SCAN_START = "SCAN_START"
    DIGIT_BOUNDARY = "DIGIT_BOUNDARY"
    SCAN_END = "SCAN_END"
    PROBE_START = "PROBE_START"
    PROBE_SEGMENT = "PROBE_SEGMENT"
    PROBE_END = "PROBE_END"
    WIDE_PROBE_START = "WIDE_PROBE_START"
    WIDE_PROBE_SEGMENT = "WIDE_PROBE_SEGMENT"
    WIDE_PROBE_END = "WIDE_PROBE_END"


class RunStatus(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class ActionType(str, Enum):
    DIGIT_MOVE = "DIGIT_MOVE"
    PROBE = "PROBE"
    WIDE_PROBE = "WIDE_PROBE"
    BINDING_SWEEP = "BINDING_SWEEP"
    BINDING_REFERENCE_SWEEP = "BINDING_REFERENCE_SWEEP"


@dataclass(frozen=True)
class RunRequest:
    run_id: str
    session_id: str
    wheel_index: int
    direction: str
    correct_digit: int
    start_digit: int

    scenario: str
    wheel_1_digit: int
    wheel_2_digit: int
    wheel_3_digit: int
    wheel_4_digit: int

    lock_id: str
    tape_version: str
    microphone_position: str
    focusrite_gain: str
    spring_setting: str

    repetition: int = 1
    notes: str = ""

    action_type: str = ActionType.DIGIT_MOVE.value
    collection_mode: str = "single_digit_scan"
    tension_state: str = "UNSPECIFIED"
    probe_amplitude: int = 20
    probe_cycles: int = 1
    sweep_steps: int = WHEEL_STEPS_PER_REV
    sector_steps: int = WHEEL_STEPS_PER_DIGIT
    digit_steps: int = WHEEL_STEPS_PER_DIGIT
    position_valid: bool = True

    # Optional metadata used by Decision Batch collection.
    profile_id: str = ""
    group_id: str = ""
    decision_id: str = ""
    decision_repeat_id: str = ""
    decision_move_index: int = 0
    decision_scan_position: int = 0
    decision_candidate_index: int = 0
    decision_active_w1: int = 0
    decision_active_w2: int = 0
    decision_active_w3: int = 0
    decision_active_w4: int = 0
    decision_binding_wheel: int = 0
    decision_target_digit: int = -1
    decision_true_w1: int = -1
    decision_true_w2: int = -1
    decision_true_w3: int = -1
    decision_true_w4: int = -1
    decision_is_true_gate_movement: int = 0
    decision_is_target: int = 0
    decision_binding_confidence: int = 0

    # Optional metadata used by the plan-driven Binding Scan workflow.
    batch_task_type: str = "digit_scan"
    binding_prefix_stage: int = 0
    binding_prefix_valid: int = -1
    binding_expected_wheel: int = 0
    binding_probe_wheel: int = 0

    batch_plan_id: str = ""
    batch_plan_source_row: int = 0

    def __post_init__(self) -> None:
        direction = self.direction.upper()
        object.__setattr__(self, "direction", direction)

        action = self.action_type.upper().strip()
        aliases = {
            "DIGIT": ActionType.DIGIT_MOVE.value,
            "SCAN": ActionType.DIGIT_MOVE.value,
            "DIGIT_TRANSITION": ActionType.DIGIT_MOVE.value,
            "MICRO_PROBE": ActionType.PROBE.value,
            "WIDE_LOCAL_PROBE": ActionType.WIDE_PROBE.value,
            "WIDE_MICRO_PROBE": ActionType.WIDE_PROBE.value,
            "LOCAL_SWEEP": ActionType.WIDE_PROBE.value,
            "SWEEP": ActionType.BINDING_SWEEP.value,
            "FULL_REVOLUTION": ActionType.BINDING_SWEEP.value,
            "BINDING": ActionType.BINDING_SWEEP.value,
            "REFERENCE_SWEEP": ActionType.BINDING_REFERENCE_SWEEP.value,
            "BINDING_REFERENCE": ActionType.BINDING_REFERENCE_SWEEP.value,
            "REF_SWEEP": ActionType.BINDING_REFERENCE_SWEEP.value,
        }
        action = aliases.get(action, action)
        object.__setattr__(self, "action_type", action)

        tension = self.tension_state.upper().strip()
        if tension == "UNKNOWN":
            tension = "UNSPECIFIED"
        object.__setattr__(self, "tension_state", tension)

        if not self.run_id:
            raise ValueError("run_id cannot be empty")

        if not self.session_id:
            raise ValueError("session_id cannot be empty")

        if self.wheel_index not in range(1, 5):
            raise ValueError("wheel_index must be between 1 and 4")

        if direction not in {"CW", "CCW"}:
            raise ValueError("direction must be CW or CCW")

        if action not in {item.value for item in ActionType}:
            raise ValueError(
                "action_type must be DIGIT_MOVE, PROBE, WIDE_PROBE, "
                "BINDING_SWEEP or BINDING_REFERENCE_SWEEP"
            )

        if tension not in {"LOADED", "UNLOADED", "UNSPECIFIED"}:
            raise ValueError(
                "tension_state must be LOADED, UNLOADED or UNSPECIFIED"
            )

        if self.digit_steps < 1 or self.digit_steps > 2000:
            raise ValueError("digit_steps must be between 1 and 2000")

        if self.correct_digit not in {-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9}:
            raise ValueError("correct_digit must be -1 (unknown) or between 0 and 9")
        if (
            action == ActionType.BINDING_REFERENCE_SWEEP.value
            and self.correct_digit == -1
        ):
            raise ValueError("Binding reference sweep requires a known correct_digit")

        if self.start_digit not in range(10):
            raise ValueError("start_digit must be between 0 and 9")

        if not self.scenario.strip():
            raise ValueError("scenario cannot be empty")

        if not self.collection_mode.strip():
            raise ValueError("collection_mode cannot be empty")

        for index, digit in enumerate(self.wheel_digits, start=1):
            if digit not in range(10):
                raise ValueError(
                    f"wheel_{index}_digit must be between 0 and 9"
                )

        if self.wheel_digits[self.wheel_index - 1] != self.start_digit:
            raise ValueError(
                "The target wheel digit must match start_digit"
            )

        required_text_fields = {
            "lock_id": self.lock_id,
            "tape_version": self.tape_version,
            "microphone_position": self.microphone_position,
            "focusrite_gain": self.focusrite_gain,
            "spring_setting": self.spring_setting,
        }

        for field_name, value in required_text_fields.items():
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")

        if self.repetition < 1:
            raise ValueError("repetition must be at least 1")

        if action == ActionType.PROBE.value:
            if self.probe_amplitude not in range(5, 61):
                raise ValueError(
                    "probe_amplitude must be between 5 and 60 steps"
                )

        if action == ActionType.WIDE_PROBE.value:
            if not (
                WIDE_PROBE_MIN_AMPLITUDE_STEPS
                <= self.probe_amplitude
                <= WIDE_PROBE_MAX_AMPLITUDE_STEPS
            ):
                raise ValueError(
                    "wide probe amplitude must be between "
                    f"{WIDE_PROBE_MIN_AMPLITUDE_STEPS} and "
                    f"{WIDE_PROBE_MAX_AMPLITUDE_STEPS} steps"
                )
            if not (
                WIDE_PROBE_MIN_CYCLES
                <= self.probe_cycles
                <= WIDE_PROBE_MAX_CYCLES
            ):
                raise ValueError(
                    "wide probe cycles must be between "
                    f"{WIDE_PROBE_MIN_CYCLES} and {WIDE_PROBE_MAX_CYCLES}"
                )

        if action == ActionType.BINDING_SWEEP.value:
            if self.sweep_steps != WHEEL_STEPS_PER_REV:
                raise ValueError(
                    f"Binding sweep must use {WHEEL_STEPS_PER_REV} steps"
                )
            if self.sector_steps != WHEEL_STEPS_PER_DIGIT:
                raise ValueError(
                    f"Binding sweep sectors must use {WHEEL_STEPS_PER_DIGIT} steps"
                )
            if self.sweep_steps % self.sector_steps != 0:
                raise ValueError(
                    "sweep_steps must be divisible by sector_steps"
                )

        if action == ActionType.BINDING_REFERENCE_SWEEP.value:
            if direction != "CCW":
                raise ValueError(
                    "Binding reference sweep is fixed to CCW"
                )
            if self.sweep_steps != BINDING_REFERENCE_SWEEP_STEPS:
                raise ValueError(
                    f"Binding reference sweep must use "
                    f"{BINDING_REFERENCE_SWEEP_STEPS} steps"
                )
            if self.sector_steps != BINDING_REFERENCE_SWEEP_SECTOR_STEPS:
                raise ValueError(
                    f"Binding reference sectors must use "
                    f"{BINDING_REFERENCE_SWEEP_SECTOR_STEPS} steps"
                )
            if self.start_digit != (self.correct_digit + 1) % 10:
                raise ValueError(
                    "Binding reference sweep must start one digit after "
                    "the known correct digit"
                )

    @property
    def wheel_digits(self) -> tuple[int, int, int, int]:
        return (
            self.wheel_1_digit,
            self.wheel_2_digit,
            self.wheel_3_digit,
            self.wheel_4_digit,
        )

    @property
    def current_code_before(self) -> str:
        return "".join(str(value) for value in self.wheel_digits)

    @property
    def end_digit(self) -> int:
        if self.action_type in {
            ActionType.PROBE.value,
            ActionType.WIDE_PROBE.value,
            ActionType.BINDING_SWEEP.value,
        }:
            return self.start_digit

        if self.action_type == ActionType.BINDING_REFERENCE_SWEEP.value:
            sectors = self.sweep_steps // self.sector_steps
            if self.direction == "CW":
                return (self.start_digit - sectors) % 10
            return (self.start_digit + sectors) % 10

        if self.direction == "CW":
            return (self.start_digit - 1) % 10

        return (self.start_digit + 1) % 10

    @property
    def wheel_digits_after(self) -> tuple[int, int, int, int]:
        digits = list(self.wheel_digits)
        digits[self.wheel_index - 1] = self.end_digit
        return tuple(digits)  # type: ignore[return-value]

    @property
    def current_code_after(self) -> str:
        return "".join(str(value) for value in self.wheel_digits_after)

    @property
    def expected_final_step(self) -> int:
        if self.action_type == ActionType.PROBE.value:
            return self.probe_amplitude * 4
        if self.action_type == ActionType.WIDE_PROBE.value:
            return self.probe_amplitude * (4 * self.probe_cycles + 2)
        if self.action_type in {
            ActionType.BINDING_SWEEP.value,
            ActionType.BINDING_REFERENCE_SWEEP.value,
        }:
            return self.sweep_steps
        return self.digit_steps

    @property
    def start_event_type(self) -> EspEventType:
        if self.action_type == ActionType.PROBE.value:
            return EspEventType.PROBE_START
        if self.action_type == ActionType.WIDE_PROBE.value:
            return EspEventType.WIDE_PROBE_START
        return EspEventType.SCAN_START

    @property
    def end_event_type(self) -> EspEventType:
        if self.action_type == ActionType.PROBE.value:
            return EspEventType.PROBE_END
        if self.action_type == ActionType.WIDE_PROBE.value:
            return EspEventType.WIDE_PROBE_END
        return EspEventType.SCAN_END

    @property
    def expected_event_sequence(self) -> tuple[EspEventType, ...]:
        if self.action_type == ActionType.PROBE.value:
            return (
                EspEventType.PROBE_START,
                EspEventType.PROBE_SEGMENT,
                EspEventType.PROBE_SEGMENT,
                EspEventType.PROBE_SEGMENT,
                EspEventType.PROBE_END,
            )

        if self.action_type == ActionType.WIDE_PROBE.value:
            segment_count = 2 * self.probe_cycles + 2
            return (
                EspEventType.WIDE_PROBE_START,
                *(
                    EspEventType.WIDE_PROBE_SEGMENT
                    for _ in range(segment_count)
                ),
                EspEventType.WIDE_PROBE_END,
            )

        if self.action_type in {
            ActionType.BINDING_SWEEP.value,
            ActionType.BINDING_REFERENCE_SWEEP.value,
        }:
            boundary_count = (self.sweep_steps // self.sector_steps) - 1
            return (
                EspEventType.SCAN_START,
                *(EspEventType.DIGIT_BOUNDARY for _ in range(boundary_count)),
                EspEventType.SCAN_END,
            )

        return (
            EspEventType.SCAN_START,
            EspEventType.SCAN_END,
        )


@dataclass(frozen=True)
class EspEvent:
    run_id: str
    event_type: EspEventType
    esp_time_us: int
    digit_index: int
    step: int
    pc_time_ns: int
    raw_message: str

    def relative_esp_time_s(self, scan_start_us: int) -> float:
        return (self.esp_time_us - scan_start_us) / 1_000_000.0


@dataclass(frozen=True)
class StatusSnapshot:
    acquisition_state: str
    fault: str
    wheel_busy: bool
    rail_busy: bool
    rail_homed: bool
    servo_busy: bool
    limit_triggered: bool
    rail_position: int


@dataclass(frozen=True)
class ConfigSnapshot:
    servo_configured: bool
    wheel_configured: bool
    rail_configured: bool
    limit_verified: bool
    auto_enabled: bool

    @property
    def collection_ready(self) -> bool:
        return (
            self.servo_configured
            and self.wheel_configured
            and self.rail_configured
            and self.limit_verified
            and self.auto_enabled
        )


@dataclass(frozen=True)
class SerialMessage:
    message_type: MessageType
    raw: str
    pc_time_ns: int
    name: str = ""
    run_id: str = ""
    detail: str = ""
    state: str = ""
    fault: str = ""
    values: tuple[str, ...] = ()
    event: EspEvent | None = None
    status: StatusSnapshot | None = None
    config: ConfigSnapshot | None = None


@dataclass
class AudioResult:
    samples: NDArray[np.float32]
    sample_rate: int
    channels: int
    started_at_ns: int
    stopped_at_ns: int
    statuses: list[str] = field(default_factory=list)
    overflowed: bool = False

    @property
    def frame_count(self) -> int:
        return int(self.samples.shape[0]) if self.samples.ndim else 0

    @property
    def duration_s(self) -> float:
        if self.sample_rate <= 0:
            return 0.0

        return self.frame_count / self.sample_rate


@dataclass
class QualityReport:
    valid: bool
    errors: list[str] = field(default_factory=list)

    event_count: int = 0
    digit_boundary_count: int = 0
    probe_segment_count: int = 0
    final_step: int = 0

    duration_s: float = 0.0
    peak: float = 0.0
    rms: float = 0.0

    clipped_sample_count: int = 0
    clipped_ratio: float = 0.0

    contains_non_finite: bool = False
    audio_overflow: bool = False

    target_peak: float = 0.0
    target_rms: float = 0.0
    target_clipped_sample_count: int = 0
    target_clipped_ratio: float = 0.0
    target_contains_non_finite: bool = False

    reference_peak: float = 0.0
    reference_rms: float = 0.0
    reference_clipped_sample_count: int = 0
    reference_clipped_ratio: float = 0.0
    reference_contains_non_finite: bool = False


@dataclass
class RunResult:
    request: RunRequest
    status: RunStatus

    output_dir: Path | None = None
    quality: QualityReport | None = None
    error_message: str = ""

    started_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at_utc: str = ""

    def mark_finished(self) -> None:
        self.finished_at_utc = datetime.now(timezone.utc).isoformat()
