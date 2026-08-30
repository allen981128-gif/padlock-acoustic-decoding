#pragma once

#include <Arduino.h>

constexpr size_t RUN_ID_SIZE = 24;

enum class StepDirection : uint8_t
{
    FORWARD,
    REVERSE
};

enum class ScanDirection : uint8_t
{
    CW,
    CCW
};

enum class WheelActionType : uint8_t
{
    DIGIT_MOVE,
    PROBE,
    WIDE_PROBE,
    BINDING_SWEEP,
    BINDING_REFERENCE_SWEEP
};

enum class AcquisitionState : uint8_t
{
    BOOT,
    IDLE,

    HOMING_FAST,
    HOMING_BACKOFF,
    HOMING_SLOW,

    MOVING_TO_WHEEL,
    RAIL_SETTLING,
    LOWERING_SERVO,
    WAITING_FOR_RECORDING,

    SCANNING,
    PROBING,
    RAISING_SERVO,

    DONE,
    ABORTING,
    FAULT
};

enum class CommandType : uint8_t
{
    NONE,

    PING,
    STATUS,
    STOP,
    RESET_FAULT,

    JOG_WHEEL,
    JOG_RAIL,
    PROBE_WHEEL,

    SERVO_UP,
    SERVO_DOWN,
    SERVO_ANGLE,

    LIMIT_READ,

    HOME,
    GOTO_WHEEL,
    SCAN_WHEEL,

    PREPARE,
    RECORDING
};

enum class FaultCode : uint8_t
{
    NONE,

    CALIBRATION_REQUIRED,
    LIMIT_NOT_VERIFIED,
    AUTO_ACQUISITION_DISABLED,

    INVALID_COMMAND,
    INVALID_ARGUMENT,
    INVALID_STATE,

    RUN_ID_MISMATCH,
    SERIAL_BUFFER_OVERFLOW,

    RAIL_NOT_HOMED,
    RAIL_RANGE_ERROR,
    LIMIT_UNEXPECTED,

    HOME_TIMEOUT,
    RAIL_MOVE_TIMEOUT,
    SCAN_TIMEOUT,
    RECORDING_WAIT_TIMEOUT,

    STEP_COUNT_ERROR
};

enum class WheelEventType : uint8_t
{
    NONE,
    SCAN_START,
    DIGIT_BOUNDARY,
    SCAN_END,
    PROBE_START,
    PROBE_SEGMENT,
    PROBE_END,
    WIDE_PROBE_START,
    WIDE_PROBE_SEGMENT,
    WIDE_PROBE_END
};

struct Command
{
    CommandType type = CommandType::NONE;

    char runId[RUN_ID_SIZE] = {};

    uint8_t wheelIndex = 0;
    uint32_t steps = 0;
    bool reuseContact = false;
    uint32_t probeAmplitude = 0;
    uint8_t probeCycles = 0;
    int16_t servoAngle = 0;

    StepDirection stepDirection = StepDirection::FORWARD;
    ScanDirection scanDirection = ScanDirection::CW;
    WheelActionType wheelAction = WheelActionType::DIGIT_MOVE;
};

struct WheelEvent
{
    WheelEventType type = WheelEventType::NONE;

    uint8_t digitIndex = 0;
    uint32_t step = 0;
    int64_t timestampUs = 0;
};
