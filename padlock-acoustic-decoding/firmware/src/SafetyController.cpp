#include "SafetyController.h"

#include "Calibration.h"
#include "FeatureFlags.h"
#include "LimitSwitch.h"
#include "RailController.h"
#include "ServoLift.h"
#include "WheelController.h"

SafetyController::SafetyController(
    WheelController& wheel,
    RailController& rail,
    ServoLift& servo,
    LimitSwitch& limitSwitch
)
    : wheel_(wheel),
      rail_(rail),
      servo_(servo),
      limitSwitch_(limitSwitch)
{
}

void SafetyController::begin()
{
    state_ = State::READY;
    faultCode_ = FaultCode::NONE;

    safeStateApplied_ = false;
    stopCompleted_ = false;
    faultPending_ = false;

    applySafeState();
}

void SafetyController::update()
{
    FaultCode railFault = FaultCode::NONE;

    if (rail_.takeFault(railFault))
    {
        raiseFault(railFault);
    }

    if (state_ == State::READY &&
        unexpectedLimitTriggered())
    {
        raiseFault(FaultCode::LIMIT_UNEXPECTED);
    }

    if (state_ == State::STOPPING)
    {
        if (!safeStateApplied_)
        {
            applySafeState();
        }

        if (!wheel_.isBusy() &&
            !rail_.isBusy() &&
            !servo_.isBusy())
        {
            state_ = State::READY;
            stopCompleted_ = true;
        }
    }

    if (state_ == State::FAULT &&
        !safeStateApplied_)
    {
        applySafeState();
    }
}

void SafetyController::requestStop()
{
    if (state_ == State::FAULT)
    {
        if (!safeStateApplied_)
        {
            applySafeState();
        }

        return;
    }

    if (state_ == State::STOPPING)
    {
        return;
    }

    state_ = State::STOPPING;
    stopCompleted_ = false;
    safeStateApplied_ = false;

    applySafeState();
}

void SafetyController::raiseFault(FaultCode code)
{
    if (code == FaultCode::NONE)
    {
        return;
    }

    if (state_ == State::FAULT)
    {
        if (!safeStateApplied_)
        {
            applySafeState();
        }

        return;
    }

    state_ = State::FAULT;
    faultCode_ = code;

    stopCompleted_ = false;
    faultPending_ = true;
    safeStateApplied_ = false;

    applySafeState();
}

bool SafetyController::resetFault()
{
    if (state_ != State::FAULT)
    {
        return false;
    }

    if (wheel_.isBusy() ||
        rail_.isBusy() ||
        servo_.isBusy())
    {
        return false;
    }

    if (rail_.hasFault())
    {
        rail_.clearFault();
    }

    state_ = State::READY;
    faultCode_ = FaultCode::NONE;

    safeStateApplied_ = true;
    stopCompleted_ = false;
    faultPending_ = false;

    return true;
}

SafetyController::State SafetyController::state() const
{
    return state_;
}

bool SafetyController::isStopping() const
{
    return state_ == State::STOPPING;
}

bool SafetyController::hasFault() const
{
    return state_ == State::FAULT;
}

bool SafetyController::isSafe() const
{
    return state_ == State::READY &&
           faultCode_ == FaultCode::NONE &&
           !wheel_.isBusy() &&
           !rail_.isBusy() &&
           !servo_.isBusy();
}

FaultCode SafetyController::faultCode() const
{
    return faultCode_;
}

bool SafetyController::takeStopCompleted()
{
    const bool completed = stopCompleted_;
    stopCompleted_ = false;

    return completed;
}

bool SafetyController::takeFault(FaultCode& code)
{
    if (!faultPending_)
    {
        return false;
    }

    code = faultCode_;
    faultPending_ = false;

    return true;
}

void SafetyController::applySafeState()
{
    wheel_.disable();
    rail_.disable();

    if (Calibration::servoConfigured())
    {
        servo_.moveUp();
    }

    safeStateApplied_ = true;
}

bool SafetyController::unexpectedLimitTriggered() const
{
    if (!FeatureFlags::LIMIT_SWITCH_VERIFIED ||
        !limitSwitch_.isTriggered())
    {
        return false;
    }

    if (rail_.hasFault() ||
        rail_.isBusy() ||
        !rail_.isHomed())
    {
        return false;
    }

    // Before the switch-release distance is calibrated,
    // a pressed home switch is not treated as a fault.
    if (Calibration::HOME_BACKOFF_STEPS == 0)
    {
        return false;
    }

    // The switch may remain pressed while the rail is
    // still inside the calibrated release distance.
    return rail_.currentPosition() >
           static_cast<long>(
               Calibration::HOME_BACKOFF_STEPS
           );
}
