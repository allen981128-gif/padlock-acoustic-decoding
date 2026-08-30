#pragma once

#include <Arduino.h>

#include "SystemTypes.h"

class LimitSwitch;
class RailController;
class SafetyController;
class SerialProtocol;
class ServoLift;
class WheelController;

class AcquisitionFlow
{
public:
    AcquisitionFlow(
        WheelController& wheel,
        RailController& rail,
        ServoLift& servo,
        LimitSwitch& limitSwitch,
        SerialProtocol& protocol,
        SafetyController& safety
    );

    void begin();
    void update();

    AcquisitionState state() const;
    FaultCode faultCode() const;

    bool isIdle() const;

    const char* runId() const;
    uint8_t targetWheelIndex() const;
    ScanDirection scanDirection() const;

private:
    enum class ActiveOperation : uint8_t
    {
        NONE,
        WHEEL_JOG,
        RAIL_JOG,
        SERVO_MOVE,
        HOME,
        GOTO_WHEEL,
        MANUAL_SCAN,
        MANUAL_PROBE,
        AUTO_PREPARE,
        AUTO_SCAN,
        STOPPING
    };

    enum class PendingRailAction : uint8_t
    {
        NONE,
        HOME,
        GOTO_WHEEL
    };

    void processCommands();
    void handleCommand(const Command& command);

    void sendCurrentStatus();

    void updateSafety();
    void updateWheelEvents();
    void updateRailState();
    void updateCompletions();
    void updateTimeout();

    bool startPrepare(const Command& command);
    bool startRecording(const Command& command);

    bool queueRailAction(
        PendingRailAction action
    );

    bool startPendingRailAction();
    bool startRailHome();
    bool startRailMoveToTarget();

    bool startServoDown();
    bool startServoUp();
    bool startConfiguredWheelAction();
    uint32_t expectedWheelPulseCount() const;

    void handleRailCompleted();
    void handleWheelCompleted();
    void handleServoCompleted();

    bool canStartOperation() const;
    bool automaticReady() const;

    void completeManualOperation(
        const char* operation
    );

    void finishAutomaticRun();
    void enterFault(FaultCode code);

    void setState(AcquisitionState state);

    void setDeadline(uint32_t durationMs);
    void clearDeadline();
    bool deadlineExpired() const;

    bool runIdMatches(const char* value) const;
    void copyRunId(const char* value);
    void clearRun();

    static bool timeReached(
        uint32_t now,
        uint32_t target
    );

    WheelController& wheel_;
    RailController& rail_;
    ServoLift& servo_;
    LimitSwitch& limitSwitch_;
    SerialProtocol& protocol_;
    SafetyController& safety_;

    AcquisitionState state_ =
        AcquisitionState::BOOT;

    ActiveOperation activeOperation_ =
        ActiveOperation::NONE;

    PendingRailAction pendingRailAction_ =
        PendingRailAction::NONE;

    char runId_[RUN_ID_SIZE] = {};

    uint8_t targetWheelIndex_ = 0;

    ScanDirection scanDirection_ =
        ScanDirection::CW;

    WheelActionType wheelAction_ =
        WheelActionType::DIGIT_MOVE;

    uint32_t digitMoveSteps_ = 0;
    uint32_t probeAmplitude_ = 0;
    uint8_t probeCycles_ = 0;

    uint32_t deadlineMs_ = 0;
    bool deadlineActive_ = false;

    bool leaveDoneState_ = false;
};