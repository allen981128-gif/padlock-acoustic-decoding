from __future__ import annotations

import time
from datetime import datetime, timezone
from collections.abc import Callable

from audio_recorder import (
    AudioRecorder,
    AudioRecorderError,
)
from config import CONFIG, AppConfig
from models import (
    AudioResult,
    ControllerState,
    EspEvent,
    EspEventType,
    MessageType,
    QualityReport,
    RunRequest,
    RunResult,
    RunStatus,
)
from protocol import (
    build_prepare_command,
    build_recording_command,
    build_stop_command,
)
from quality_control import QualityControl
from run_writer import RunWriter, RunWriterError
from serial_client import (
    Esp32ResponseError,
    SerialClient,
    SerialClientError,
    SerialTimeoutError,
)


class AcquisitionError(RuntimeError):
    pass


class AcquisitionController:
    def __init__(
        self,
        serial_client: SerialClient,
        audio_recorder: AudioRecorder,
        run_writer: RunWriter,
        quality_control: QualityControl,
        config: AppConfig = CONFIG,
        expected_final_step: int | None = None,
        state_callback: Callable[[ControllerState], None] | None = None,
    ) -> None:
        self._serial = serial_client
        self._audio = audio_recorder
        self._writer = run_writer
        self._quality = quality_control
        self._config = config
        self._expected_final_step = expected_final_step
        self._state_callback = state_callback

        self._state = ControllerState.IDLE

    @property
    def state(self) -> ControllerState:
        return self._state

    def collect_run(
        self,
        request: RunRequest,
        *,
        reuse_contact: bool = False,
        keep_servo_down_after: bool = False,
    ) -> RunResult:
        result = RunResult(
            request=request,
            status=RunStatus.PENDING,
        )

        history_mark = self._serial.history_mark()

        audio: AudioResult | None = None
        events: list[EspEvent] = []
        quality: QualityReport | None = None

        started_at_ns = time.perf_counter_ns()
        error_message = ""

        try:
            self._require_open_serial()
            self._perform_handshake()

            self._set_state(ControllerState.PREPARING)
            self._serial.send_line(
                build_prepare_command(
                    request,
                    reuse_contact=reuse_contact,
                )
            )

            self._serial.wait_for_type(
                MessageType.ACK,
                self._config.timeouts.prepare_s,
                name="PREPARE",
                run_id=request.run_id,
            )

            self._set_state(
                ControllerState.WAITING_FOR_READY
            )

            self._serial.wait_for_type(
                MessageType.READY_TO_RECORD,
                self._config.timeouts.prepare_s,
                run_id=request.run_id,
            )

            self._audio.start()

            self._set_state(ControllerState.PRE_ROLL)
            time.sleep(self._config.audio.pre_roll_s)

            self._serial.send_line(
                build_recording_command(
                    request.run_id
                )
            )

            self._serial.wait_for_type(
                MessageType.ACK,
                self._config.timeouts.scan_start_s,
                name="RECORDING",
                run_id=request.run_id,
            )

            self._set_state(
                ControllerState.WAITING_FOR_SCAN
            )

            action_start = self._wait_for_event(
                request,
                request.start_event_type,
                self._config.timeouts.scan_start_s,
            )
            events.append(action_start)

            self._set_state(
                ControllerState.PROBING
                if request.action_type in {"PROBE", "WIDE_PROBE"}
                else ControllerState.SCANNING
            )

            events.extend(
                self._collect_until_action_end(
                    request,
                    request.end_event_type,
                )
            )

            self._serial.wait_for_type(
                MessageType.DONE,
                self._config.timeouts.done_s,
                run_id=request.run_id,
            )

            self._set_state(ControllerState.POST_ROLL)
            time.sleep(self._config.audio.post_roll_s)

            # Audio is still split one WAV per digit.  Servo movement is kept
            # outside every WAV.  In fast Digit Scan mode the drive head may
            # remain down after a VALID candidate when the next candidate uses
            # the same wheel.
            audio = self._audio.stop()

            quality = self._quality.evaluate(
                request=request,
                audio=audio,
                events=events,
                expected_final_step=request.expected_final_step,
            )

            # W3 physical unlock is intentionally detected from the contact-mic
            # transient itself. A genuine release click can saturate either input,
            # so clipping alone must not prevent the frozen unlock detector from
            # seeing the saved WAV. All non-clipping QC failures remain fatal.
            w3_unlock_clipping_only = (
                request.wheel_index == 3
                and request.action_type == "DIGIT_MOVE"
                and request.collection_mode == "auto_recognition_unlock_v1"
                and bool(quality.errors)
                and set(quality.errors).issubset(
                    {"AUDIO_CLIPPED", "REFERENCE_AUDIO_CLIPPED"}
                )
            )
            if w3_unlock_clipping_only:
                # Preserve peak/RMS/clipped counts and ratios as diagnostics, but
                # downgrade clipping from a rejection reason for this W3 path only.
                quality.errors = []
                quality.valid = True

            run_status = (
                RunStatus.VALID
                if quality.valid
                else RunStatus.REJECTED
            )

            leave_contact_down = bool(
                keep_servo_down_after
                and run_status is RunStatus.VALID
                and request.action_type == "DIGIT_MOVE"
            )

            if not leave_contact_down:
                self._serial.send_line("SERVO,UP")

                self._serial.wait_for_type(
                    MessageType.ACK,
                    self._config.timeouts.done_s,
                    name="SERVO_UP",
                )

                self._serial.wait_for_type(
                    MessageType.COMPLETED,
                    self._config.timeouts.done_s,
                    name="SERVO",
                )

            self._set_state(ControllerState.SAVING)

            serial_messages = (
                self._serial.history_since(
                    history_mark
                )
            )

            output_dir = self._writer.write_run(
                request=request,
                status=run_status,
                audio=audio,
                events=events,
                quality=quality,
                serial_messages=serial_messages,
                metadata=self._build_metadata(
                    request=request,
                    started_at_ns=started_at_ns,
                    finished_at_ns=time.perf_counter_ns(),
                    reuse_contact=reuse_contact,
                    kept_servo_down_after=leave_contact_down,
                ),
            )

            result.status = run_status
            result.output_dir = output_dir
            result.quality = quality
            result.mark_finished()

            self._set_state(
                ControllerState.COMPLETED
            )

            return result

        except KeyboardInterrupt:
            error_message = "Collection interrupted"
            run_status = RunStatus.ABORTED

        except (
            AcquisitionError,
            AudioRecorderError,
            Esp32ResponseError,
            SerialClientError,
            SerialTimeoutError,
            RunWriterError,
            ValueError,
        ) as exc:
            error_message = str(exc)
            run_status = RunStatus.FAILED

        except Exception as exc:
            error_message = (
                f"Unexpected collection error: {exc}"
            )
            run_status = RunStatus.FAILED

        self._set_state(ControllerState.ABORTING)

        self._send_stop()

        if self._audio.is_recording:
            try:
                audio = self._audio.stop()
            except AudioRecorderError:
                self._audio.abort()
                audio = None

        if audio is not None:
            quality = self._quality.evaluate(
                request=request,
                audio=audio,
                events=events,
                expected_final_step=request.expected_final_step,
            )

        serial_messages = self._serial.history_since(
            history_mark
        )

        try:
            output_dir = self._writer.write_run(
                request=request,
                status=run_status,
                audio=audio,
                events=events,
                quality=quality,
                serial_messages=serial_messages,
                metadata=self._build_metadata(
                    request=request,
                    started_at_ns=started_at_ns,
                    finished_at_ns=time.perf_counter_ns(),
                    reuse_contact=reuse_contact,
                    kept_servo_down_after=False,
                ),
                error_message=error_message,
            )
        except RunWriterError:
            output_dir = None

        result.status = run_status
        result.output_dir = output_dir
        result.quality = quality
        result.error_message = error_message
        result.mark_finished()

        self._set_state(ControllerState.FAILED)
        return result

    def _perform_handshake(self) -> None:
        self._set_state(ControllerState.HANDSHAKE)

        self._serial.ping(
            self._config.timeouts.ping_s
        )

        status, device_config = (
            self._serial.request_status(
                self._config.timeouts.status_s
            )
        )

        if status.acquisition_state != "IDLE":
            raise AcquisitionError(
                "ESP32 is not idle"
            )

        if status.fault != "NONE":
            raise AcquisitionError(
                f"ESP32 fault: {status.fault}"
            )

        if not device_config.collection_ready:
            raise AcquisitionError(
                "ESP32 collection configuration "
                "is not ready"
            )

    def _wait_for_event(
        self,
        request: RunRequest,
        event_type: EspEventType,
        timeout_s: float,
    ) -> EspEvent:
        message = self._serial.wait_for(
            predicate=lambda item: (
                item.message_type
                is MessageType.EVENT
                and item.event is not None
                and item.event.event_type
                is event_type
            ),
            timeout_s=timeout_s,
            description=event_type.value,
        )

        event = message.event

        if event is None:
            raise AcquisitionError(
                "EVENT message did not contain an event"
            )

        self._validate_event_run_id(
            event,
            request,
        )

        return event

    def _collect_until_action_end(
        self,
        request: RunRequest,
        end_event_type: EspEventType,
    ) -> list[EspEvent]:
        events: list[EspEvent] = []
        deadline = (
            time.monotonic()
            + self._config.timeouts.scan_end_s
        )

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise SerialTimeoutError(
                    f"Timed out waiting for {end_event_type.value}"
                )

            message = self._serial.read_message(
                remaining
            )

            if message is None:
                raise SerialTimeoutError(
                    f"Timed out waiting for {end_event_type.value}"
                )

            if message.message_type is MessageType.ERROR:
                raise Esp32ResponseError(message)

            if message.message_type is MessageType.DONE:
                raise AcquisitionError(
                    f"DONE received before {end_event_type.value}"
                )

            if (
                message.message_type
                is not MessageType.EVENT
                or message.event is None
            ):
                continue

            event = message.event
            self._validate_event_run_id(
                event,
                request,
            )

            if event.event_type is request.start_event_type:
                raise AcquisitionError(
                    f"Duplicate {request.start_event_type.value} event"
                )

            events.append(event)

            if event.event_type is end_event_type:
                return events

    def _validate_event_run_id(
        self,
        event: EspEvent,
        request: RunRequest,
    ) -> None:
        if event.run_id != request.run_id:
            raise AcquisitionError(
                "ESP32 event run_id does not match "
                "the active run"
            )

    def _send_stop(self) -> None:
        if not self._serial.is_open:
            return

        try:
            self._serial.send_line(
                build_stop_command()
            )

            self._serial.wait_for_type(
                MessageType.COMPLETED,
                self._config.timeouts.stop_s,
                name="STOP",
                raise_on_esp_error=False,
            )
        except (
            SerialClientError,
            SerialTimeoutError,
            ValueError,
        ):
            return

    def _require_open_serial(self) -> None:
        if not self._serial.is_open:
            raise AcquisitionError(
                "ESP32 serial connection is not open"
            )

    def _build_metadata(
        self,
        request: RunRequest,
        started_at_ns: int,
        finished_at_ns: int,
        *,
        reuse_contact: bool = False,
        kept_servo_down_after: bool = False,
    ) -> dict[str, object]:
        device = self._audio.device

        return {
            "controller_started_at_ns": (
                started_at_ns
            ),
            "controller_finished_at_ns": (
                finished_at_ns
            ),
            "controller_duration_s": (
                finished_at_ns - started_at_ns
            )
            / 1_000_000_000.0,
            "saved_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "serial_port": self._serial.port,
            "audio_device_index": (
                device.index
                if device is not None
                else None
            ),
            "audio_device_name": (
                device.name
                if device is not None
                else ""
            ),
            "audio_host_api": (
                device.host_api
                if device is not None
                else ""
            ),
            "audio_mode": "dual_input_synchronised",
            "target_input": "Focusrite analogue Input 1",
            "reference_input": "Focusrite analogue Input 2",
            "target_audio_file": "audio.wav",
            "reference_audio_file": "motor_reference.wav",
            "dual_audio_file": "audio_dual.wav",
            "pre_roll_s": (
                self._config.audio.pre_roll_s
            ),
            "post_roll_s": (
                self._config.audio.post_roll_s
            ),
            "action_type": request.action_type,
            "collection_mode": request.collection_mode,
            "tension_state": request.tension_state,
            "probe_amplitude": request.probe_amplitude,
            "probe_cycles": request.probe_cycles,
            "sweep_steps": request.sweep_steps,
            "sector_steps": request.sector_steps,
            "digit_steps": request.digit_steps,
            "reuse_contact": bool(reuse_contact),
            "kept_servo_down_after": bool(kept_servo_down_after),
            "current_code_before": request.current_code_before,
            "current_code_after": request.current_code_after,
            "expected_final_step": request.expected_final_step,
        }

    def _set_state(
        self,
        state: ControllerState,
    ) -> None:
        self._state = state

        if self._state_callback is not None:
            self._state_callback(state)
