#pragma once

#include <Arduino.h>

#include "SystemTypes.h"

class StepperAxis
{
public:
    StepperAxis(
        uint8_t enPin,
        uint8_t stepPin,
        uint8_t dirPin,
        bool forwardIsHigh
    );

    void begin();
    void update();

    bool startMove(
        StepDirection direction,
        uint32_t pulses,
        uint32_t stepIntervalUs
    );

    void stop();

    void enable();
    void disable();

    bool isBusy() const;
    bool isEnabled() const;

    bool takeMoveCompleted();

    uint32_t requestedPulses() const;
    uint32_t completedPulses() const;

    StepDirection direction() const;

private:
    void writeDirection(StepDirection direction);
    static bool timeReached(uint32_t now, uint32_t target);

    uint8_t enPin_;
    uint8_t stepPin_;
    uint8_t dirPin_;

    bool forwardIsHigh_;

    bool initialized_ = false;
    bool enabled_ = false;
    bool busy_ = false;
    bool stepHigh_ = false;
    bool moveCompleted_ = false;

    StepDirection direction_ = StepDirection::FORWARD;

    uint32_t requestedPulses_ = 0;
    uint32_t completedPulses_ = 0;

    uint32_t stepIntervalUs_ = 0;
    uint32_t nextStepTimeUs_ = 0;
    uint32_t stepLowTimeUs_ = 0;
};