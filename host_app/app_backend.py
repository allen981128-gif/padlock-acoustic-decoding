from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

import sounddevice as sd

from acquisition_controller import AcquisitionController
from audio_recorder import AudioRecorder
from config import (
    BINDING_REFERENCE_SWEEP_SECTOR_STEPS,
    BINDING_REFERENCE_SWEEP_STEPS,
    CONFIG,
    WHEEL_STEPS_PER_DIGIT,
    WIDE_PROBE_MAX_AMPLITUDE_STEPS,
    WIDE_PROBE_MAX_CYCLES,
    WIDE_PROBE_MIN_AMPLITUDE_STEPS,
    WIDE_PROBE_MIN_CYCLES,
    AppConfig,
    ensure_storage_directories,
)
from device_discovery import (
    AudioInputInfo,
    SerialPortInfo,
    list_audio_inputs,
    list_serial_ports,
)
from models import (
    ActionType,
    ConfigSnapshot,
    ControllerState,
    MessageType,
    RunRequest,
    RunResult,
    RunStatus,
    StatusSnapshot,
)
from protocol import (
    build_goto_command,
    build_home_command,
    build_limit_read_command,
    build_rail_jog_command,
    build_reset_fault_command,
    build_servo_down_command,
    build_servo_up_command,
    build_stop_command,
    build_wheel_jog_command,
)
from quality_control import QualityControl
from run_writer import RunWriter
from serial_client import SerialClient, SerialTimeoutError
from session_controller import SessionController


LogCallback = Callable[[str], None]
StateCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, RunRequest], None]
ResultCallback = Callable[[int, RunResult], None]
StopAfterResultCallback = Callable[[int, RunResult], str | None]


class BackendError(RuntimeError):
    pass


class PadlockBackend:
    def __init__(self) -> None:
        self._serial: SerialClient | None = None
        self._serial_port = ""
        self._audio_device: int | None = None

        self._operation_lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._current_audio: AudioRecorder | None = None

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def serial_port(self) -> str:
        return self._serial_port

    @property
    def audio_device(self) -> int | None:
        return self._audio_device

    def scan_devices(
        self,
    ) -> tuple[list[SerialPortInfo], list[AudioInputInfo]]:
        return list_serial_ports(), list_audio_inputs()

    def connect(
        self,
        serial_port: str,
        audio_device: int,
        log: LogCallback,
    ) -> tuple[StatusSnapshot, ConfigSnapshot]:
        with self._operation_lock:
            self.disconnect(log)

            log(f"Opening ESP32 serial port {serial_port}...")
            client = SerialClient(
                config=CONFIG.serial,
                port=serial_port,
            )
            client.open()
            client.clear_cancel()

            try:
                client.ping(CONFIG.timeouts.ping_s)
                status, device_config = client.request_status(
                    CONFIG.timeouts.status_s
                )
                self._check_audio_device(audio_device)
            except Exception:
                client.close()
                raise

            self._serial = client
            self._serial_port = serial_port
            self._audio_device = audio_device

            log(f"ESP32 connected on {serial_port}")
            log(f"Audio input {audio_device} passed configuration check")
            return status, device_config

    def disconnect(self, log: LogCallback | None = None) -> None:
        with self._operation_lock:
            client = self._serial
            self._serial = None
            self._serial_port = ""
            self._audio_device = None

            if client is not None:
                client.close()
                if log is not None:
                    log("Devices disconnected")

    def refresh_status(
        self,
        log: LogCallback,
    ) -> tuple[StatusSnapshot, ConfigSnapshot]:
        with self._operation_lock:
            client = self._require_serial()
            client.clear_cancel()
            client.drain_messages()
            status, device_config = client.request_status(
                CONFIG.timeouts.status_s
            )
            log(self._format_status(status, device_config))
            return status, device_config

    def read_limit(self, log: LogCallback) -> str:
        with self._operation_lock:
            client = self._require_serial()
            client.clear_cancel()
            client.drain_messages()
            client.send_line(build_limit_read_command())
            message = client.wait_for_type(
                MessageType.LIMIT,
                CONFIG.timeouts.status_s,
            )
            log(message.raw)
            return message.raw

    def home(self, log: LogCallback) -> tuple[StatusSnapshot, ConfigSnapshot]:
        with self._operation_lock:
            self._send_completed_command(
                command=build_servo_up_command(),
                ack_name="SERVO_UP",
                completed_name="SERVO",
                timeout_s=20.0,
                log=log,
            )
            self._send_completed_command(
                command=build_home_command(),
                ack_name="HOME",
                completed_name="HOME",
                timeout_s=300.0,
                log=log,
            )
            return self.refresh_status(log)

    def goto_wheel(
        self,
        wheel_index: int,
        log: LogCallback,
    ) -> tuple[StatusSnapshot, ConfigSnapshot]:
        with self._operation_lock:
            self._send_completed_command(
                command=build_goto_command(wheel_index),
                ack_name="GOTO",
                completed_name="GOTO",
                timeout_s=240.0,
                log=log,
            )
            return self.refresh_status(log)

    def servo_up(self, log: LogCallback) -> None:
        with self._operation_lock:
            self._send_completed_command(
                command=build_servo_up_command(),
                ack_name="SERVO_UP",
                completed_name="SERVO",
                timeout_s=20.0,
                log=log,
            )

    def servo_down(self, log: LogCallback) -> None:
        with self._operation_lock:
            self._send_completed_command(
                command=build_servo_down_command(),
                ack_name="SERVO_DOWN",
                completed_name="SERVO",
                timeout_s=20.0,
                log=log,
            )

    def wheel_jog(
        self,
        direction: str,
        steps: int,
        log: LogCallback,
    ) -> None:
        with self._operation_lock:
            self._send_completed_command(
                command=build_wheel_jog_command(direction, steps),
                ack_name="JOG_WHEEL",
                completed_name="JOG_WHEEL",
                timeout_s=60.0,
                log=log,
            )

    def rail_jog(
        self,
        direction: str,
        steps: int,
        log: LogCallback,
    ) -> None:
        with self._operation_lock:
            self._send_completed_command(
                command=build_rail_jog_command(direction, steps),
                ack_name="JOG_RAIL",
                completed_name="JOG_RAIL",
                timeout_s=300.0,
                log=log,
            )

    def transition_goto_wheel(
        self,
        wheel_index: int,
        log: LogCallback,
    ) -> tuple[StatusSnapshot, ConfigSnapshot]:
        """Raise the drive head, then move safely to one wheel."""
        with self._operation_lock:
            self.servo_up(log)
            return self.goto_wheel(wheel_index, log)

    def transition_to_code(
        self,
        *,
        current_digits: Sequence[int],
        target_digits: Sequence[int],
        digit_steps: int,
        settle_delay_s: float = 1.0,
        log: LogCallback,
    ) -> str:
        """Move the physical lock from one known 4-digit state to another.

        This helper is deliberately conservative: the servo is raised for every
        rail move, lowered only on the selected wheel, held for a configurable
        pressure-settle delay, and raised again after each adjustment. The shortest digit path is used; a five-digit tie is
        resolved CCW.  The caller must still require visual human confirmation
        before trusting the resulting code.
        """
        current = self._normalise_code(current_digits)
        target = self._normalise_code(target_digits)
        steps_per_digit = int(digit_steps)
        if steps_per_digit < 1:
            raise ValueError("digit_steps must be at least 1")

        settle_delay = float(settle_delay_s)
        if settle_delay < 0.0 or settle_delay > 10.0:
            raise ValueError("settle_delay_s must be between 0 and 10 seconds")

        with self._operation_lock:
            try:
                self.servo_up(log)
                for wheel_index in range(1, 5):
                    before = current[wheel_index - 1]
                    after = target[wheel_index - 1]
                    if before == after:
                        continue

                    ccw_digits = (after - before) % 10
                    cw_digits = (before - after) % 10
                    if ccw_digits <= cw_digits:
                        direction = "CCW"
                        digit_count = ccw_digits
                    else:
                        direction = "CW"
                        digit_count = cw_digits

                    steps = digit_count * steps_per_digit
                    log(
                        f"Transition W{wheel_index}: {before} -> {after}, "
                        f"{direction} {digit_count} digit(s), {steps} step(s)"
                    )
                    self.goto_wheel(wheel_index, log)
                    self.servo_down(log)
                    if settle_delay > 0.0:
                        log(
                            f"W{wheel_index}: servo down completed; waiting "
                            f"{settle_delay:.1f} s for contact pressure to settle"
                        )
                        time.sleep(settle_delay)
                    self.wheel_jog(direction, steps, log)
                    self.servo_up(log)
                    current[wheel_index - 1] = after

                code = "".join(str(value) for value in target)
                log(f"Automatic code transition finished at expected code {code}")
                return code
            finally:
                # Best effort: never intentionally leave the drive head down at
                # the end of a transition, including a failed transition.
                try:
                    self.servo_up(log)
                except Exception:
                    pass

    def reset_fault(self, log: LogCallback) -> None:
        with self._operation_lock:
            client = self._require_serial()
            client.clear_cancel()
            client.drain_messages()
            client.send_line(build_reset_fault_command())
            message = client.wait_for_type(
                MessageType.ACK,
                CONFIG.timeouts.stop_s,
                name="RESET_FAULT",
            )
            log(message.raw)

    def stop(self, log: LogCallback) -> None:
        with self._operation_lock:
            client = self._require_serial()
            client.clear_cancel()
            client.drain_messages()
            client.send_line(build_stop_command())
            ack = client.wait_for_type(
                MessageType.ACK,
                CONFIG.timeouts.stop_s,
                name="STOP",
                raise_on_esp_error=False,
            )
            log(ack.raw)
            completed = client.wait_for_type(
                MessageType.COMPLETED,
                CONFIG.timeouts.stop_s,
                name="STOP",
                raise_on_esp_error=False,
            )
            log(completed.raw)

    def request_graceful_batch_stop(self) -> None:
        """Stop a running batch after the current run finishes normally."""
        self._stop_requested.set()

    def emergency_stop(self, log: LogCallback) -> None:
        self._stop_requested.set()

        audio = self._current_audio
        if audio is not None and audio.is_recording:
            audio.abort()
            log("Audio capture aborted")

        client = self._serial
        if client is None or not client.is_open:
            return

        # Release any worker waiting for ACK/COMPLETED before attempting the
        # emergency write. This keeps the UI responsive even if the current
        # operation has entered a long timeout.
        client.cancel_pending_waits()

        try:
            client.send_line(build_stop_command())
            log("Emergency STOP sent to ESP32")
        except Exception as exc:
            log(f"Could not send emergency STOP: {exc}")

    def build_single_digit_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetitions: int,
        dataset_dir: Path,
    ) -> list[RunRequest]:
        """Backwards-compatible wrapper for the original digit scan."""
        return self.build_digit_scan_requests(
            session_id=session_id,
            selected_wheels=selected_wheels,
            direction=direction,
            correct_digits=correct_digits,
            current_digits=(0, 0, 0, 0),
            lock_id=lock_id,
            scenario=scenario,
            tape_version=tape_version,
            microphone_position=microphone_position,
            focusrite_gain=focusrite_gain,
            spring_setting=spring_setting,
            repetitions=repetitions,
            tension_state="UNSPECIFIED",
            dataset_dir=dataset_dir,
        )

    def build_digit_scan_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetitions: int,
        tension_state: str,
        dataset_dir: Path,
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> list[RunRequest]:
        code = self._normalise_code(current_digits)
        self._validate_plan_inputs(
            selected_wheels=selected_wheels,
            correct_digits=correct_digits,
            repetitions=repetitions,
        )
        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []

        for wheel_index in selected_wheels:
            wheel_start = code[wheel_index - 1]
            for cycle in range(1, repetitions + 1):
                for _ in range(10):
                    request = self._make_request(
                        run_number=run_number,
                        session_id=session_id,
                        wheel_index=wheel_index,
                        direction=direction,
                        correct_digits=correct_digits,
                        code=code,
                        action_type=ActionType.DIGIT_MOVE.value,
                        collection_mode="digit_scan",
                        tension_state=tension_state,
                        probe_amplitude=20,
                        digit_steps=digit_steps,
                        lock_id=lock_id,
                        scenario=scenario,
                        tape_version=tape_version,
                        microphone_position=microphone_position,
                        focusrite_gain=focusrite_gain,
                        spring_setting=spring_setting,
                        repetition=cycle,
                        notes=(
                            f"wheel_{wheel_index}_{code[wheel_index - 1]}_"
                            f"to_{self._next_digit(code[wheel_index - 1], direction)}"
                        ),
                    )
                    requests.append(request)
                    code = list(request.wheel_digits_after)
                    run_number += 1

                if code[wheel_index - 1] != wheel_start:
                    raise BackendError(
                        "Digit scan did not return to its starting digit"
                    )

        return requests

    def build_decision_digit_scan_requests(
        self,
        *,
        session_id: str,
        wheel_index: int,
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        dataset_dir: Path,
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> list[RunRequest]:
        """Build one Decision Batch wheel scan: 10 independent CCW digit moves.

        The training-time true combination is intentionally not supplied to the
        acquisition request.  Each wheel completes exactly one revolution and
        returns to the Decision start code.
        """
        if wheel_index not in {1, 2, 3, 4}:
            raise ValueError("wheel_index must be between 1 and 4")
        code = self._normalise_code(current_digits)
        start_code = list(code)
        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []

        for move_index in range(1, 11):
            request = self._make_request(
                run_number=run_number,
                session_id=session_id,
                wheel_index=wheel_index,
                direction="CCW",
                correct_digits=(-1, -1, -1, -1),
                code=code,
                action_type=ActionType.DIGIT_MOVE.value,
                collection_mode="decision_digit_scan",
                tension_state="LOADED",
                probe_amplitude=20,
                digit_steps=digit_steps,
                lock_id=lock_id,
                scenario=scenario,
                tape_version=tape_version,
                microphone_position=microphone_position,
                focusrite_gain=focusrite_gain,
                spring_setting=spring_setting,
                repetition=1,
                notes=(
                    f"decision_digit_scan_wheel_{wheel_index}_move_{move_index:02d}_"
                    f"{code[wheel_index - 1]}_to_"
                    f"{self._next_digit(code[wheel_index - 1], 'CCW')}"
                ),
            )
            requests.append(request)
            code = list(request.wheel_digits_after)
            run_number += 1

        if code != start_code:
            raise BackendError(
                "Decision digit scan did not return to the Decision start code"
            )
        return requests

    def build_continuous_decision_requests(
        self,
        *,
        session_id: str,
        scan_order: Sequence[int],
        direction: str,
        current_digits: Sequence[int],
        binding_wheel: int,
        true_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        dataset_dir: Path,
        start_candidate_index: int = 1,
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> list[RunRequest]:
        """Build one continuous Decision: 10 one-digit runs per active wheel.

        There are no operator prompts or deliberate inter-run pauses inside the
        Decision.  Each wheel completes one full revolution and therefore
        returns to the Decision start code before the next wheel is scanned.
        Training labels are stored as metadata only; they are not used by the
        movement controller.
        """
        code0 = self._normalise_code(current_digits)
        true_code = self._normalise_code(true_digits)
        resolved_direction = str(direction).strip().upper()
        if resolved_direction not in {"CW", "CCW"}:
            raise ValueError("Decision direction must be CW or CCW")
        order = [int(wheel) for wheel in scan_order]
        if not order or len(set(order)) != len(order):
            raise ValueError("scan_order must contain unique wheel numbers")
        if any(wheel not in {1, 2, 3, 4} for wheel in order):
            raise ValueError("scan_order wheels must be between 1 and 4")
        if binding_wheel not in order:
            raise ValueError("binding_wheel must be present in scan_order")
        total_candidates = len(order) * 10
        if start_candidate_index not in range(1, total_candidates + 1):
            raise ValueError("start_candidate_index is out of range")

        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []
        candidate_index = 1
        total_target_count = 0

        for scan_position, wheel_index in enumerate(order, start=1):
            code = list(code0)
            for move_index in range(1, 11):
                to_digit = self._next_digit(code[wheel_index - 1], resolved_direction)
                is_true_gate = int(to_digit == true_code[wheel_index - 1])
                is_target = int(
                    wheel_index == binding_wheel
                    and to_digit == true_code[wheel_index - 1]
                )
                total_target_count += is_target
                if candidate_index >= start_candidate_index:
                    request = self._make_request(
                        run_number=run_number,
                        session_id=session_id,
                        wheel_index=wheel_index,
                        direction=resolved_direction,
                        correct_digits=(-1, -1, -1, -1),
                        code=code,
                        action_type=ActionType.DIGIT_MOVE.value,
                        collection_mode="decision_digit_scan_v2",
                        tension_state="LOADED",
                        probe_amplitude=20,
                        digit_steps=digit_steps,
                        lock_id=lock_id,
                        scenario=scenario,
                        tape_version=tape_version,
                        microphone_position=microphone_position,
                        focusrite_gain=focusrite_gain,
                        spring_setting=spring_setting,
                        repetition=1,
                        notes=(
                            f"decision_candidate_{candidate_index:03d}_"
                            f"{resolved_direction.lower()}_wheel_{wheel_index}_move_{move_index:02d}_"
                            f"{code[wheel_index - 1]}_to_{to_digit}"
                        ),
                    )
                    request = replace(
                        request,
                        decision_move_index=move_index,
                        decision_scan_position=scan_position,
                        decision_candidate_index=candidate_index,
                        decision_binding_wheel=binding_wheel,
                        decision_target_digit=true_code[binding_wheel - 1],
                        decision_true_w1=true_code[0],
                        decision_true_w2=true_code[1],
                        decision_true_w3=true_code[2],
                        decision_true_w4=true_code[3],
                        decision_is_true_gate_movement=is_true_gate,
                        decision_is_target=is_target,
                    )
                    requests.append(request)
                    run_number += 1
                code[wheel_index - 1] = to_digit
                candidate_index += 1

            if code != list(code0):
                raise BackendError(
                    f"Decision wheel W{wheel_index} did not return to the Decision start code"
                )

        if total_target_count != 1:
            raise BackendError("Decision must contain exactly one target candidate")
        return requests

    def build_auto_recognition_requests(
        self,
        *,
        session_id: str,
        wheel_index: int,
        direction: str,
        current_digits: Sequence[int],
        profile_id: str,
        repeat_id: str,
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        dataset_dir: Path,
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> list[RunRequest]:
        """Build one unknown-lock MAIN-v8 component: exactly ten 1-digit WAVs.

        The correct combination is intentionally absent.  The target wheel makes
        one complete revolution in the requested direction and returns to the
        supplied physical start code.  Metadata identifies the recognition profile,
        direction and A/B repeat only; all truth/target fields remain unknown.
        """
        wheel_index = int(wheel_index)
        if wheel_index not in {1, 2, 4}:
            raise ValueError("Automatic True-Gate recognition supports W1, W2 and W4 only")
        resolved_direction = str(direction).strip().upper()
        if resolved_direction not in {"CW", "CCW"}:
            raise ValueError("Automatic-recognition direction must be CW or CCW")
        resolved_repeat = str(repeat_id).strip().upper()
        if resolved_repeat not in {"A", "B"}:
            raise ValueError("Automatic-recognition repeat must be A or B")
        profile_id = str(profile_id).strip()
        if not profile_id:
            raise ValueError("Automatic-recognition profile_id cannot be empty")

        code = self._normalise_code(current_digits)
        start_code = list(code)
        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []
        active_mask = [1 if item == wheel_index else 0 for item in range(1, 5)]

        for move_index in range(1, 11):
            to_digit = self._next_digit(code[wheel_index - 1], resolved_direction)
            request = self._make_request(
                run_number=run_number,
                session_id=session_id,
                wheel_index=wheel_index,
                direction=resolved_direction,
                correct_digits=(-1, -1, -1, -1),
                code=code,
                action_type=ActionType.DIGIT_MOVE.value,
                # Legacy metadata identifier retained for compatibility with existing datasets.
                collection_mode="auto_recognition_main_v7",
                tension_state="LOADED",
                probe_amplitude=20,
                digit_steps=digit_steps,
                lock_id=lock_id,
                scenario=scenario,
                tape_version=tape_version,
                microphone_position=microphone_position,
                focusrite_gain=focusrite_gain,
                spring_setting=spring_setting,
                repetition=1,
                notes=(
                    f"auto_main_v7_profile={profile_id}; component={resolved_direction}_{resolved_repeat}; "
                    f"wheel=W{wheel_index}; move={move_index:02d}; "
                    f"{code[wheel_index - 1]}_to_{to_digit}; correct_combination=UNKNOWN"
                ),
            )
            request = replace(
                request,
                profile_id=profile_id,
                group_id=profile_id,
                decision_id=f"{profile_id}_{resolved_direction}",
                decision_repeat_id=resolved_repeat,
                decision_move_index=move_index,
                decision_scan_position=1,
                decision_candidate_index=move_index,
                decision_active_w1=active_mask[0],
                decision_active_w2=active_mask[1],
                decision_active_w3=active_mask[2],
                decision_active_w4=active_mask[3],
                decision_binding_wheel=wheel_index,
                decision_target_digit=-1,
                decision_true_w1=-1,
                decision_true_w2=-1,
                decision_true_w3=-1,
                decision_true_w4=-1,
                decision_is_true_gate_movement=0,
                decision_is_target=0,
                decision_binding_confidence=0,
                batch_task_type="digit_scan",
                binding_prefix_stage=0,
                binding_prefix_valid=-1,
                binding_expected_wheel=0,
                binding_probe_wheel=0,
                batch_plan_id="AUTO_RECOGNITION_RUNTIME",
                batch_plan_source_row=0,
            )
            requests.append(request)
            code = list(request.wheel_digits_after)
            run_number += 1

        if code != start_code:
            raise BackendError(
                f"Automatic recognition W{wheel_index} {resolved_direction}_{resolved_repeat} did not return to the start code"
            )
        return requests

    def build_auto_unlock_search_requests(
        self,
        *,
        session_id: str,
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        dataset_dir: Path,
        moves: int,
        move_index_offset: int = 0,
        prefix_rank: int = 0,
        prefix_text: str = "",
        pass_number: int = 1,
        direction: str = "CCW",
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> list[RunRequest]:
        """Build one continuous W3 physical-unlock search segment.

        Each movement remains a normal one-digit DIGIT_MOVE and therefore
        produces its own WAV/events/metadata folder.  A segment may contain
        fewer than ten movements when a previous detector trigger was rejected
        by the operator and the remaining positions of the same circle must be
        completed.

        No correct combination or W3 true-gate label is supplied.  The only
        downstream stopping signal is the independent physical-unlock detector.
        """
        resolved_direction = str(direction).strip().upper()
        if resolved_direction != "CCW":
            raise ValueError("Unlock Detector v1 W3 search is fixed to CCW")
        moves = int(moves)
        if moves < 1 or moves > 10:
            raise ValueError("W3 unlock search moves must be between 1 and 10")
        move_index_offset = int(move_index_offset)
        if move_index_offset < 0 or move_index_offset > 9:
            raise ValueError("move_index_offset must be between 0 and 9")
        if move_index_offset + moves > 10:
            raise ValueError("W3 unlock search segment cannot exceed a 10-position circle")

        pass_number = int(pass_number)
        if pass_number < 1:
            raise ValueError("pass_number must be at least 1")

        code = self._normalise_code(current_digits)
        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []
        profile_id = f"AUTO_{session_id}_P{pass_number}_W3_UNLOCK_V1"

        for local_index in range(1, moves + 1):
            global_index = move_index_offset + local_index
            to_digit = self._next_digit(code[2], resolved_direction)
            request = self._make_request(
                run_number=run_number,
                session_id=session_id,
                wheel_index=3,
                direction=resolved_direction,
                correct_digits=(-1, -1, -1, -1),
                code=code,
                action_type=ActionType.DIGIT_MOVE.value,
                collection_mode="auto_recognition_unlock_v1",
                tension_state="LOADED",
                probe_amplitude=20,
                digit_steps=digit_steps,
                lock_id=lock_id,
                scenario=scenario,
                tape_version=tape_version,
                microphone_position=microphone_position,
                focusrite_gain=focusrite_gain,
                spring_setting=spring_setting,
                repetition=1,
                notes=(
                    "physical_unlock_detector_v1; wheel=W3; direction=CCW; "
                    f"circle_move={global_index:02d}; {code[2]}_to_{to_digit}; "
                    f"recognition_pass={pass_number}; prefix_rank={int(prefix_rank)}; "
                    f"prefix={str(prefix_text or 'UNKNOWN')}; "
                    "correct_combination=UNKNOWN; true_gate_label=UNUSED"
                ),
            )
            request = replace(
                request,
                profile_id=profile_id,
                group_id=profile_id,
                decision_id=f"{profile_id}_PREFIX{int(prefix_rank):02d}",
                decision_repeat_id="U",
                decision_move_index=global_index,
                decision_scan_position=1,
                decision_candidate_index=global_index,
                decision_active_w1=0,
                decision_active_w2=0,
                decision_active_w3=1,
                decision_active_w4=0,
                decision_binding_wheel=0,
                decision_target_digit=-1,
                decision_true_w1=-1,
                decision_true_w2=-1,
                decision_true_w3=-1,
                decision_true_w4=-1,
                decision_is_true_gate_movement=0,
                decision_is_target=0,
                decision_binding_confidence=0,
                batch_task_type="unlock_search",
                binding_prefix_stage=0,
                binding_prefix_valid=-1,
                binding_expected_wheel=0,
                binding_probe_wheel=0,
                batch_plan_id="AUTO_UNLOCK_V1_RUNTIME",
                batch_plan_source_row=0,
            )
            requests.append(request)
            code = list(request.wheel_digits_after)
            run_number += 1

        return requests

    def build_binding_scan_requests(
        self,
        *,
        session_id: str,
        scan_order: Sequence[int],
        direction: str,
        current_digits: Sequence[int],
        true_digits: Sequence[int],
        prefix_stage: int,
        prefix_valid: int,
        expected_binding_wheel: int,
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        dataset_dir: Path,
        start_candidate_index: int = 1,
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> list[RunRequest]:
        """Build one plan-driven Binding Scan.

        Each probed wheel performs one full revolution as ten one-digit DIGIT_MOVE
        runs.  Every movement is saved as its own WAV, but there is deliberately
        no per-digit true-gate target.  Labels describe the prefix state and the
        expected next binding wheel at scan level.
        """
        code0 = self._normalise_code(current_digits)
        true_code = self._normalise_code(true_digits)
        resolved_direction = str(direction).strip().upper()
        if resolved_direction not in {"CW", "CCW"}:
            raise ValueError("Binding Scan direction must be CW or CCW")
        order = [int(wheel) for wheel in scan_order]
        if not order or len(set(order)) != len(order):
            raise ValueError("scan_order must contain unique wheel numbers")
        if any(wheel not in {1, 2, 3, 4} for wheel in order):
            raise ValueError("scan_order wheels must be between 1 and 4")
        if int(prefix_valid) not in {0, 1}:
            raise ValueError("prefix_valid must be 0 or 1")
        if int(prefix_stage) not in {0, 1, 2, 3, 4}:
            raise ValueError("prefix_stage must be between 0 and 4")
        if int(expected_binding_wheel) not in {0, 1, 2, 3, 4}:
            raise ValueError("expected_binding_wheel must be 0 (NONE) or W1-W4")
        if expected_binding_wheel and expected_binding_wheel not in order:
            raise ValueError("expected_binding_wheel must be one of the probed wheels, or 0 for NONE")

        total_candidates = len(order) * 10
        if start_candidate_index not in range(1, total_candidates + 1):
            raise ValueError("start_candidate_index is out of range")

        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []
        candidate_index = 1

        for scan_position, wheel_index in enumerate(order, start=1):
            code = list(code0)
            for move_index in range(1, 11):
                to_digit = self._next_digit(code[wheel_index - 1], resolved_direction)
                if candidate_index >= start_candidate_index:
                    request = self._make_request(
                        run_number=run_number,
                        session_id=session_id,
                        wheel_index=wheel_index,
                        direction=resolved_direction,
                        correct_digits=(-1, -1, -1, -1),
                        code=code,
                        action_type=ActionType.DIGIT_MOVE.value,
                        collection_mode="binding_scan_v1",
                        tension_state="LOADED",
                        probe_amplitude=20,
                        digit_steps=digit_steps,
                        lock_id=lock_id,
                        scenario=scenario,
                        tape_version=tape_version,
                        microphone_position=microphone_position,
                        focusrite_gain=focusrite_gain,
                        spring_setting=spring_setting,
                        repetition=1,
                        notes=(
                            f"binding_scan_candidate_{candidate_index:03d}_"
                            f"{resolved_direction.lower()}_wheel_{wheel_index}_move_{move_index:02d}_"
                            f"{code[wheel_index - 1]}_to_{to_digit}"
                        ),
                    )
                    request = replace(
                        request,
                        decision_move_index=move_index,
                        decision_scan_position=scan_position,
                        decision_candidate_index=candidate_index,
                        decision_binding_wheel=int(expected_binding_wheel),
                        decision_target_digit=-1,
                        decision_true_w1=true_code[0],
                        decision_true_w2=true_code[1],
                        decision_true_w3=true_code[2],
                        decision_true_w4=true_code[3],
                        decision_is_true_gate_movement=0,
                        decision_is_target=0,
                        batch_task_type="binding_scan",
                        binding_prefix_stage=int(prefix_stage),
                        binding_prefix_valid=int(prefix_valid),
                        binding_expected_wheel=int(expected_binding_wheel),
                        binding_probe_wheel=wheel_index,
                    )
                    requests.append(request)
                    run_number += 1
                code[wheel_index - 1] = to_digit
                candidate_index += 1

            if code != list(code0):
                raise BackendError(
                    f"Binding Scan wheel W{wheel_index} did not return to the planned start code"
                )
        return requests

    def build_binding_sweep_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetitions: int,
        tension_state: str,
        dataset_dir: Path,
    ) -> list[RunRequest]:
        """Build continuous full-revolution sweeps for binding comparison.

        Each run rotates one selected wheel by exactly one revolution without
        stopping at digit boundaries. The physical and tracked code therefore
        return to the same state after every valid run.
        """
        code = self._normalise_code(current_digits)
        self._validate_plan_inputs(
            selected_wheels=selected_wheels,
            correct_digits=correct_digits,
            repetitions=repetitions,
        )

        resolved_tension = tension_state.upper().strip()
        if resolved_tension not in {"LOADED", "UNLOADED"}:
            raise ValueError(
                "Binding sweep requires Loaded or Unloaded tension state"
            )

        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []

        for wheel_index in selected_wheels:
            start_digit = code[wheel_index - 1]
            for repeat in range(1, repetitions + 1):
                request = self._make_request(
                    run_number=run_number,
                    session_id=session_id,
                    wheel_index=wheel_index,
                    direction=direction,
                    correct_digits=correct_digits,
                    code=code,
                    action_type=ActionType.BINDING_SWEEP.value,
                    collection_mode="binding_sweep",
                    tension_state=resolved_tension,
                    probe_amplitude=20,
                    lock_id=lock_id,
                    scenario=scenario,
                    tape_version=tape_version,
                    microphone_position=microphone_position,
                    focusrite_gain=focusrite_gain,
                    spring_setting=spring_setting,
                    repetition=repeat,
                    notes=(
                        f"binding_sweep_wheel_{wheel_index}_"
                        f"start_{start_digit}_full_revolution"
                    ),
                )
                if request.current_code_after != request.current_code_before:
                    raise BackendError(
                        "Binding sweep did not return to the starting code"
                    )
                requests.append(request)
                run_number += 1

        return requests

    def build_binding_reference_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetitions: int,
        tension_state: str,
        dataset_dir: Path,
    ) -> list[RunRequest]:
        """Build one controlled eight-sector reference sweep.

        The target wheel must start one digit after its known correct digit,
        while all other wheels are fixed at their known correct digits. The
        CCW path ends one digit before the true gate and never enters it.
        """
        code = self._normalise_code(current_digits)
        self._validate_plan_inputs(
            selected_wheels=selected_wheels,
            correct_digits=correct_digits,
            repetitions=repetitions,
        )

        if len(selected_wheels) != 1:
            raise ValueError(
                "Binding reference sweep requires exactly one selected wheel"
            )
        if repetitions != 1:
            raise ValueError(
                "Binding reference sweep requires Repetitions = 1; reset the "
                "target wheel before each additional run"
            )
        if direction.upper() != "CCW":
            raise ValueError(
                "Binding reference sweep is fixed to CCW"
            )

        resolved_tension = tension_state.upper().strip()
        if resolved_tension not in {"LOADED", "UNLOADED"}:
            raise ValueError(
                "Binding reference sweep requires Loaded or Unloaded tension"
            )

        wheel_index = int(selected_wheels[0])
        correct = [int(value) for value in correct_digits]
        expected_start = (correct[wheel_index - 1] + 1) % 10
        if code[wheel_index - 1] != expected_start:
            raise ValueError(
                f"Wheel {wheel_index} must start at digit {expected_start}, "
                f"one digit after its correct digit {correct[wheel_index - 1]}"
            )

        for index in range(4):
            if index == wheel_index - 1:
                continue
            if code[index] != correct[index]:
                raise ValueError(
                    f"Wheel {index + 1} must be fixed at its correct digit "
                    f"{correct[index]} for a unique binding reference"
                )

        run_number = self._next_run_number(session_id, dataset_dir)
        request = self._make_request(
            run_number=run_number,
            session_id=session_id,
            wheel_index=wheel_index,
            direction="CCW",
            correct_digits=correct,
            code=code,
            action_type=ActionType.BINDING_REFERENCE_SWEEP.value,
            collection_mode="binding_reference_sweep",
            tension_state=resolved_tension,
            probe_amplitude=20,
            sweep_steps=BINDING_REFERENCE_SWEEP_STEPS,
            sector_steps=BINDING_REFERENCE_SWEEP_SECTOR_STEPS,
            lock_id=lock_id,
            scenario=scenario,
            tape_version=tape_version,
            microphone_position=microphone_position,
            focusrite_gain=focusrite_gain,
            spring_setting=spring_setting,
            repetition=1,
            notes=(
                f"binding_reference_wheel_{wheel_index}_"
                f"start_{expected_start}_avoid_true_gate"
            ),
        )

        expected_end = (correct[wheel_index - 1] - 1) % 10
        if request.end_digit != expected_end:
            raise BackendError(
                "Binding reference sweep endpoint calculation failed"
            )
        return [request]

    def build_probe_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetitions: int,
        tension_state: str,
        probe_amplitude: int,
        dataset_dir: Path,
        collection_mode: str = "state_probe",
    ) -> list[RunRequest]:
        code = self._normalise_code(current_digits)
        self._validate_plan_inputs(
            selected_wheels=selected_wheels,
            correct_digits=correct_digits,
            repetitions=repetitions,
        )
        if probe_amplitude not in range(5, 61):
            raise ValueError("Probe amplitude must be between 5 and 60 steps")

        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []

        for wheel_index in selected_wheels:
            for repeat in range(1, repetitions + 1):
                requests.append(
                    self._make_request(
                        run_number=run_number,
                        session_id=session_id,
                        wheel_index=wheel_index,
                        direction=direction,
                        correct_digits=correct_digits,
                        code=code,
                        action_type=ActionType.PROBE.value,
                        collection_mode=collection_mode,
                        tension_state=tension_state,
                        probe_amplitude=probe_amplitude,
                        lock_id=lock_id,
                        scenario=scenario,
                        tape_version=tape_version,
                        microphone_position=microphone_position,
                        focusrite_gain=focusrite_gain,
                        spring_setting=spring_setting,
                        repetition=repeat,
                        notes=(
                            f"wheel_{wheel_index}_digit_"
                            f"{code[wheel_index - 1]}_probe"
                        ),
                    )
                )
                run_number += 1

        return requests

    def build_wide_probe_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetitions: int,
        tension_state: str,
        probe_amplitude: int,
        probe_cycles: int,
        dataset_dir: Path,
    ) -> list[RunRequest]:
        """Build zero-net wide local probes around the current digit.

        Each run pre-positions by -A, performs N continuous -A↔+A cycles,
        then returns to the centre. The displayed code is unchanged.
        """
        code = self._normalise_code(current_digits)
        self._validate_plan_inputs(
            selected_wheels=selected_wheels,
            correct_digits=correct_digits,
            repetitions=repetitions,
        )
        if not (
            WIDE_PROBE_MIN_AMPLITUDE_STEPS
            <= probe_amplitude
            <= WIDE_PROBE_MAX_AMPLITUDE_STEPS
        ):
            raise ValueError(
                "Wide probe amplitude must be between "
                f"{WIDE_PROBE_MIN_AMPLITUDE_STEPS} and "
                f"{WIDE_PROBE_MAX_AMPLITUDE_STEPS} steps"
            )
        if not (
            WIDE_PROBE_MIN_CYCLES
            <= probe_cycles
            <= WIDE_PROBE_MAX_CYCLES
        ):
            raise ValueError(
                "Wide probe cycles must be between "
                f"{WIDE_PROBE_MIN_CYCLES} and {WIDE_PROBE_MAX_CYCLES}"
            )

        resolved_tension = tension_state.upper().strip()
        if resolved_tension not in {"LOADED", "UNLOADED"}:
            raise ValueError(
                "Wide local probe requires Loaded or Unloaded tension state"
            )

        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []
        for wheel_index in selected_wheels:
            for repeat in range(1, repetitions + 1):
                request = self._make_request(
                    run_number=run_number,
                    session_id=session_id,
                    wheel_index=wheel_index,
                    direction=direction,
                    correct_digits=correct_digits,
                    code=code,
                    action_type=ActionType.WIDE_PROBE.value,
                    collection_mode="wide_local_probe",
                    tension_state=resolved_tension,
                    probe_amplitude=probe_amplitude,
                    probe_cycles=probe_cycles,
                    lock_id=lock_id,
                    scenario=scenario,
                    tape_version=tape_version,
                    microphone_position=microphone_position,
                    focusrite_gain=focusrite_gain,
                    spring_setting=spring_setting,
                    repetition=repeat,
                    notes=(
                        f"wide_probe_wheel_{wheel_index}_digit_"
                        f"{code[wheel_index - 1]}_amp_{probe_amplitude}_"
                        f"cycles_{probe_cycles}"
                    ),
                )
                if request.current_code_after != request.current_code_before:
                    raise BackendError(
                        "Wide local probe did not return to the starting code"
                    )
                requests.append(request)
                run_number += 1

        return requests

    def build_unloaded_baseline_requests(
        self,
        *,
        session_id: str,
        selected_wheels: Sequence[int],
        direction: str,
        correct_digits: Sequence[int],
        current_digits: Sequence[int],
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        probe_repetitions: int,
        probe_amplitude: int,
        dataset_dir: Path,
    ) -> list[RunRequest]:
        code = self._normalise_code(current_digits)
        self._validate_plan_inputs(
            selected_wheels=selected_wheels,
            correct_digits=correct_digits,
            repetitions=probe_repetitions,
        )
        if probe_amplitude not in range(5, 61):
            raise ValueError("Probe amplitude must be between 5 and 60 steps")

        run_number = self._next_run_number(session_id, dataset_dir)
        requests: list[RunRequest] = []

        for wheel_index in selected_wheels:
            wheel_start = code[wheel_index - 1]

            for position_index in range(10):
                for repeat in range(1, probe_repetitions + 1):
                    requests.append(
                        self._make_request(
                            run_number=run_number,
                            session_id=session_id,
                            wheel_index=wheel_index,
                            direction=direction,
                            correct_digits=correct_digits,
                            code=code,
                            action_type=ActionType.PROBE.value,
                            collection_mode="unloaded_baseline",
                            tension_state="UNLOADED",
                            probe_amplitude=probe_amplitude,
                            lock_id=lock_id,
                            scenario=scenario,
                            tape_version=tape_version,
                            microphone_position=microphone_position,
                            focusrite_gain=focusrite_gain,
                            spring_setting=spring_setting,
                            repetition=repeat,
                            notes=(
                                f"baseline_wheel_{wheel_index}_digit_"
                                f"{code[wheel_index - 1]}_probe"
                            ),
                        )
                    )
                    run_number += 1

                transition = self._make_request(
                    run_number=run_number,
                    session_id=session_id,
                    wheel_index=wheel_index,
                    direction=direction,
                    correct_digits=correct_digits,
                    code=code,
                    action_type=ActionType.DIGIT_MOVE.value,
                    collection_mode="unloaded_baseline_transition",
                    tension_state="UNLOADED",
                    probe_amplitude=probe_amplitude,
                    lock_id=lock_id,
                    scenario=scenario,
                    tape_version=tape_version,
                    microphone_position=microphone_position,
                    focusrite_gain=focusrite_gain,
                    spring_setting=spring_setting,
                    repetition=position_index + 1,
                    notes=(
                        f"baseline_transition_wheel_{wheel_index}_"
                        f"{code[wheel_index - 1]}_to_"
                        f"{self._next_digit(code[wheel_index - 1], direction)}"
                    ),
                )
                requests.append(transition)
                code = list(transition.wheel_digits_after)
                run_number += 1

            if code[wheel_index - 1] != wheel_start:
                raise BackendError(
                    "Baseline cycle did not return to its starting digit"
                )

        return requests

    def _make_request(
        self,
        *,
        run_number: int,
        session_id: str,
        wheel_index: int,
        direction: str,
        correct_digits: Sequence[int],
        code: Sequence[int],
        action_type: str,
        collection_mode: str,
        tension_state: str,
        probe_amplitude: int,
        sweep_steps: int | None = None,
        sector_steps: int | None = None,
        lock_id: str,
        scenario: str,
        tape_version: str,
        microphone_position: str,
        focusrite_gain: str,
        spring_setting: str,
        repetition: int,
        notes: str,
        probe_cycles: int = 1,
        digit_steps: int = WHEEL_STEPS_PER_DIGIT,
    ) -> RunRequest:
        digits = self._normalise_code(code)
        extra: dict[str, int] = {}
        if sweep_steps is not None:
            extra["sweep_steps"] = int(sweep_steps)
        if sector_steps is not None:
            extra["sector_steps"] = int(sector_steps)

        return RunRequest(
            run_id=f"run_{run_number:06d}",
            session_id=session_id,
            wheel_index=wheel_index,
            direction=direction,
            correct_digit=int(correct_digits[wheel_index - 1]),
            start_digit=digits[wheel_index - 1],
            scenario=scenario,
            wheel_1_digit=digits[0],
            wheel_2_digit=digits[1],
            wheel_3_digit=digits[2],
            wheel_4_digit=digits[3],
            lock_id=lock_id,
            tape_version=tape_version,
            microphone_position=microphone_position,
            focusrite_gain=focusrite_gain,
            spring_setting=spring_setting,
            repetition=repetition,
            notes=notes,
            action_type=action_type,
            collection_mode=collection_mode,
            tension_state=tension_state,
            probe_amplitude=probe_amplitude,
            probe_cycles=probe_cycles,
            digit_steps=int(digit_steps),
            position_valid=True,
            **extra,
        )

    def _next_run_number(self, session_id: str, dataset_dir: Path) -> int:
        runtime_config = self.runtime_config(dataset_dir=dataset_dir)
        ensure_storage_directories(runtime_config)
        helper = SessionController(
            acquisition_controller=None,  # type: ignore[arg-type]
            config=runtime_config,
        )
        return helper._next_run_number(session_id)

    @staticmethod
    def _normalise_code(values: Sequence[int]) -> list[int]:
        if len(values) != 4:
            raise ValueError("Exactly four current digits are required")
        code = [int(value) for value in values]
        if any(value not in range(10) for value in code):
            raise ValueError("Every current digit must be between 0 and 9")
        return code

    @staticmethod
    def _validate_plan_inputs(
        *,
        selected_wheels: Sequence[int],
        correct_digits: Sequence[int],
        repetitions: int,
    ) -> None:
        if len(correct_digits) != 4:
            raise ValueError("Exactly four correct digits are required")
        if any(int(value) not in {-1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9} for value in correct_digits):
            raise ValueError("Every correct digit must be -1 (unknown) or 0-9")
        if not selected_wheels:
            raise ValueError("Select at least one wheel")
        if any(int(value) not in range(1, 5) for value in selected_wheels):
            raise ValueError("Selected wheel must be between 1 and 4")
        if repetitions < 1:
            raise ValueError("Repetitions must be at least 1")

    @staticmethod
    def _next_digit(digit: int, direction: str) -> int:
        return (digit - 1) % 10 if direction.upper() == "CW" else (digit + 1) % 10

    def collect_batch(
        self,
        *,
        requests: Sequence[RunRequest],
        dataset_dir: Path,
        pre_roll_s: float,
        post_roll_s: float,
        pause_between_runs_s: float,
        stop_on_rejected: bool,
        keep_contact_between_digits: bool,
        log: LogCallback,
        state_changed: StateCallback,
        progress: ProgressCallback,
        result_ready: ResultCallback,
        stop_after_result: StopAfterResultCallback | None = None,
    ) -> list[RunResult]:
        client = self._require_serial()
        audio_device = self._require_audio_device()

        self._stop_requested.clear()
        client.clear_cancel()

        runtime_config = self.runtime_config(
            dataset_dir=dataset_dir,
            pre_roll_s=pre_roll_s,
            post_roll_s=post_roll_s,
            pause_between_runs_s=pause_between_runs_s,
        )
        ensure_storage_directories(runtime_config)

        audio = AudioRecorder(
            config=runtime_config.audio,
            device_index=audio_device,
        )
        self._current_audio = audio

        writer = RunWriter(
            storage_config=runtime_config.storage,
            audio_config=runtime_config.audio,
        )
        quality = QualityControl(runtime_config.quality)
        controller = AcquisitionController(
            serial_client=client,
            audio_recorder=audio,
            run_writer=writer,
            quality_control=quality,
            config=runtime_config,
            expected_final_step=None,
            state_callback=lambda state: state_changed(
                state.value
                if isinstance(state, ControllerState)
                else str(state)
            ),
        )
        summary_helper = SessionController(
            acquisition_controller=controller,
            config=runtime_config,
        )

        results: list[RunResult] = []
        total = len(requests)
        contact_is_down = False

        try:
            for index, request in enumerate(requests, start=1):
                if self._stop_requested.is_set():
                    log("Batch stopped by operator")
                    break

                progress(index, total, request)
                log(
                    f"Run {index}/{total}: {request.action_type}, "
                    f"wheel {request.wheel_index}, "
                    f"{request.current_code_before} -> "
                    f"{request.current_code_after}, "
                    f"direction {request.direction}"
                )

                next_request = (
                    requests[index]
                    if index < total
                    else None
                )
                reuse_contact = bool(
                    keep_contact_between_digits
                    and contact_is_down
                    and request.action_type == ActionType.DIGIT_MOVE.value
                )
                keep_contact_after = bool(
                    keep_contact_between_digits
                    and request.action_type == ActionType.DIGIT_MOVE.value
                    and next_request is not None
                    and next_request.action_type == ActionType.DIGIT_MOVE.value
                    and next_request.wheel_index == request.wheel_index
                )

                result = controller.collect_run(
                    request,
                    reuse_contact=reuse_contact,
                    keep_servo_down_after=keep_contact_after,
                )
                contact_is_down = bool(
                    result.status is RunStatus.VALID
                    and keep_contact_after
                )
                results.append(result)
                summary_helper._append_summary(result)
                result_ready(index - 1, result)

                log(
                    f"{request.run_id}: {result.status.value}"
                    + (
                        f" ({result.error_message})"
                        if result.error_message
                        else ""
                    )
                )

                if result.status in {
                    RunStatus.FAILED,
                    RunStatus.ABORTED,
                }:
                    break

                if (
                    stop_on_rejected
                    and result.status is RunStatus.REJECTED
                ):
                    break

                if stop_after_result is not None and result.status is RunStatus.VALID:
                    stop_reason = stop_after_result(index - 1, result)
                    if stop_reason:
                        log(
                            f"Batch stopped after {request.run_id}: {stop_reason}"
                        )
                        break

                if index < total and pause_between_runs_s > 0:
                    time.sleep(pause_between_runs_s)

            return results
        finally:
            self._current_audio = None
            client.clear_cancel()

            # A graceful "pause after current" can arrive while a candidate
            # is recording.  That candidate may have intentionally left the
            # drive head down for the next same-wheel movement.  Always lift
            # before returning control to the operator.
            if contact_is_down and client.is_open:
                try:
                    self._send_completed_command(
                        command=build_servo_up_command(),
                        ack_name="SERVO_UP",
                        completed_name="SERVO",
                        timeout_s=20.0,
                        log=log,
                    )
                    contact_is_down = False
                except Exception as exc:
                    log(f"Could not raise drive head after fast Digit Scan: {exc}")

            self._stop_requested.clear()
            state_changed("IDLE")

    @staticmethod
    def runtime_config(
        *,
        dataset_dir: Path,
        pre_roll_s: float | None = None,
        post_roll_s: float | None = None,
        pause_between_runs_s: float | None = None,
    ) -> AppConfig:
        audio = CONFIG.audio
        session = CONFIG.session

        if pre_roll_s is not None or post_roll_s is not None:
            audio = replace(
                audio,
                pre_roll_s=(
                    audio.pre_roll_s
                    if pre_roll_s is None
                    else pre_roll_s
                ),
                post_roll_s=(
                    audio.post_roll_s
                    if post_roll_s is None
                    else post_roll_s
                ),
            )

        if pause_between_runs_s is not None:
            session = replace(
                session,
                pause_between_runs_s=pause_between_runs_s,
                require_confirmation=False,
            )

        storage = replace(
            CONFIG.storage,
            dataset_dir=dataset_dir,
        )

        return replace(
            CONFIG,
            audio=audio,
            storage=storage,
            session=session,
        )

    def _send_completed_command(
        self,
        *,
        command: str,
        ack_name: str,
        completed_name: str,
        timeout_s: float,
        log: LogCallback,
    ) -> None:
        with self._operation_lock:
            client = self._require_serial()
            client.clear_cancel()

            stale = client.drain_messages()
            if stale:
                log(
                    f"Cleared {len(stale)} stale ESP32 message(s) "
                    "before the next command"
                )

            history_mark = client.history_mark()
            log(f">>> {command}")
            client.send_line(command)

            started = time.monotonic()
            ack_window_s = min(5.0, timeout_s)

            def is_ack_or_completed(message: object) -> bool:
                message_type = getattr(message, "message_type", None)
                name = str(getattr(message, "name", "")).upper()
                return (
                    message_type is MessageType.ACK
                    and name == ack_name.upper()
                ) or (
                    message_type is MessageType.COMPLETED
                    and name == completed_name.upper()
                )

            try:
                try:
                    first = client.wait_for(
                        is_ack_or_completed,
                        ack_window_s,
                        (
                            f"ACK {ack_name} or COMPLETED "
                            f"{completed_name}"
                        ),
                    )
                except SerialTimeoutError:
                    # ACK is expected immediately, but it can be lost while a
                    # valid COMPLETED line still arrives later. Do not resend a
                    # motion command because that could move the hardware twice.
                    log(
                        f"No ACK observed within {ack_window_s:.1f} seconds; "
                        "still listening for the completion confirmation"
                    )
                    remaining = max(
                        0.1,
                        timeout_s - (time.monotonic() - started),
                    )
                    completed = client.wait_for_type(
                        MessageType.COMPLETED,
                        remaining,
                        name=completed_name,
                    )
                    log(completed.raw)
                    log(
                        "Command completed; the separate ACK was not observed"
                    )
                    return

                log(first.raw)

                if first.message_type is MessageType.COMPLETED:
                    log(
                        "COMPLETED arrived before, or instead of, the ACK; "
                        "the command is treated as finished"
                    )
                    return

                remaining = max(
                    0.1,
                    timeout_s - (time.monotonic() - started),
                )
                completed = client.wait_for_type(
                    MessageType.COMPLETED,
                    remaining,
                    name=completed_name,
                )
                log(completed.raw)
            except Exception:
                self._log_serial_diagnostics(
                    client,
                    history_mark,
                    log,
                )
                raise

    @staticmethod
    def _log_serial_diagnostics(
        client: SerialClient,
        history_mark: int,
        log: LogCallback,
    ) -> None:
        log(f"Serial diagnostics: {client.diagnostic_summary()}")
        messages = client.history_since(history_mark)[-12:]

        if messages:
            log("ESP32 lines received after command:")
            for message in messages:
                detail = (
                    f" [parse warning: {message.detail}]"
                    if message.name == "MALFORMED" and message.detail
                    else ""
                )
                log(f"<<< {message.raw}{detail}")
        else:
            raw_lines = client.recent_raw_lines(6)
            if raw_lines:
                log("No parsed response for this command. Recent raw lines:")
                for line in raw_lines:
                    log(f"<<< {line}")
            else:
                log("No serial bytes were received after the command")

    def _check_audio_device(self, device_index: int) -> None:
        sd.check_input_settings(
            device=device_index,
            channels=CONFIG.audio.capture_channels,
            dtype=CONFIG.audio.dtype,
            samplerate=CONFIG.audio.sample_rate,
        )

    def _require_serial(self) -> SerialClient:
        if self._serial is None or not self._serial.is_open:
            raise BackendError("ESP32 is not connected")
        return self._serial

    def _require_audio_device(self) -> int:
        if self._audio_device is None:
            raise BackendError("Audio device is not selected")
        return self._audio_device

    @staticmethod
    def _format_status(
        status: StatusSnapshot,
        device_config: ConfigSnapshot,
    ) -> str:
        return (
            f"State={status.acquisition_state}, "
            f"Fault={status.fault}, "
            f"Homed={status.rail_homed}, "
            f"Limit={status.limit_triggered}, "
            f"Position={status.rail_position}, "
            f"Ready={device_config.collection_ready}"
        )
