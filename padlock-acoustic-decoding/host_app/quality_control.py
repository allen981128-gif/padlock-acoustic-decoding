from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import numpy as np

from config import CONFIG, QualityConfig
from models import (
    ActionType,
    AudioResult,
    EspEvent,
    EspEventType,
    QualityReport,
    RunRequest,
)


class QualityControl:
    def __init__(
        self,
        config: QualityConfig = CONFIG.quality,
    ) -> None:
        self._config = config

    def evaluate(
        self,
        request: RunRequest,
        audio: AudioResult,
        events: Sequence[EspEvent],
        expected_final_step: int | None = None,
    ) -> QualityReport:
        errors: list[str] = []

        target_metrics, reference_metrics = self._check_audio(
            audio,
            errors,
        )

        resolved_expected_final_step = (
            request.expected_final_step
            if expected_final_step is None
            else expected_final_step
        )

        event_metrics = self._check_events(
            request,
            events,
            resolved_expected_final_step,
            errors,
        )

        return QualityReport(
            valid=not errors,
            errors=errors,
            event_count=len(events),
            digit_boundary_count=event_metrics["digit_boundary_count"],
            probe_segment_count=event_metrics["probe_segment_count"],
            final_step=event_metrics["final_step"],
            duration_s=audio.duration_s,
            peak=target_metrics["peak"],
            rms=target_metrics["rms"],
            clipped_sample_count=target_metrics["clipped_sample_count"],
            clipped_ratio=target_metrics["clipped_ratio"],
            contains_non_finite=target_metrics["contains_non_finite"],
            audio_overflow=audio.overflowed,
            target_peak=target_metrics["peak"],
            target_rms=target_metrics["rms"],
            target_clipped_sample_count=(
                target_metrics["clipped_sample_count"]
            ),
            target_clipped_ratio=target_metrics["clipped_ratio"],
            target_contains_non_finite=(
                target_metrics["contains_non_finite"]
            ),
            reference_peak=reference_metrics["peak"],
            reference_rms=reference_metrics["rms"],
            reference_clipped_sample_count=(
                reference_metrics["clipped_sample_count"]
            ),
            reference_clipped_ratio=(
                reference_metrics["clipped_ratio"]
            ),
            reference_contains_non_finite=(
                reference_metrics["contains_non_finite"]
            ),
        )

    def _check_audio(
        self,
        audio: AudioResult,
        errors: list[str],
    ) -> tuple[
        dict[str, float | int | bool],
        dict[str, float | int | bool],
    ]:
        samples = np.asarray(audio.samples, dtype=np.float32)

        if samples.size == 0:
            errors.append("AUDIO_EMPTY")
            empty = self._empty_metrics()
            return empty, empty.copy()

        if samples.ndim != 2 or samples.shape[1] < 2:
            errors.append("AUDIO_DUAL_CHANNEL_REQUIRED")
            target = samples.reshape(-1)
            target_metrics = self._channel_metrics(target)
            return target_metrics, self._empty_metrics()

        target = samples[:, 0]
        reference = samples[:, 1]

        target_metrics = self._channel_metrics(target)
        reference_metrics = self._channel_metrics(reference)

        self._append_channel_errors(
            target_metrics,
            errors,
            prefix="",
        )
        self._append_channel_errors(
            reference_metrics,
            errors,
            prefix="REFERENCE_",
        )

        if audio.duration_s < self._config.minimum_duration_s:
            errors.append("AUDIO_TOO_SHORT")

        if audio.overflowed:
            errors.append("AUDIO_OVERFLOW")

        if audio.statuses:
            errors.append("AUDIO_STATUS_REPORTED")

        return target_metrics, reference_metrics

    def _channel_metrics(
        self,
        samples: np.ndarray,
    ) -> dict[str, float | int | bool]:
        contains_non_finite = not bool(np.isfinite(samples).all())
        finite_samples = samples[np.isfinite(samples)]

        if finite_samples.size == 0:
            return {
                "peak": 0.0,
                "rms": 0.0,
                "clipped_sample_count": 0,
                "clipped_ratio": 0.0,
                "contains_non_finite": contains_non_finite,
            }

        absolute = np.abs(finite_samples)
        clipped_sample_count = int(
            np.count_nonzero(
                absolute >= self._config.clipping_level
            )
        )

        return {
            "peak": float(np.max(absolute)),
            "rms": float(
                np.sqrt(
                    np.mean(
                        np.square(finite_samples, dtype=np.float64)
                    )
                )
            ),
            "clipped_sample_count": clipped_sample_count,
            "clipped_ratio": (
                clipped_sample_count / finite_samples.size
            ),
            "contains_non_finite": contains_non_finite,
        }

    def _append_channel_errors(
        self,
        metrics: dict[str, float | int | bool],
        errors: list[str],
        *,
        prefix: str,
    ) -> None:
        if bool(metrics["contains_non_finite"]):
            errors.append(f"{prefix}AUDIO_NON_FINITE")

        if float(metrics["rms"]) < self._config.minimum_rms:
            errors.append(f"{prefix}AUDIO_TOO_QUIET")

        if (
            float(metrics["clipped_ratio"])
            > self._config.max_clipped_ratio
        ):
            errors.append(f"{prefix}AUDIO_CLIPPED")

    @staticmethod
    def _empty_metrics() -> dict[str, float | int | bool]:
        return {
            "peak": 0.0,
            "rms": 0.0,
            "clipped_sample_count": 0,
            "clipped_ratio": 0.0,
            "contains_non_finite": False,
        }

    def _check_events(
        self,
        request: RunRequest,
        events: Sequence[EspEvent],
        expected_final_step: int,
        errors: list[str],
    ) -> dict[str, int]:
        counts = Counter(event.event_type for event in events)

        expected_order = list(request.expected_event_sequence)
        actual_order = [event.event_type for event in events]

        if actual_order != expected_order:
            errors.append("EVENT_ORDER_ERROR")

        if any(event.run_id != request.run_id for event in events):
            errors.append("RUN_ID_MISMATCH")

        if not self._event_times_are_monotonic(events):
            errors.append("EVENT_TIME_ORDER_ERROR")

        event_steps = [event.step for event in events]
        if any(
            current < previous
            for previous, current in zip(event_steps, event_steps[1:])
        ):
            errors.append("STEP_ORDER_ERROR")

        final_step = events[-1].step if events else 0
        if final_step != expected_final_step:
            errors.append("WRONG_FINAL_STEP")

        probe_segment_count = (
            counts[EspEventType.PROBE_SEGMENT]
            + counts[EspEventType.WIDE_PROBE_SEGMENT]
        )
        digit_boundary_count = counts[EspEventType.DIGIT_BOUNDARY]

        if request.action_type == ActionType.PROBE.value:
            self._check_probe_events(request, events, errors)
        elif request.action_type == ActionType.WIDE_PROBE.value:
            self._check_wide_probe_events(request, events, errors)
        elif request.action_type in {
            ActionType.BINDING_SWEEP.value,
            ActionType.BINDING_REFERENCE_SWEEP.value,
        }:
            self._check_binding_sweep_events(request, events, errors)
        else:
            if counts[EspEventType.SCAN_START] != 1:
                errors.append("INVALID_SCAN_START_COUNT")
            if counts[EspEventType.SCAN_END] != 1:
                errors.append("INVALID_SCAN_END_COUNT")
            if digit_boundary_count != 0:
                errors.append("INVALID_BOUNDARY_COUNT")

        return {
            "digit_boundary_count": digit_boundary_count,
            "probe_segment_count": probe_segment_count,
            "final_step": final_step,
        }


    @staticmethod
    def _check_binding_sweep_events(
        request: RunRequest,
        events: Sequence[EspEvent],
        errors: list[str],
    ) -> None:
        counts = Counter(event.event_type for event in events)

        if counts[EspEventType.SCAN_START] != 1:
            errors.append("INVALID_SCAN_START_COUNT")
        if counts[EspEventType.SCAN_END] != 1:
            errors.append("INVALID_SCAN_END_COUNT")

        boundaries = [
            event
            for event in events
            if event.event_type is EspEventType.DIGIT_BOUNDARY
        ]
        expected_count = (request.sweep_steps // request.sector_steps) - 1
        if len(boundaries) != expected_count:
            errors.append("INVALID_BOUNDARY_COUNT")

        expected_indices = list(range(1, expected_count + 1))
        actual_indices = [event.digit_index for event in boundaries]
        if actual_indices != expected_indices:
            errors.append("INVALID_BOUNDARY_INDICES")

        expected_steps = [
            request.sector_steps * index
            for index in expected_indices
        ]
        actual_steps = [event.step for event in boundaries]
        if actual_steps != expected_steps:
            errors.append("INVALID_BOUNDARY_STEPS")

    @staticmethod
    def _check_probe_events(
        request: RunRequest,
        events: Sequence[EspEvent],
        errors: list[str],
    ) -> None:
        counts = Counter(event.event_type for event in events)

        if counts[EspEventType.PROBE_START] != 1:
            errors.append("INVALID_PROBE_START_COUNT")
        if counts[EspEventType.PROBE_SEGMENT] != 3:
            errors.append("INVALID_PROBE_SEGMENT_COUNT")
        if counts[EspEventType.PROBE_END] != 1:
            errors.append("INVALID_PROBE_END_COUNT")

        segments = [
            event
            for event in events
            if event.event_type is EspEventType.PROBE_SEGMENT
        ]

        expected_indices = [1, 2, 3]
        actual_indices = [event.digit_index for event in segments]
        if actual_indices != expected_indices:
            errors.append("INVALID_PROBE_SEGMENT_INDICES")

        amplitude = request.probe_amplitude
        expected_steps = [amplitude, amplitude * 3, amplitude * 4]
        actual_steps = [event.step for event in segments]
        if actual_steps != expected_steps:
            errors.append("INVALID_PROBE_SEGMENT_STEPS")


    @staticmethod
    def _check_wide_probe_events(
        request: RunRequest,
        events: Sequence[EspEvent],
        errors: list[str],
    ) -> None:
        counts = Counter(event.event_type for event in events)
        segment_count = 2 * request.probe_cycles + 2

        if counts[EspEventType.WIDE_PROBE_START] != 1:
            errors.append("INVALID_WIDE_PROBE_START_COUNT")
        if counts[EspEventType.WIDE_PROBE_SEGMENT] != segment_count:
            errors.append("INVALID_WIDE_PROBE_SEGMENT_COUNT")
        if counts[EspEventType.WIDE_PROBE_END] != 1:
            errors.append("INVALID_WIDE_PROBE_END_COUNT")

        segments = [
            event
            for event in events
            if event.event_type is EspEventType.WIDE_PROBE_SEGMENT
        ]
        expected_indices = list(range(1, segment_count + 1))
        actual_indices = [event.digit_index for event in segments]
        if actual_indices != expected_indices:
            errors.append("INVALID_WIDE_PROBE_SEGMENT_INDICES")

        amplitude = request.probe_amplitude
        expected_steps: list[int] = []
        cumulative = amplitude
        expected_steps.append(cumulative)
        for _ in range(request.probe_cycles * 2):
            cumulative += amplitude * 2
            expected_steps.append(cumulative)
        cumulative += amplitude
        expected_steps.append(cumulative)

        actual_steps = [event.step for event in segments]
        if actual_steps != expected_steps:
            errors.append("INVALID_WIDE_PROBE_SEGMENT_STEPS")

    @staticmethod
    def _event_times_are_monotonic(events: Sequence[EspEvent]) -> bool:
        if not events:
            return False

        esp_times = [event.esp_time_us for event in events]
        pc_times = [event.pc_time_ns for event in events]

        return all(
            current >= previous
            for previous, current in zip(esp_times, esp_times[1:])
        ) and all(
            current >= previous
            for previous, current in zip(pc_times, pc_times[1:])
        )
