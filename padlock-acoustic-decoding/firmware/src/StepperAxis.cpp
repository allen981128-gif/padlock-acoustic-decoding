#include "StepperAxis.h"

#include "Calibration.h"
#include "HardwareConfig.h"

StepperAxis::StepperAxis(
    uint8_t enPin,
    uint8_t stepPin,
    uint8_t dirPin,
    bool forwardIsHigh
)
    : enPin_(enPin),
      stepPin_(stepPin),
      dirPin_(dirPin),
      forwardIsHigh_(forwardIsHigh)
{
}

void StepperAxis::begin()
{
    pinMode(enPin_, OUTPUT);
    pinMode(stepPin_, OUTPUT);
    pinMode(dirPin_, OUTPUT);

    digitalWrite(stepPin_, LogicLevels::STEP_IDLE);
    writeDirection(direction_);
    digitalWrite(enPin_, LogicLevels::DRIVER_DISABLE);

    initialized_ = true;
    enabled_ = false;
    busy_ = false;
    stepHigh_ = false;
    moveCompleted_ = false;
}

void StepperAxis::update()
{
    if (!initialized_ || !busy_)
    {
        return;
    }

    const uint32_t now = micros();

    // Finish the current STEP pulse
    if (stepHigh_)
    {
        if (!timeReached(now, stepLowTimeUs_))
        {
            return;
        }

        digitalWrite(stepPin_, LogicLevels::STEP_IDLE);
        stepHigh_ = false;
        ++completedPulses_;

        if (completedPulses_ >= requestedPulses_)
        {
            busy_ = false;
            moveCompleted_ = true;
            return;
        }

        const uint32_t lowTimeUs =
            stepIntervalUs_ - Calibration::STEP_PULSE_WIDTH_US;

        nextStepTimeUs_ = now + lowTimeUs;
        return;
    }

    // Start the next STEP pulse
    if (!timeReached(now, nextStepTimeUs_))
    {
        return;
    }

    digitalWrite(stepPin_, LogicLevels::STEP_ACTIVE);
    stepHigh_ = true;

    stepLowTimeUs_ =
        now + Calibration::STEP_PULSE_WIDTH_US;
}

bool StepperAxis::startMove(
    StepDirection direction,
    uint32_t pulses,
    uint32_t stepIntervalUs
)
{
    if (!initialized_ || busy_)
    {
        return false;
    }

    if (pulses == 0)
    {
        return false;
    }

    if (stepIntervalUs <= Calibration::STEP_PULSE_WIDTH_US)
    {
        return false;
    }

    direction_ = direction;
    requestedPulses_ = pulses;
    completedPulses_ = 0;
    stepIntervalUs_ = stepIntervalUs;

    stepHigh_ = false;
    moveCompleted_ = false;

    digitalWrite(stepPin_, LogicLevels::STEP_IDLE);
    writeDirection(direction_);

    const bool wasEnabled = enabled_;
    enable();

    busy_ = true;

    // If the driver was previously disabled, allow its power stage and rotor
    // to settle before the first STEP pulse. If it was already enabled (the
    // normal path between consecutive digit recordings), only the existing
    // DIR setup delay is required.
    const uint32_t firstStepDelayUs = wasEnabled
        ? Calibration::STEP_PULSE_WIDTH_US
        : Calibration::DRIVER_ENABLE_SETTLE_US;

    nextStepTimeUs_ = micros() + firstStepDelayUs;

    return true;
}

void StepperAxis::stop()
{
    if (initialized_)
    {
        digitalWrite(stepPin_, LogicLevels::STEP_IDLE);
    }

    busy_ = false;
    stepHigh_ = false;
    moveCompleted_ = false;
}

void StepperAxis::enable()
{
    if (!initialized_)
    {
        return;
    }

    digitalWrite(enPin_, LogicLevels::DRIVER_ENABLE);
    enabled_ = true;
}

void StepperAxis::disable()
{
    if (!initialized_)
    {
        return;
    }

    if (busy_)
    {
        stop();
    }

    digitalWrite(stepPin_, LogicLevels::STEP_IDLE);
    digitalWrite(enPin_, LogicLevels::DRIVER_DISABLE);

    stepHigh_ = false;
    enabled_ = false;
}

bool StepperAxis::isBusy() const
{
    return busy_;
}

bool StepperAxis::isEnabled() const
{
    return enabled_;
}

bool StepperAxis::takeMoveCompleted()
{
    const bool completed = moveCompleted_;
    moveCompleted_ = false;

    return completed;
}

uint32_t StepperAxis::requestedPulses() const
{
    return requestedPulses_;
}

uint32_t StepperAxis::completedPulses() const
{
    return completedPulses_;
}

StepDirection StepperAxis::direction() const
{
    return direction_;
}

void StepperAxis::writeDirection(
    StepDirection direction
)
{
    bool outputHigh = forwardIsHigh_;

    if (direction == StepDirection::REVERSE)
    {
        outputHigh = !outputHigh;
    }

    digitalWrite(dirPin_, outputHigh ? HIGH : LOW);
}

bool StepperAxis::timeReached(
    uint32_t now,
    uint32_t target
)
{
    return static_cast<int32_t>(now - target) >= 0;
}