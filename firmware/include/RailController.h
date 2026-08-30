#pragma once

#include <Arduino.h>

#include "LimitSwitch.h"
#include "StepperAxis.h"
#include "SystemTypes.h"

class RailController
{
public:
    enum class State : uint8_t
    {
        IDLE,
        JOGGING,
        HOMING_FAST,
        HOMING_BACKOFF,
        HOMING_SLOW,
        MOVING_TO_WHEEL,
        SETTLING,
        FAULT
    };

    RailController(
        StepperAxis& axis,
        LimitSwitch& limitSwitch
    );

    void begin();
    void update();

    bool startJog(
        StepDirection direction,
        uint32_t steps
    );

    bool startHome();

    bool startMoveToWheel(
        uint8_t wheelIndex
    );

    void stop();
    void disable();
    void clearFault();

    bool isBusy() const;
    bool isHomed() const;
    bool hasFault() const;

    State state() const;
    FaultCode faultCode() const;

    bool takeOperationCompleted();
    bool takeFault(FaultCode& code);

    long currentPosition() const;
    long targetPosition() const;
    uint8_t targetWheelIndex() const;

private:
    bool startAxisMove(
        StepDirection direction,
        uint32_t steps,
        uint32_t stepIntervalUs
    );

    void updatePosition();

    bool startHomeBackoff();
    bool startHomeSlow();

    void beginSettling();
    void finishOperation();
    void setFault(FaultCode code);

    StepDirection homeDirection() const;
    StepDirection awayDirection() const;

    int positionSign(
        StepDirection direction
    ) const;

    static bool timeReached(
        uint32_t now,
        uint32_t target
    );

    StepperAxis& axis_;
    LimitSwitch& limitSwitch_;

    State state_ = State::IDLE;
    FaultCode faultCode_ = FaultCode::NONE;

    bool homed_ = false;
    bool operationCompleted_ = false;
    bool faultPending_ = false;

    StepDirection activeDirection_ =
        StepDirection::FORWARD;

    long currentPosition_ = 0;
    long targetPosition_ = 0;

    uint8_t targetWheelIndex_ = 0;

    uint32_t lastAxisPulseCount_ = 0;
    uint32_t operationDeadlineMs_ = 0;
    uint32_t settleDeadlineMs_ = 0;
};