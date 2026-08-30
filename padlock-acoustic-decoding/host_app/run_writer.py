from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from config import CONFIG, AudioConfig, StorageConfig
from models import (
    AudioResult,
    EspEvent,
    QualityReport,
    RunRequest,
    RunStatus,
    SerialMessage,
)


class RunWriterError(RuntimeError):
    pass


class RunWriter:
    def __init__(
        self,
        storage_config: StorageConfig = CONFIG.storage,
        audio_config: AudioConfig = CONFIG.audio,
    ) -> None:
        self._storage = storage_config
        self._audio = audio_config

    def write_run(
        self,
        request: RunRequest,
        status: RunStatus,
        audio: AudioResult | None,
        events: Sequence[EspEvent],
        quality: QualityReport | None,
        *,
        serial_messages: Sequence[SerialMessage] = (),
        metadata: Mapping[str, Any] | None = None,
        error_message: str = "",
    ) -> Path:
        self._validate_names(request)
        self._validate_inputs(status, audio, quality)

        partial_dir = self._partial_dir(request)
        final_dir = self._final_dir(request, status)

        if partial_dir.exists():
            shutil.rmtree(partial_dir)

        if final_dir.exists():
            raise RunWriterError(
                f"Run directory already exists: {final_dir}"
            )

        partial_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        try:
            if audio is not None:
                self._write_audio_files(
                    partial_dir,
                    audio,
                )

            self._write_events(
                partial_dir / self._storage.events_filename,
                events,
                audio,
            )

            self._write_serial_log(
                partial_dir / "serial_log.csv",
                serial_messages,
            )

            self._write_metadata(
                partial_dir / self._storage.metadata_filename,
                request,
                status,
                audio,
                serial_messages,
                metadata,
                error_message,
            )

            self._write_quality(
                partial_dir / self._storage.quality_filename,
                quality,
            )

            final_dir.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            partial_dir.replace(final_dir)

        except Exception as exc:
            raise RunWriterError(
                f"Could not save run {request.run_id}: {exc}"
            ) from exc

        self._remove_empty_partial_parents(
            partial_dir.parent
        )

        return final_dir

    def _write_audio_files(
        self,
        directory: Path,
        audio: AudioResult,
    ) -> None:
        if audio.samples.size == 0:
            raise RunWriterError(
                "Audio data is empty"
            )

        samples = np.asarray(
            audio.samples,
            dtype=np.float32,
        )

        if samples.ndim != 2 or samples.shape[1] < 2:
            raise RunWriterError(
                "Dual-channel audio is required"
            )

        dual = np.ascontiguousarray(samples[:, :2])
        target = np.ascontiguousarray(dual[:, 0])
        reference = np.ascontiguousarray(dual[:, 1])

        self._write_wav(
            directory / self._storage.audio_filename,
            target,
            audio.sample_rate,
        )
        self._write_wav(
            directory / self._storage.reference_audio_filename,
            reference,
            audio.sample_rate,
        )
        self._write_wav(
            directory / self._storage.dual_audio_filename,
            dual,
            audio.sample_rate,
        )

    def _write_wav(
        self,
        path: Path,
        samples: np.ndarray,
        sample_rate: int,
    ) -> None:
        sf.write(
            file=str(path),
            data=samples,
            samplerate=sample_rate,
            subtype=self._audio.wav_subtype,
            format="WAV",
        )

    def _write_events(
        self,
        path: Path,
        events: Sequence[EspEvent],
        audio: AudioResult | None,
    ) -> None:
        fieldnames = [
            "sequence",
            "pc_time_ns",
            "received_audio_elapsed_s",
            "aligned_audio_elapsed_s",
            "aligned_sample_index",
            "esp_time_us",
            "esp_relative_time_s",
            "event",
            "digit_index",
            "step",
            "run_id",
            "raw_message",
        ]

        with path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
            )
            writer.writeheader()

            action_start = next(
                (
                    event
                    for event in events
                    if event.event_type.value
                    in {"SCAN_START", "PROBE_START", "WIDE_PROBE_START"}
                ),
                None,
            )

            action_start_received_s: float | None = None

            if (
                audio is not None
                and audio.started_at_ns > 0
                and action_start is not None
            ):
                action_start_received_s = (
                    action_start.pc_time_ns
                    - audio.started_at_ns
                ) / 1_000_000_000.0

            for sequence, event in enumerate(events):
                received_elapsed: float | str = ""
                aligned_elapsed: float | str = ""
                aligned_sample_index: int | str = ""
                esp_relative_time_s: float | str = ""

                if (
                    audio is not None
                    and audio.started_at_ns > 0
                ):
                    received_elapsed = (
                        event.pc_time_ns
                        - audio.started_at_ns
                    ) / 1_000_000_000.0

                if (
                    action_start is not None
                    and action_start_received_s is not None
                    and audio is not None
                ):
                    esp_relative_time_s = (
                        event.esp_time_us
                        - action_start.esp_time_us
                    ) / 1_000_000.0

                    aligned_elapsed = (
                        action_start_received_s
                        + esp_relative_time_s
                    )

                    aligned_sample_index = int(
                        round(
                            aligned_elapsed
                            * audio.sample_rate
                        )
                    )

                writer.writerow(
                    {
                        "sequence": sequence,
                        "pc_time_ns": event.pc_time_ns,
                        "received_audio_elapsed_s": (
                            received_elapsed
                        ),
                        "aligned_audio_elapsed_s": (
                            aligned_elapsed
                        ),
                        "aligned_sample_index": (
                            aligned_sample_index
                        ),
                        "esp_time_us": event.esp_time_us,
                        "esp_relative_time_s": (
                            esp_relative_time_s
                        ),
                        "event": event.event_type.value,
                        "digit_index": event.digit_index,
                        "step": event.step,
                        "run_id": event.run_id,
                        "raw_message": event.raw_message,
                    }
                )

    def _write_serial_log(
        self,
        path: Path,
        messages: Sequence[SerialMessage],
    ) -> None:
        fieldnames = [
            "sequence",
            "pc_time_ns",
            "message_type",
            "name",
            "run_id",
            "state",
            "fault",
            "detail",
            "event_type",
            "esp_time_us",
            "digit_index",
            "step",
            "raw_message",
        ]

        with path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
            )
            writer.writeheader()

            for sequence, message in enumerate(messages):
                event = message.event

                writer.writerow(
                    {
                        "sequence": sequence,
                        "pc_time_ns": message.pc_time_ns,
                        "message_type": (
                            message.message_type.value
                        ),
                        "name": message.name,
                        "run_id": message.run_id,
                        "state": message.state,
                        "fault": message.fault,
                        "detail": message.detail,
                        "event_type": (
                            event.event_type.value
                            if event is not None
                            else ""
                        ),
                        "esp_time_us": (
                            event.esp_time_us
                            if event is not None
                            else ""
                        ),
                        "digit_index": (
                            event.digit_index
                            if event is not None
                            else ""
                        ),
                        "step": (
                            event.step
                            if event is not None
                            else ""
                        ),
                        "raw_message": message.raw,
                    }
                )

    def _write_metadata(
        self,
        path: Path,
        request: RunRequest,
        status: RunStatus,
        audio: AudioResult | None,
        serial_messages: Sequence[SerialMessage],
        metadata: Mapping[str, Any] | None,
        error_message: str,
    ) -> None:
        payload: dict[str, Any] = {
            "run": asdict(request),
            "status": status.value,
            "error_message": error_message,
            "audio": None,
            "serial_message_count": len(
                serial_messages
            ),
        }

        if audio is not None:
            payload["audio"] = {
                "sample_rate": audio.sample_rate,
                "channels": audio.channels,
                "frames": audio.frame_count,
                "duration_s": audio.duration_s,
                "started_at_ns": audio.started_at_ns,
                "stopped_at_ns": audio.stopped_at_ns,
                "statuses": list(audio.statuses),
                "overflowed": audio.overflowed,
                "wav_subtype": self._audio.wav_subtype,
                "capture_channels": self._audio.capture_channels,
                "target_input_channel_zero_based": (
                    self._audio.target_channel
                ),
                "reference_input_channel_zero_based": (
                    self._audio.reference_channel
                ),
                "channel_layout": {
                    "audio.wav": "lock target, mono",
                    "motor_reference.wav": "motor reference, mono",
                    "audio_dual.wav": {
                        "channel_1": "lock target",
                        "channel_2": "motor reference",
                    },
                },
                "event_alignment": {
                    "anchor": (
                        "ACTION_START_PC_RECEIVE_TIME"
                    ),
                    "relative_timing": (
                        "ESP32_EVENT_TIME_US"
                    ),
                    "sample_index_field": (
                        "events.csv:"
                        "aligned_sample_index"
                    ),
                },
            }

        if metadata:
            payload["collection"] = dict(metadata)

        self._write_json(path, payload)

    def _write_quality(
        self,
        path: Path,
        quality: QualityReport | None,
    ) -> None:
        payload: dict[str, Any]

        if quality is None:
            payload = {
                "valid": False,
                "errors": [
                    "QUALITY_REPORT_NOT_AVAILABLE"
                ],
            }
        else:
            payload = asdict(quality)

        self._write_json(path, payload)

    def _write_json(
        self,
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        with path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                self._json_ready(dict(payload)),
                file,
                indent=2,
                ensure_ascii=False,
            )

    def _partial_dir(
        self,
        request: RunRequest,
    ) -> Path:
        return (
            self._storage.dataset_dir
            / ".partial"
            / request.session_id
            / f"{request.run_id}.partial"
        )

    def _final_dir(
        self,
        request: RunRequest,
        status: RunStatus,
    ) -> Path:
        root = (
            self._storage.raw_dir
            if status is RunStatus.VALID
            else self._storage.rejected_dir
        )

        return (
            root
            / request.session_id
            / request.run_id
        )

    def _validate_inputs(
        self,
        status: RunStatus,
        audio: AudioResult | None,
        quality: QualityReport | None,
    ) -> None:
        if status is RunStatus.VALID:
            if audio is None:
                raise RunWriterError(
                    "Valid runs require audio data"
                )

            if quality is None or not quality.valid:
                raise RunWriterError(
                    "Valid runs require a valid quality report"
                )

    def _validate_names(
        self,
        request: RunRequest,
    ) -> None:
        self._validate_path_name(
            request.session_id,
            "session_id",
        )
        self._validate_path_name(
            request.run_id,
            "run_id",
        )

    @staticmethod
    def _validate_path_name(
        value: str,
        field_name: str,
    ) -> None:
        if not value:
            raise RunWriterError(
                f"{field_name} cannot be empty"
            )

        if value in {".", ".."}:
            raise RunWriterError(
                f"Invalid {field_name}: {value}"
            )

        if any(
            character in value
            for character in '<>:"/\\|?*'
        ):
            raise RunWriterError(
                f"Invalid {field_name}: {value}"
            )

    @staticmethod
    def _json_ready(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value

        if isinstance(value, Path):
            return str(value)

        if isinstance(value, np.generic):
            return value.item()

        if isinstance(value, Mapping):
            return {
                str(key): RunWriter._json_ready(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                RunWriter._json_ready(item)
                for item in value
            ]

        return value

    @staticmethod
    def _remove_empty_partial_parents(
        path: Path,
    ) -> None:
        current = path

        for _ in range(2):
            try:
                current.rmdir()
            except OSError:
                return

            current = current.parent