#pragma once

#include <Arduino.h>

#include "HardwareConfig.h"
#include "SystemTypes.h"

class SerialProtocol
{
public:
    explicit SerialProtocol(Stream& stream);

    void begin();
    void update();

    bool takeCommand(Command& command);

    void sendSystemReady();

    void sendAck(const char* command);
    void sendAck(
        const char* command,
        const char* value
    );

    void sendCompleted(const char* operation);

    void sendState(AcquisitionState state);

    void sendError(FaultCode code);
    void sendError(
        FaultCode code,
        const char* detail
    );

    void sendReadyToRecord(const char* runId);
    void sendDone(const char* runId);

    void sendWheelEvent(
        const char* runId,
        const WheelEvent& event
    );

    void sendLimitState(
        bool rawTriggered,
        bool stableTriggered
    );

    void sendStatus(
        AcquisitionState state,
        FaultCode fault,
        bool wheelBusy,
        bool railBusy,
        bool railHomed,
        bool servoBusy,
        bool limitTriggered,
        long railPosition
    );

    void sendConfigStatus(
        bool servoConfigured,
        bool wheelConfigured,
        bool railConfigured,
        bool limitVerified,
        bool autoEnabled
    );

    void sendDebug(const char* message);

private:
    static constexpr uint8_t COMMAND_QUEUE_SIZE = 8;
    static constexpr uint8_t MAX_TOKENS = 7;

    void processByte(char value);
    void processLine();

    bool parseLine(
        char* line,
        Command& command
    );

    bool pushCommand(const Command& command);

    void clearReceiveBuffer();
    void clearCommandQueue();

    static bool tokenEquals(
        const char* left,
        const char* right
    );

    static bool parseUnsigned(
        const char* token,
        uint32_t& value
    );

    static bool parseWheelIndex(
        const char* token,
        uint8_t& wheelIndex
    );

    static bool parseServoAngle(
        const char* token,
        int16_t& angle
    );

    static bool parseStepDirection(
        const char* token,
        StepDirection& direction
    );

    static bool parseScanDirection(
        const char* token,
        ScanDirection& direction
    );

    static bool copyRunId(
        char destination[RUN_ID_SIZE],
        const char* source
    );

    static const char* stateText(
        AcquisitionState state
    );

    static const char* faultText(
        FaultCode code
    );

    static const char* wheelEventText(
        WheelEventType type
    );

    Stream& stream_;

    char receiveBuffer_[
        Communication::SERIAL_RX_BUFFER_SIZE
    ] = {};

    size_t receiveLength_ = 0;
    bool discardCurrentLine_ = false;

    Command commandQueue_[COMMAND_QUEUE_SIZE];

    uint8_t commandHead_ = 0;
    uint8_t commandTail_ = 0;
    uint8_t commandCount_ = 0;
};