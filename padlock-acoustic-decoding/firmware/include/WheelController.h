#pragma once

#include <Arduino.h>

#include "StepperAxis.h"
#include "SystemTypes.h"

class WheelController
{
public:
    explicit WheelController(StepperAxis& axis);

    void begin();
    void update();

    bool startJog(
        ScanDirection direction,
        uint32_t steps
    );

    bool startMoveOneDigit(
        ScanDirection direction
    );

    bool startMoveOneDigit(
        ScanDirection direction,
        uint32_t steps
    );

    // Backwards-compatible name used by the previous firmware.
    bool startScanOneDigit(
        ScanDirection direction
    );

    bool startScanOneRevolution(
        ScanDirection direction
    );

    bool startBindingReferenceSweep(
        ScanDirection direction
    );

    bool startProbe(
        ScanDirection firstDirection,
        uint32_t amplitudeSteps
    );

    bool startWideProbe(
        ScanDirection firstSweepDirection,
        uint32_t amplitudeSteps,
        uint8_t cycles
    );

    void stop();
    void disable();

    bool isBusy() const;
    bool isScanning() const;
    bool isBindingSweep() const;
    bool isProbing() const;

    bool takeOperationCompleted();
    bool takeEvent(WheelEvent& event);

    uint32_t currentStep() const;
    ScanDirection direction() const;
    WheelActionType actionType() const;

private:
    enum class Operation : uint8_t
    {
        IDLE,
        JOG,
        DIGIT_MOVE,
        BINDING_SWEEP,
        BINDING_REFERENCE_SWEEP,
        PROBE,
        WIDE_PROBE
    };

    static constexpr uint8_t EVENT_QUEUE_SIZE = 32;

    StepDirection toStepDirection(
        ScanDirection direction
    ) const;

    ScanDirection oppositeDirection(
        ScanDirection direction
    ) const;

    bool startProbeSegment(
        uint8_t segmentIndex
    );

    bool startWideProbeSegment(
        uint8_t segmentIndex
    );

    bool emitSweepBoundaries(
        uint32_t completedPulses
    );

    bool pushEvent(
        WheelEventType type,
        uint8_t digitIndex,
        uint32_t step
    );

    void finishOperation();
    void clearEvents();

    StepperAxis& axis_;

    Operation operation_ = Operation::IDLE;
    ScanDirection direction_ = ScanDirection::CW;

    bool operationCompleted_ = false;

    uint32_t operationPulseCount_ = 0;
    uint32_t probeAmplitudeSteps_ = 0;
    uint8_t probeSegmentIndex_ = 0;
    uint8_t probeCycles_ = 0;
    uint8_t probeTotalSegments_ = 0;
    uint8_t nextSweepBoundaryIndex_ = 1;
    uint8_t sweepSectorCount_ = 0;
    uint32_t sweepSectorSteps_ = 0;

    WheelEvent eventQueue_[EVENT_QUEUE_SIZE];
    uint8_t eventHead_ = 0;
    uint8_t eventTail_ = 0;
    uint8_t eventCount_ = 0;
};
