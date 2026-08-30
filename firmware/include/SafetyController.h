#pragma once

#include <Arduino.h>

#include "SystemTypes.h"

class LimitSwitch;
class RailController;
class ServoLift;
class WheelController;

class SafetyController
{
public:
    enum class State : uint8_t
    {
        READY,
        STOPPING,
        FAULT
    };

    SafetyController(
        WheelController& wheel,
        RailController& rail,
        ServoLift& servo,
        LimitSwitch& limitSwitch
    );

    void begin();
    void update();

    void requestStop();
    void raiseFault(FaultCode code);

    bool resetFault();

    State state() const;

    bool isStopping() const;
    bool hasFault() const;
    bool isSafe() const;

    FaultCode faultCode() const;

    bool takeStopCompleted();
    bool takeFault(FaultCode& code);

private:
    void applySafeState();
    bool unexpectedLimitTriggered() const;

    WheelController& wheel_;
    RailController& rail_;
    ServoLift& servo_;
    LimitSwitch& limitSwitch_;

    State state_ = State::READY;
    FaultCode faultCode_ = FaultCode::NONE;

    bool safeStateApplied_ = false;
    bool stopCompleted_ = false;
    bool faultPending_ = false;
};