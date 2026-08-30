from __future__ import annotations

from time import perf_counter_ns

from models import (
    ActionType,
    ConfigSnapshot,
    EspEvent,
    EspEventType,
    MessageType,
    RunRequest,
    SerialMessage,
    StatusSnapshot,
)


class ProtocolError(ValueError):
    pass


def build_ping_command() -> str:
    return "PING"


def build_status_command() -> str:
    return "STATUS"


def build_stop_command() -> str:
    return "STOP"


def build_reset_fault_command() -> str:
    return "RESET_FAULT"


def build_limit_read_command() -> str:
    return "LIMIT,READ"


def build_home_command() -> str:
    return "HOME"


def build_goto_command(wheel_index: int) -> str:
    _validate_wheel_index(wheel_index)
    return f"GOTO,{wheel_index}"


def build_scan_command(direction: str) -> str:
    return f"SCAN,{_normalise_scan_direction(direction)}"


def build_probe_command(direction: str, amplitude: int) -> str:
    direction = _normalise_scan_direction(direction)
    amplitude = _validate_probe_amplitude(amplitude)
    return f"PROBE,{direction},{amplitude}"


def build_wide_probe_command(direction: str, amplitude: int, cycles: int) -> str:
    direction = _normalise_scan_direction(direction)
    amplitude = _validate_wide_probe_amplitude(amplitude)
    cycles = _validate_wide_probe_cycles(cycles)
    return f"WIDE_PROBE,{direction},{amplitude},{cycles}"


def build_wheel_jog_command(
    direction: str,
    steps: int,
) -> str:
    direction = _normalise_scan_direction(direction)
    steps = _validate_steps(steps)

    return f"JOG,WHEEL,{direction},{steps}"


def build_rail_jog_command(
    direction: str,
    steps: int,
) -> str:
    direction = _normalise_rail_direction(direction)
    steps = _validate_steps(steps)

    return f"JOG,RAIL,{direction},{steps}"


def build_servo_up_command() -> str:
    return "SERVO,UP"


def build_servo_down_command() -> str:
    return "SERVO,DOWN"


def build_servo_angle_command(angle: int) -> str:
    if angle not in range(181):
        raise ProtocolError("Servo angle must be between 0 and 180")

    return f"SERVO,ANGLE,{angle}"


def build_prepare_command(
    request: RunRequest,
    *,
    reuse_contact: bool = False,
) -> str:
    _validate_run_id(request.run_id)
    _validate_wheel_index(request.wheel_index)

    direction = _normalise_scan_direction(request.direction)

    if request.action_type == ActionType.PROBE.value:
        amplitude = _validate_probe_amplitude(request.probe_amplitude)
        return (
            f"PREPARE,{request.run_id},{request.wheel_index},"
            f"PROBE,{direction},{amplitude}"
        )

    if request.action_type == ActionType.WIDE_PROBE.value:
        amplitude = _validate_wide_probe_amplitude(request.probe_amplitude)
        cycles = _validate_wide_probe_cycles(request.probe_cycles)
        return (
            f"PREPARE,{request.run_id},{request.wheel_index},"
            f"WIDE_PROBE,{direction},{amplitude},{cycles}"
        )

    if request.action_type == ActionType.BINDING_SWEEP.value:
        return (
            f"PREPARE,{request.run_id},{request.wheel_index},"
            f"SWEEP,{direction}"
        )

    if request.action_type == ActionType.BINDING_REFERENCE_SWEEP.value:
        return (
            f"PREPARE,{request.run_id},{request.wheel_index},"
            f"REFERENCE_SWEEP,{direction}"
        )

    # Digit Scan uses an explicit runtime step count.  REUSE_CONTACT tells
    # the upgraded firmware that the rail is already on this wheel and the
    # drive head was intentionally left down after the previous candidate.
    command = (
        f"PREPARE,{request.run_id},{request.wheel_index},"
        f"DIGIT,{direction},{int(request.digit_steps)}"
    )
    if reuse_contact:
        command += ",REUSE_CONTACT"
    return command


def build_recording_command(run_id: str) -> str:
    _validate_run_id(run_id)
    return f"RECORDING,{run_id}"


def parse_message(
    raw: str,
    pc_time_ns: int | None = None,
) -> SerialMessage:
    line = raw.strip()

    if not line:
        raise ProtocolError("Empty serial message")

    received_at_ns = (
        perf_counter_ns()
        if pc_time_ns is None
        else pc_time_ns
    )

    tokens = [token.strip() for token in line.split(",")]
    message_name = tokens[0].upper()

    if message_name == "SYSTEM":
        _require_minimum_tokens(tokens, 2, line)

        return SerialMessage(
            message_type=MessageType.SYSTEM,
            raw=line,
            pc_time_ns=received_at_ns,
            name=tokens[1].upper(),
            values=tuple(tokens[2:]),
        )

    if message_name == "CONFIG":
        return _parse_config(
            tokens,
            line,
            received_at_ns,
        )

    if message_name == "ACK":
        _require_minimum_tokens(tokens, 2, line)

        name = tokens[1].upper()
        values = tuple(tokens[2:])
        run_id = values[0] if values else ""

        return SerialMessage(
            message_type=MessageType.ACK,
            raw=line,
            pc_time_ns=received_at_ns,
            name=name,
            run_id=run_id,
            detail=",".join(values),
            values=values,
        )

    if message_name == "COMPLETED":
        _require_token_count(tokens, 2, line)

        return SerialMessage(
            message_type=MessageType.COMPLETED,
            raw=line,
            pc_time_ns=received_at_ns,
            name=tokens[1].upper(),
        )

    if message_name == "STATE":
        _require_token_count(tokens, 2, line)

        return SerialMessage(
            message_type=MessageType.STATE,
            raw=line,
            pc_time_ns=received_at_ns,
            state=tokens[1].upper(),
        )

    if message_name == "READY_TO_RECORD":
        _require_token_count(tokens, 2, line)

        return SerialMessage(
            message_type=MessageType.READY_TO_RECORD,
            raw=line,
            pc_time_ns=received_at_ns,
            run_id=tokens[1],
        )

    if message_name == "DONE":
        _require_token_count(tokens, 2, line)

        return SerialMessage(
            message_type=MessageType.DONE,
            raw=line,
            pc_time_ns=received_at_ns,
            run_id=tokens[1],
        )

    if message_name == "ERROR":
        _require_minimum_tokens(tokens, 2, line)

        return SerialMessage(
            message_type=MessageType.ERROR,
            raw=line,
            pc_time_ns=received_at_ns,
            fault=tokens[1].upper(),
            detail=",".join(tokens[2:]),
            values=tuple(tokens[2:]),
        )

    if message_name == "STATUS":
        return _parse_status(
            tokens,
            line,
            received_at_ns,
        )

    if message_name == "LIMIT":
        return _parse_limit(
            tokens,
            line,
            received_at_ns,
        )

    if message_name == "EVENT":
        return _parse_event(
            tokens,
            line,
            received_at_ns,
        )

    if message_name == "DEBUG":
        return SerialMessage(
            message_type=MessageType.DEBUG,
            raw=line,
            pc_time_ns=received_at_ns,
            detail=",".join(tokens[1:]),
            values=tuple(tokens[1:]),
        )

    return SerialMessage(
        message_type=MessageType.UNKNOWN,
        raw=line,
        pc_time_ns=received_at_ns,
        name=message_name,
        values=tuple(tokens[1:]),
    )


def _parse_config(
    tokens: list[str],
    raw: str,
    pc_time_ns: int,
) -> SerialMessage:
    values = _parse_key_value_pairs(tokens, raw)

    required = {
        "SERVO",
        "WHEEL",
        "RAIL",
        "LIMIT",
        "AUTO",
    }

    if not required.issubset(values):
        raise ProtocolError(
            f"Missing CONFIG values: {raw}"
        )

    snapshot = ConfigSnapshot(
        servo_configured=_parse_bool(values["SERVO"]),
        wheel_configured=_parse_bool(values["WHEEL"]),
        rail_configured=_parse_bool(values["RAIL"]),
        limit_verified=_parse_bool(values["LIMIT"]),
        auto_enabled=_parse_bool(values["AUTO"]),
    )

    return SerialMessage(
        message_type=MessageType.CONFIG,
        raw=raw,
        pc_time_ns=pc_time_ns,
        config=snapshot,
    )


def _parse_status(
    tokens: list[str],
    raw: str,
    pc_time_ns: int,
) -> SerialMessage:
    _require_token_count(tokens, 9, raw)

    snapshot = StatusSnapshot(
        acquisition_state=tokens[1].upper(),
        fault=tokens[2].upper(),
        wheel_busy=_parse_bool(tokens[3]),
        rail_busy=_parse_bool(tokens[4]),
        rail_homed=_parse_bool(tokens[5]),
        servo_busy=_parse_bool(tokens[6]),
        limit_triggered=_parse_bool(tokens[7]),
        rail_position=_parse_int(
            tokens[8],
            "rail position",
        ),
    )

    return SerialMessage(
        message_type=MessageType.STATUS,
        raw=raw,
        pc_time_ns=pc_time_ns,
        state=snapshot.acquisition_state,
        fault=snapshot.fault,
        status=snapshot,
    )


def _parse_limit(
    tokens: list[str],
    raw: str,
    pc_time_ns: int,
) -> SerialMessage:
    values = _parse_key_value_pairs(tokens, raw)

    if "RAW" not in values or "STABLE" not in values:
        raise ProtocolError(
            f"Missing LIMIT values: {raw}"
        )

    return SerialMessage(
        message_type=MessageType.LIMIT,
        raw=raw,
        pc_time_ns=pc_time_ns,
        values=(
            values["RAW"],
            values["STABLE"],
        ),
    )


def _parse_event(
    tokens: list[str],
    raw: str,
    pc_time_ns: int,
) -> SerialMessage:
    _require_token_count(tokens, 6, raw)

    run_id = tokens[1]
    _validate_run_id(run_id)

    try:
        event_type = EspEventType(tokens[2].upper())
    except ValueError as exc:
        raise ProtocolError(
            f"Unknown event type: {tokens[2]}"
        ) from exc

    event = EspEvent(
        run_id=run_id,
        event_type=event_type,
        esp_time_us=_parse_int(
            tokens[3],
            "ESP timestamp",
        ),
        digit_index=_parse_int(
            tokens[4],
            "digit index",
        ),
        step=_parse_int(
            tokens[5],
            "step",
        ),
        pc_time_ns=pc_time_ns,
        raw_message=raw,
    )

    if event.esp_time_us < 0:
        raise ProtocolError(
            "ESP timestamp cannot be negative"
        )

    if event.digit_index not in range(32):
        raise ProtocolError(
            "Event index must be between 0 and 31"
        )

    if event.step < 0:
        raise ProtocolError("Step cannot be negative")

    return SerialMessage(
        message_type=MessageType.EVENT,
        raw=raw,
        pc_time_ns=pc_time_ns,
        run_id=run_id,
        name=event_type.value,
        event=event,
    )


def _parse_key_value_pairs(
    tokens: list[str],
    raw: str,
) -> dict[str, str]:
    if len(tokens) < 3 or len(tokens[1:]) % 2 != 0:
        raise ProtocolError(
            f"Invalid key-value message: {raw}"
        )

    values: dict[str, str] = {}

    for index in range(1, len(tokens), 2):
        key = tokens[index].upper()
        value = tokens[index + 1]

        if not key or key in values:
            raise ProtocolError(
                f"Invalid or repeated key: {raw}"
            )

        values[key] = value

    return values


def _parse_bool(value: str) -> bool:
    if value == "1":
        return True

    if value == "0":
        return False

    raise ProtocolError(
        f"Boolean value must be 0 or 1: {value}"
    )


def _parse_int(
    value: str,
    field_name: str,
) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ProtocolError(
            f"Invalid {field_name}: {value}"
        ) from exc


def _validate_run_id(run_id: str) -> None:
    if not run_id:
        raise ProtocolError("run_id cannot be empty")

    if len(run_id) >= 24:
        raise ProtocolError(
            "run_id must contain fewer than 24 characters"
        )

    for character in run_id:
        if not (
            character.isalnum()
            or character in {"_", "-"}
        ):
            raise ProtocolError(
                "run_id may only contain letters, "
                "numbers, underscores and hyphens"
            )


def _validate_wheel_index(wheel_index: int) -> None:
    if wheel_index not in range(1, 5):
        raise ProtocolError(
            "wheel_index must be between 1 and 4"
        )


def _validate_steps(steps: int) -> int:
    if steps <= 0:
        raise ProtocolError("steps must be positive")

    return steps


def _validate_probe_amplitude(amplitude: int) -> int:
    if amplitude not in range(5, 61):
        raise ProtocolError(
            "Probe amplitude must be between 5 and 60 steps"
        )
    return amplitude



def _validate_wide_probe_amplitude(amplitude: int) -> int:
    if amplitude not in range(20, 81):
        raise ProtocolError(
            "Wide probe amplitude must be between 20 and 80 steps"
        )
    return amplitude


def _validate_wide_probe_cycles(cycles: int) -> int:
    if cycles not in range(1, 9):
        raise ProtocolError("Wide probe cycles must be between 1 and 8")
    return cycles

def _normalise_scan_direction(
    direction: str,
) -> str:
    value = direction.upper()

    if value not in {"CW", "CCW"}:
        raise ProtocolError(
            "Scan direction must be CW or CCW"
        )

    return value


def _normalise_rail_direction(
    direction: str,
) -> str:
    value = direction.upper()

    if value in {"FORWARD", "FWD"}:
        return "FWD"

    if value in {"REVERSE", "REV"}:
        return "REV"

    raise ProtocolError(
        "Rail direction must be FWD or REV"
    )


def _require_token_count(
    tokens: list[str],
    expected: int,
    raw: str,
) -> None:
    if len(tokens) != expected:
        raise ProtocolError(
            f"Expected {expected} fields: {raw}"
        )


def _require_minimum_tokens(
    tokens: list[str],
    minimum: int,
    raw: str,
) -> None:
    if len(tokens) < minimum:
        raise ProtocolError(
            f"Expected at least {minimum} fields: {raw}"
        )
