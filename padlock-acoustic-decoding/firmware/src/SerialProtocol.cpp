#include "SerialProtocol.h"

#include <ctype.h>
#include <limits.h>
#include <string.h>

#include "Calibration.h"
#include "FeatureFlags.h"

namespace
{
char* trimToken(char* token)
{
    while (*token != '\0' &&
           isspace(static_cast<unsigned char>(*token)))
    {
        ++token;
    }

    char* end = token + strlen(token);

    while (end > token &&
           isspace(
               static_cast<unsigned char>(*(end - 1))
           ))
    {
        --end;
    }

    *end = '\0';
    return token;
}
}

SerialProtocol::SerialProtocol(Stream& stream)
    : stream_(stream)
{
}

void SerialProtocol::begin()
{
    clearReceiveBuffer();
    clearCommandQueue();
}

void SerialProtocol::update()
{
    while (stream_.available() > 0)
    {
        const char value =
            static_cast<char>(stream_.read());

        processByte(value);
    }
}

bool SerialProtocol::takeCommand(Command& command)
{
    if (commandCount_ == 0)
    {
        return false;
    }

    command = commandQueue_[commandHead_];

    commandHead_ =
        (commandHead_ + 1) % COMMAND_QUEUE_SIZE;

    --commandCount_;
    return true;
}

void SerialProtocol::sendSystemReady()
{
    stream_.println("SYSTEM,READY");
}

void SerialProtocol::sendAck(const char* command)
{
    stream_.print("ACK,");
    stream_.println(command);
}

void SerialProtocol::sendAck(
    const char* command,
    const char* value
)
{
    stream_.print("ACK,");
    stream_.print(command);
    stream_.print(",");
    stream_.println(value);
}

void SerialProtocol::sendCompleted(
    const char* operation
)
{
    stream_.print("COMPLETED,");
    stream_.println(operation);
}

void SerialProtocol::sendState(
    AcquisitionState state
)
{
    stream_.print("STATE,");
    stream_.println(stateText(state));
}

void SerialProtocol::sendError(FaultCode code)
{
    stream_.print("ERROR,");
    stream_.println(faultText(code));
}

void SerialProtocol::sendError(
    FaultCode code,
    const char* detail
)
{
    stream_.print("ERROR,");
    stream_.print(faultText(code));

    if (detail != nullptr && detail[0] != '\0')
    {
        stream_.print(",");
        stream_.print(detail);
    }

    stream_.println();
}

void SerialProtocol::sendReadyToRecord(
    const char* runId
)
{
    stream_.print("READY_TO_RECORD,");
    stream_.println(runId);
}

void SerialProtocol::sendDone(const char* runId)
{
    stream_.print("DONE,");
    stream_.println(runId);
}

void SerialProtocol::sendWheelEvent(
    const char* runId,
    const WheelEvent& event
)
{
    stream_.print("EVENT,");
    stream_.print(runId);
    stream_.print(",");
    stream_.print(wheelEventText(event.type));
    stream_.print(",");
    stream_.print(
        static_cast<long long>(event.timestampUs)
    );
    stream_.print(",");
    stream_.print(event.digitIndex);
    stream_.print(",");
    stream_.println(event.step);
}

void SerialProtocol::sendLimitState(
    bool rawTriggered,
    bool stableTriggered
)
{
    stream_.print("LIMIT,RAW,");
    stream_.print(rawTriggered ? 1 : 0);
    stream_.print(",STABLE,");
    stream_.println(stableTriggered ? 1 : 0);
}

void SerialProtocol::sendStatus(
    AcquisitionState state,
    FaultCode fault,
    bool wheelBusy,
    bool railBusy,
    bool railHomed,
    bool servoBusy,
    bool limitTriggered,
    long railPosition
)
{
    stream_.print("STATUS,");
    stream_.print(stateText(state));
    stream_.print(",");
    stream_.print(faultText(fault));
    stream_.print(",");
    stream_.print(wheelBusy ? 1 : 0);
    stream_.print(",");
    stream_.print(railBusy ? 1 : 0);
    stream_.print(",");
    stream_.print(railHomed ? 1 : 0);
    stream_.print(",");
    stream_.print(servoBusy ? 1 : 0);
    stream_.print(",");
    stream_.print(limitTriggered ? 1 : 0);
    stream_.print(",");
    stream_.println(railPosition);
}

void SerialProtocol::sendConfigStatus(
    bool servoConfigured,
    bool wheelConfigured,
    bool railConfigured,
    bool limitVerified,
    bool autoEnabled
)
{
    stream_.print("CONFIG,SERVO,");
    stream_.print(servoConfigured ? 1 : 0);
    stream_.print(",WHEEL,");
    stream_.print(wheelConfigured ? 1 : 0);
    stream_.print(",RAIL,");
    stream_.print(railConfigured ? 1 : 0);
    stream_.print(",LIMIT,");
    stream_.print(limitVerified ? 1 : 0);
    stream_.print(",AUTO,");
    stream_.println(autoEnabled ? 1 : 0);
}

void SerialProtocol::sendDebug(const char* message)
{
    if (!FeatureFlags::ENABLE_DEBUG_OUTPUT)
    {
        return;
    }

    stream_.print("DEBUG,");
    stream_.println(message);
}

void SerialProtocol::processByte(char value)
{
    if (value == '\r')
    {
        return;
    }

    if (value == Communication::LINE_TERMINATOR)
    {
        if (discardCurrentLine_)
        {
            sendError(
                FaultCode::SERIAL_BUFFER_OVERFLOW
            );

            clearReceiveBuffer();
            return;
        }

        if (receiveLength_ == 0)
        {
            return;
        }

        receiveBuffer_[receiveLength_] = '\0';
        processLine();
        clearReceiveBuffer();
        return;
    }

    if (discardCurrentLine_)
    {
        return;
    }

    if (receiveLength_ >=
        Communication::SERIAL_RX_BUFFER_SIZE - 1)
    {
        discardCurrentLine_ = true;
        return;
    }

    receiveBuffer_[receiveLength_] = value;
    ++receiveLength_;
}

void SerialProtocol::processLine()
{
    Command command;

    if (!parseLine(receiveBuffer_, command))
    {
        sendError(FaultCode::INVALID_COMMAND);
        return;
    }

    if (!pushCommand(command))
    {
        sendError(
            FaultCode::INVALID_STATE,
            "COMMAND_QUEUE_FULL"
        );
    }
}

bool SerialProtocol::parseLine(
    char* line,
    Command& command
)
{
    char* tokens[MAX_TOKENS] = {};
    uint8_t tokenCount = 0;

    char* context = nullptr;
    char* token = strtok_r(line, ",", &context);

    while (token != nullptr)
    {
        if (tokenCount >= MAX_TOKENS)
        {
            return false;
        }

        tokens[tokenCount] = trimToken(token);

        if (tokens[tokenCount][0] == '\0')
        {
            return false;
        }

        ++tokenCount;
        token = strtok_r(nullptr, ",", &context);
    }

    if (tokenCount == 0)
    {
        return false;
    }

    if (tokenEquals(tokens[0], "PING") &&
        tokenCount == 1)
    {
        command.type = CommandType::PING;
        return true;
    }

    if (tokenEquals(tokens[0], "STATUS") &&
        tokenCount == 1)
    {
        command.type = CommandType::STATUS;
        return true;
    }

    if (tokenEquals(tokens[0], "STOP") &&
        tokenCount == 1)
    {
        command.type = CommandType::STOP;
        return true;
    }

    if (tokenEquals(tokens[0], "RESET_FAULT") &&
        tokenCount == 1)
    {
        command.type = CommandType::RESET_FAULT;
        return true;
    }

    if (tokenEquals(tokens[0], "HOME") &&
        tokenCount == 1)
    {
        command.type = CommandType::HOME;
        return true;
    }

    if (tokenEquals(tokens[0], "GOTO") &&
        tokenCount == 2)
    {
        if (!parseWheelIndex(
                tokens[1],
                command.wheelIndex
            ))
        {
            return false;
        }

        command.type = CommandType::GOTO_WHEEL;
        return true;
    }

    if (tokenEquals(tokens[0], "SCAN") &&
        tokenCount == 2)
    {
        if (!parseScanDirection(
                tokens[1],
                command.scanDirection
            ))
        {
            return false;
        }

        command.type = CommandType::SCAN_WHEEL;
        return true;
    }

    if (tokenEquals(tokens[0], "PROBE") &&
        tokenCount == 3)
    {
        if (!parseScanDirection(
                tokens[1],
                command.scanDirection
            ) ||
            !parseUnsigned(
                tokens[2],
                command.probeAmplitude
            ) ||
            !Calibration::probeAmplitudeValid(
                command.probeAmplitude
            ))
        {
            return false;
        }

        command.type = CommandType::PROBE_WHEEL;
        command.wheelAction = WheelActionType::PROBE;
        return true;
    }

    if (tokenEquals(tokens[0], "LIMIT") &&
        tokenCount == 2 &&
        tokenEquals(tokens[1], "READ"))
    {
        command.type = CommandType::LIMIT_READ;
        return true;
    }

    if (tokenEquals(tokens[0], "SERVO"))
    {
        if (tokenCount == 2 &&
            tokenEquals(tokens[1], "UP"))
        {
            command.type = CommandType::SERVO_UP;
            return true;
        }

        if (tokenCount == 2 &&
            tokenEquals(tokens[1], "DOWN"))
        {
            command.type = CommandType::SERVO_DOWN;
            return true;
        }

        if (tokenCount == 3 &&
            tokenEquals(tokens[1], "ANGLE"))
        {
            if (!parseServoAngle(
                    tokens[2],
                    command.servoAngle
                ))
            {
                return false;
            }

            command.type =
                CommandType::SERVO_ANGLE;

            return true;
        }

        return false;
    }

    if (tokenEquals(tokens[0], "JOG") &&
        tokenCount == 4)
    {
        if (!parseUnsigned(
                tokens[3],
                command.steps
            ) ||
            command.steps == 0)
        {
            return false;
        }

        if (tokenEquals(tokens[1], "WHEEL"))
        {
            if (!parseScanDirection(
                    tokens[2],
                    command.scanDirection
                ))
            {
                return false;
            }

            command.type =
                CommandType::JOG_WHEEL;

            return true;
        }

        if (tokenEquals(tokens[1], "RAIL"))
        {
            if (!parseStepDirection(
                    tokens[2],
                    command.stepDirection
                ))
            {
                return false;
            }

            command.type =
                CommandType::JOG_RAIL;

            return true;
        }

        return false;
    }

    if (tokenEquals(tokens[0], "PREPARE"))
    {
        if (tokenCount < 4 || tokenCount > 7)
        {
            return false;
        }

        if (!copyRunId(
                command.runId,
                tokens[1]
            ) ||
            !parseWheelIndex(
                tokens[2],
                command.wheelIndex
            ))
        {
            return false;
        }

        // Legacy format: PREPARE,run_id,wheel,CW
        if (tokenCount == 4)
        {
            if (!parseScanDirection(
                    tokens[3],
                    command.scanDirection
                ))
            {
                return false;
            }

            command.wheelAction =
                WheelActionType::DIGIT_MOVE;
            command.type = CommandType::PREPARE;
            return true;
        }

        if (tokenEquals(tokens[3], "DIGIT") &&
            tokenCount >= 5 &&
            tokenCount <= 7)
        {
            if (!parseScanDirection(
                    tokens[4],
                    command.scanDirection
                ))
            {
                return false;
            }

            command.steps =
                Calibration::WHEEL_STEPS_PER_DIGIT;

            if (tokenCount >= 6)
            {
                if (!parseUnsigned(
                        tokens[5],
                        command.steps
                    ) ||
                    command.steps == 0 ||
                    command.steps >
                        Calibration::MAX_WHEEL_JOG_STEPS)
                {
                    return false;
                }
            }

            if (tokenCount == 7)
            {
                if (!tokenEquals(
                        tokens[6],
                        "REUSE_CONTACT"
                    ))
                {
                    return false;
                }
                command.reuseContact = true;
            }

            command.wheelAction =
                WheelActionType::DIGIT_MOVE;
            command.type = CommandType::PREPARE;
            return true;
        }

        if (tokenEquals(tokens[3], "PROBE") &&
            tokenCount == 6)
        {
            if (!parseScanDirection(
                    tokens[4],
                    command.scanDirection
                ) ||
                !parseUnsigned(
                    tokens[5],
                    command.probeAmplitude
                ) ||
                !Calibration::probeAmplitudeValid(
                    command.probeAmplitude
                ))
            {
                return false;
            }

            command.wheelAction = WheelActionType::PROBE;
            command.type = CommandType::PREPARE;
            return true;
        }

        if ((tokenEquals(tokens[3], "WIDE_PROBE") ||
             tokenEquals(tokens[3], "WIDE_LOCAL_PROBE")) &&
            tokenCount == 7)
        {
            uint32_t cycles = 0;
            if (!parseScanDirection(
                    tokens[4],
                    command.scanDirection
                ) ||
                !parseUnsigned(
                    tokens[5],
                    command.probeAmplitude
                ) ||
                !parseUnsigned(tokens[6], cycles) ||
                cycles > 255 ||
                !Calibration::wideProbeValid(
                    command.probeAmplitude,
                    static_cast<uint8_t>(cycles)
                ))
            {
                return false;
            }

            command.probeCycles = static_cast<uint8_t>(cycles);
            command.wheelAction = WheelActionType::WIDE_PROBE;
            command.type = CommandType::PREPARE;
            return true;
        }

        if ((tokenEquals(tokens[3], "SWEEP") ||
             tokenEquals(tokens[3], "BINDING_SWEEP")) &&
            tokenCount == 5)
        {
            if (!parseScanDirection(
                    tokens[4],
                    command.scanDirection
                ))
            {
                return false;
            }

            command.wheelAction =
                WheelActionType::BINDING_SWEEP;
            command.type = CommandType::PREPARE;
            return true;
        }

        if ((tokenEquals(tokens[3], "REFERENCE_SWEEP") ||
             tokenEquals(tokens[3], "BINDING_REFERENCE")) &&
            tokenCount == 5)
        {
            if (!parseScanDirection(
                    tokens[4],
                    command.scanDirection
                ) ||
                command.scanDirection != ScanDirection::CCW)
            {
                return false;
            }

            command.wheelAction =
                WheelActionType::BINDING_REFERENCE_SWEEP;
            command.type = CommandType::PREPARE;
            return true;
        }

        return false;
    }

    if (tokenEquals(tokens[0], "RECORDING") &&
        tokenCount == 2)
    {
        if (!copyRunId(
                command.runId,
                tokens[1]
            ))
        {
            return false;
        }

        command.type = CommandType::RECORDING;
        return true;
    }

    return false;
}

bool SerialProtocol::pushCommand(
    const Command& command
)
{
    if (commandCount_ >= COMMAND_QUEUE_SIZE)
    {
        return false;
    }

    commandQueue_[commandTail_] = command;

    commandTail_ =
        (commandTail_ + 1) % COMMAND_QUEUE_SIZE;

    ++commandCount_;
    return true;
}

void SerialProtocol::clearReceiveBuffer()
{
    receiveLength_ = 0;
    discardCurrentLine_ = false;
    receiveBuffer_[0] = '\0';
}

void SerialProtocol::clearCommandQueue()
{
    commandHead_ = 0;
    commandTail_ = 0;
    commandCount_ = 0;
}

bool SerialProtocol::tokenEquals(
    const char* left,
    const char* right
)
{
    if (left == nullptr || right == nullptr)
    {
        return false;
    }

    while (*left != '\0' && *right != '\0')
    {
        const char leftValue =
            static_cast<char>(
                toupper(
                    static_cast<unsigned char>(*left)
                )
            );

        const char rightValue =
            static_cast<char>(
                toupper(
                    static_cast<unsigned char>(*right)
                )
            );

        if (leftValue != rightValue)
        {
            return false;
        }

        ++left;
        ++right;
    }

    return *left == '\0' && *right == '\0';
}

bool SerialProtocol::parseUnsigned(
    const char* token,
    uint32_t& value
)
{
    if (token == nullptr || token[0] == '\0')
    {
        return false;
    }

    uint64_t result = 0;

    for (size_t i = 0; token[i] != '\0'; ++i)
    {
        if (!isdigit(
                static_cast<unsigned char>(token[i])
            ))
        {
            return false;
        }

        result =
            result * 10 +
            static_cast<uint64_t>(
                token[i] - '0'
            );

        if (result > UINT32_MAX)
        {
            return false;
        }
    }

    value = static_cast<uint32_t>(result);
    return true;
}

bool SerialProtocol::parseWheelIndex(
    const char* token,
    uint8_t& wheelIndex
)
{
    uint32_t value = 0;

    if (!parseUnsigned(token, value))
    {
        return false;
    }

    if (value < 1 ||
        value > Calibration::LOCK_WHEEL_COUNT)
    {
        return false;
    }

    wheelIndex = static_cast<uint8_t>(value);
    return true;
}

bool SerialProtocol::parseServoAngle(
    const char* token,
    int16_t& angle
)
{
    uint32_t value = 0;

    if (!parseUnsigned(token, value) ||
        value > 180)
    {
        return false;
    }

    angle = static_cast<int16_t>(value);
    return true;
}

bool SerialProtocol::parseStepDirection(
    const char* token,
    StepDirection& direction
)
{
    if (tokenEquals(token, "FWD") ||
        tokenEquals(token, "FORWARD"))
    {
        direction = StepDirection::FORWARD;
        return true;
    }

    if (tokenEquals(token, "REV") ||
        tokenEquals(token, "REVERSE"))
    {
        direction = StepDirection::REVERSE;
        return true;
    }

    return false;
}

bool SerialProtocol::parseScanDirection(
    const char* token,
    ScanDirection& direction
)
{
    if (tokenEquals(token, "CW"))
    {
        direction = ScanDirection::CW;
        return true;
    }

    if (tokenEquals(token, "CCW"))
    {
        direction = ScanDirection::CCW;
        return true;
    }

    return false;
}

bool SerialProtocol::copyRunId(
    char destination[RUN_ID_SIZE],
    const char* source
)
{
    if (source == nullptr || source[0] == '\0')
    {
        return false;
    }

    const size_t length = strlen(source);

    if (length >= RUN_ID_SIZE)
    {
        return false;
    }

    for (size_t i = 0; i < length; ++i)
    {
        const char value = source[i];

        if (!isalnum(
                static_cast<unsigned char>(value)
            ) &&
            value != '_' &&
            value != '-')
        {
            return false;
        }
    }

    memcpy(destination, source, length + 1);
    return true;
}

const char* SerialProtocol::stateText(
    AcquisitionState state
)
{
    switch (state)
    {
        case AcquisitionState::BOOT:
            return "BOOT";

        case AcquisitionState::IDLE:
            return "IDLE";

        case AcquisitionState::HOMING_FAST:
            return "HOMING_FAST";

        case AcquisitionState::HOMING_BACKOFF:
            return "HOMING_BACKOFF";

        case AcquisitionState::HOMING_SLOW:
            return "HOMING_SLOW";

        case AcquisitionState::MOVING_TO_WHEEL:
            return "MOVING_TO_WHEEL";

        case AcquisitionState::RAIL_SETTLING:
            return "RAIL_SETTLING";

        case AcquisitionState::LOWERING_SERVO:
            return "LOWERING_SERVO";

        case AcquisitionState::WAITING_FOR_RECORDING:
            return "WAITING_FOR_RECORDING";

        case AcquisitionState::SCANNING:
            return "SCANNING";

        case AcquisitionState::PROBING:
            return "PROBING";

        case AcquisitionState::RAISING_SERVO:
            return "RAISING_SERVO";

        case AcquisitionState::DONE:
            return "DONE";

        case AcquisitionState::ABORTING:
            return "ABORTING";

        case AcquisitionState::FAULT:
            return "FAULT";
    }

    return "UNKNOWN";
}

const char* SerialProtocol::faultText(
    FaultCode code
)
{
    switch (code)
    {
        case FaultCode::NONE:
            return "NONE";

        case FaultCode::CALIBRATION_REQUIRED:
            return "CALIBRATION_REQUIRED";

        case FaultCode::LIMIT_NOT_VERIFIED:
            return "LIMIT_NOT_VERIFIED";

        case FaultCode::AUTO_ACQUISITION_DISABLED:
            return "AUTO_ACQUISITION_DISABLED";

        case FaultCode::INVALID_COMMAND:
            return "INVALID_COMMAND";

        case FaultCode::INVALID_ARGUMENT:
            return "INVALID_ARGUMENT";

        case FaultCode::INVALID_STATE:
            return "INVALID_STATE";

        case FaultCode::RUN_ID_MISMATCH:
            return "RUN_ID_MISMATCH";

        case FaultCode::SERIAL_BUFFER_OVERFLOW:
            return "SERIAL_BUFFER_OVERFLOW";

        case FaultCode::RAIL_NOT_HOMED:
            return "RAIL_NOT_HOMED";

        case FaultCode::RAIL_RANGE_ERROR:
            return "RAIL_RANGE_ERROR";

        case FaultCode::LIMIT_UNEXPECTED:
            return "LIMIT_UNEXPECTED";

        case FaultCode::HOME_TIMEOUT:
            return "HOME_TIMEOUT";

        case FaultCode::RAIL_MOVE_TIMEOUT:
            return "RAIL_MOVE_TIMEOUT";

        case FaultCode::SCAN_TIMEOUT:
            return "SCAN_TIMEOUT";

        case FaultCode::RECORDING_WAIT_TIMEOUT:
            return "RECORDING_WAIT_TIMEOUT";

        case FaultCode::STEP_COUNT_ERROR:
            return "STEP_COUNT_ERROR";
    }

    return "UNKNOWN";
}

const char* SerialProtocol::wheelEventText(
    WheelEventType type
)
{
    switch (type)
    {
        case WheelEventType::SCAN_START:
            return "SCAN_START";

        case WheelEventType::DIGIT_BOUNDARY:
            return "DIGIT_BOUNDARY";

        case WheelEventType::SCAN_END:
            return "SCAN_END";

        case WheelEventType::PROBE_START:
            return "PROBE_START";

        case WheelEventType::PROBE_SEGMENT:
            return "PROBE_SEGMENT";

        case WheelEventType::PROBE_END:
            return "PROBE_END";

        case WheelEventType::WIDE_PROBE_START:
            return "WIDE_PROBE_START";

        case WheelEventType::WIDE_PROBE_SEGMENT:
            return "WIDE_PROBE_SEGMENT";

        case WheelEventType::WIDE_PROBE_END:
            return "WIDE_PROBE_END";

        case WheelEventType::NONE:
            return "NONE";
    }

    return "UNKNOWN";
}