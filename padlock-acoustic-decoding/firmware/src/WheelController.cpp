#include "WheelController.h"

#include <esp_timer.h>

#include "Calibration.h"

WheelController::WheelController(StepperAxis& axis)
    : axis_(axis)
{
}

void WheelController::begin()
{
    axis_.begin();

    operation_ = Operation::IDLE;
    direction_ = ScanDirection::CW;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = 0;
    probeSegmentIndex_ = 0;
    probeCycles_ = 0;
    probeTotalSegments_ = 0;
    nextSweepBoundaryIndex_ = 1;
    sweepSectorCount_ = 0;
    sweepSectorSteps_ = 0;
    clearEvents();
}

void WheelController::update()
{
    axis_.update();

    if ((operation_ == Operation::BINDING_SWEEP ||
         operation_ == Operation::BINDING_REFERENCE_SWEEP) &&
        axis_.isBusy())
    {
        if (!emitSweepBoundaries(
                axis_.completedPulses()
            ))
        {
            stop();
            return;
        }
    }

    if (!axis_.takeMoveCompleted())
    {
        return;
    }

    operationPulseCount_ += axis_.completedPulses();

    if (operation_ == Operation::DIGIT_MOVE)
    {
        pushEvent(
            WheelEventType::SCAN_END,
            0,
            operationPulseCount_
        );

        finishOperation();
        return;
    }

    if (operation_ == Operation::BINDING_SWEEP ||
        operation_ == Operation::BINDING_REFERENCE_SWEEP)
    {
        if (!emitSweepBoundaries(operationPulseCount_) ||
            !pushEvent(
                WheelEventType::SCAN_END,
                0,
                operationPulseCount_
            ))
        {
            stop();
            return;
        }

        finishOperation();
        return;
    }

    if (operation_ == Operation::PROBE)
    {
        pushEvent(
            WheelEventType::PROBE_SEGMENT,
            probeSegmentIndex_,
            operationPulseCount_
        );

        if (probeSegmentIndex_ < 3)
        {
            ++probeSegmentIndex_;

            if (!startProbeSegment(probeSegmentIndex_))
            {
                stop();
            }

            return;
        }

        pushEvent(
            WheelEventType::PROBE_END,
            0,
            operationPulseCount_
        );

        finishOperation();
        return;
    }

    if (operation_ == Operation::WIDE_PROBE)
    {
        if (!pushEvent(
                WheelEventType::WIDE_PROBE_SEGMENT,
                probeSegmentIndex_,
                operationPulseCount_
            ))
        {
            stop();
            return;
        }

        if (probeSegmentIndex_ < probeTotalSegments_)
        {
            ++probeSegmentIndex_;
            if (!startWideProbeSegment(probeSegmentIndex_))
            {
                stop();
            }
            return;
        }

        if (!pushEvent(
                WheelEventType::WIDE_PROBE_END,
                0,
                operationPulseCount_
            ))
        {
            stop();
            return;
        }

        finishOperation();
        return;
    }

    finishOperation();
}

bool WheelController::startJog(
    ScanDirection direction,
    uint32_t steps
)
{
    if (isBusy() ||
        steps == 0 ||
        steps > Calibration::MAX_WHEEL_JOG_STEPS)
    {
        return false;
    }

    clearEvents();

    direction_ = direction;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = 0;
    probeSegmentIndex_ = 0;

    const bool started = axis_.startMove(
        toStepDirection(direction),
        steps,
        Calibration::WHEEL_STEP_INTERVAL_US
    );

    if (!started)
    {
        return false;
    }

    operation_ = Operation::JOG;
    return true;
}

bool WheelController::startMoveOneDigit(
    ScanDirection direction
)
{
    return startMoveOneDigit(
        direction,
        Calibration::WHEEL_STEPS_PER_DIGIT
    );
}

bool WheelController::startMoveOneDigit(
    ScanDirection direction,
    uint32_t steps
)
{
    if (isBusy() ||
        !Calibration::wheelConfigured() ||
        steps == 0 ||
        steps > Calibration::MAX_WHEEL_JOG_STEPS)
    {
        return false;
    }

    clearEvents();

    direction_ = direction;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = 0;
    probeSegmentIndex_ = 0;

    const bool started = axis_.startMove(
        toStepDirection(direction),
        steps,
        Calibration::WHEEL_STEP_INTERVAL_US
    );

    if (!started)
    {
        return false;
    }

    operation_ = Operation::DIGIT_MOVE;

    if (!pushEvent(
            WheelEventType::SCAN_START,
            0,
            0
        ))
    {
        stop();
        return false;
    }

    return true;
}

bool WheelController::startScanOneDigit(
    ScanDirection direction
)
{
    return startMoveOneDigit(direction);
}

bool WheelController::startScanOneRevolution(
    ScanDirection direction
)
{
    if (isBusy() ||
        !Calibration::wheelConfigured())
    {
        return false;
    }

    clearEvents();

    direction_ = direction;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = 0;
    probeSegmentIndex_ = 0;
    probeCycles_ = 0;
    probeTotalSegments_ = 0;
    nextSweepBoundaryIndex_ = 1;
    sweepSectorCount_ = Calibration::DIGIT_COUNT;
    sweepSectorSteps_ = Calibration::BINDING_SWEEP_STEPS_PER_SECTOR;

    const bool started = axis_.startMove(
        toStepDirection(direction),
        Calibration::BINDING_SWEEP_STEPS_PER_REV,
        Calibration::WHEEL_STEP_INTERVAL_US
    );

    if (!started)
    {
        return false;
    }

    operation_ = Operation::BINDING_SWEEP;

    if (!pushEvent(
            WheelEventType::SCAN_START,
            0,
            0
        ))
    {
        stop();
        return false;
    }

    return true;
}

bool WheelController::startBindingReferenceSweep(
    ScanDirection direction
)
{
    if (isBusy() ||
        !Calibration::wheelConfigured())
    {
        return false;
    }

    clearEvents();

    direction_ = direction;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = 0;
    probeSegmentIndex_ = 0;
    probeCycles_ = 0;
    probeTotalSegments_ = 0;
    nextSweepBoundaryIndex_ = 1;
    sweepSectorCount_ =
        Calibration::BINDING_REFERENCE_SWEEP_SECTOR_COUNT;
    sweepSectorSteps_ =
        Calibration::BINDING_REFERENCE_SWEEP_SECTOR_STEPS;

    const bool started = axis_.startMove(
        toStepDirection(direction),
        Calibration::BINDING_REFERENCE_SWEEP_STEPS,
        Calibration::WHEEL_STEP_INTERVAL_US
    );

    if (!started)
    {
        return false;
    }

    operation_ = Operation::BINDING_REFERENCE_SWEEP;

    if (!pushEvent(
            WheelEventType::SCAN_START,
            0,
            0
        ))
    {
        stop();
        return false;
    }

    return true;
}

bool WheelController::startProbe(
    ScanDirection firstDirection,
    uint32_t amplitudeSteps
)
{
    if (isBusy() ||
        !Calibration::probeAmplitudeValid(amplitudeSteps))
    {
        return false;
    }

    clearEvents();

    direction_ = firstDirection;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = amplitudeSteps;
    probeSegmentIndex_ = 1;
    operation_ = Operation::PROBE;

    if (!pushEvent(
            WheelEventType::PROBE_START,
            0,
            0
        ))
    {
        stop();
        return false;
    }

    if (!startProbeSegment(probeSegmentIndex_))
    {
        stop();
        return false;
    }

    return true;
}

bool WheelController::startWideProbe(
    ScanDirection firstSweepDirection,
    uint32_t amplitudeSteps,
    uint8_t cycles
)
{
    if (isBusy() ||
        !Calibration::wideProbeValid(amplitudeSteps, cycles))
    {
        return false;
    }

    clearEvents();

    direction_ = firstSweepDirection;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = amplitudeSteps;
    probeCycles_ = cycles;
    probeTotalSegments_ = static_cast<uint8_t>(2 * cycles + 2);
    probeSegmentIndex_ = 1;
    operation_ = Operation::WIDE_PROBE;

    if (!pushEvent(
            WheelEventType::WIDE_PROBE_START,
            0,
            0
        ))
    {
        stop();
        return false;
    }

    if (!startWideProbeSegment(probeSegmentIndex_))
    {
        stop();
        return false;
    }

    return true;
}

void WheelController::stop()
{
    axis_.stop();

    operation_ = Operation::IDLE;
    operationCompleted_ = false;
    operationPulseCount_ = 0;
    probeAmplitudeSteps_ = 0;
    probeSegmentIndex_ = 0;
    probeCycles_ = 0;
    probeTotalSegments_ = 0;
    nextSweepBoundaryIndex_ = 1;
    sweepSectorCount_ = 0;
    sweepSectorSteps_ = 0;
    clearEvents();
}

void WheelController::disable()
{
    stop();
    axis_.disable();
}

bool WheelController::isBusy() const
{
    return operation_ != Operation::IDLE ||
           axis_.isBusy();
}

bool WheelController::isScanning() const
{
    return operation_ == Operation::DIGIT_MOVE;
}

bool WheelController::isBindingSweep() const
{
    return operation_ == Operation::BINDING_SWEEP ||
           operation_ == Operation::BINDING_REFERENCE_SWEEP;
}

bool WheelController::isProbing() const
{
    return operation_ == Operation::PROBE ||
           operation_ == Operation::WIDE_PROBE;
}

bool WheelController::takeOperationCompleted()
{
    const bool completed = operationCompleted_;
    operationCompleted_ = false;

    return completed;
}

bool WheelController::takeEvent(WheelEvent& event)
{
    if (eventCount_ == 0)
    {
        return false;
    }

    event = eventQueue_[eventHead_];

    eventHead_ =
        (eventHead_ + 1) % EVENT_QUEUE_SIZE;

    --eventCount_;

    return true;
}

uint32_t WheelController::currentStep() const
{
    if (axis_.isBusy())
    {
        return operationPulseCount_ +
               axis_.completedPulses();
    }

    return operationPulseCount_;
}

ScanDirection WheelController::direction() const
{
    return direction_;
}

WheelActionType WheelController::actionType() const
{
    if (operation_ == Operation::PROBE)
    {
        return WheelActionType::PROBE;
    }

    if (operation_ == Operation::WIDE_PROBE)
    {
        return WheelActionType::WIDE_PROBE;
    }

    if (operation_ == Operation::BINDING_SWEEP)
    {
        return WheelActionType::BINDING_SWEEP;
    }

    if (operation_ == Operation::BINDING_REFERENCE_SWEEP)
    {
        return WheelActionType::BINDING_REFERENCE_SWEEP;
    }

    return WheelActionType::DIGIT_MOVE;
}

StepDirection WheelController::toStepDirection(
    ScanDirection direction
) const
{
    if (direction == ScanDirection::CW)
    {
        return StepDirection::FORWARD;
    }

    return StepDirection::REVERSE;
}

ScanDirection WheelController::oppositeDirection(
    ScanDirection direction
) const
{
    return direction == ScanDirection::CW
        ? ScanDirection::CCW
        : ScanDirection::CW;
}

bool WheelController::startProbeSegment(
    uint8_t segmentIndex
)
{
    ScanDirection segmentDirection = direction_;
    uint32_t pulses = probeAmplitudeSteps_;

    if (segmentIndex == 2)
    {
        segmentDirection = oppositeDirection(direction_);
        pulses = probeAmplitudeSteps_ * 2;
    }
    else if (segmentIndex != 1 && segmentIndex != 3)
    {
        return false;
    }

    return axis_.startMove(
        toStepDirection(segmentDirection),
        pulses,
        Calibration::WHEEL_STEP_INTERVAL_US
    );
}

bool WheelController::startWideProbeSegment(
    uint8_t segmentIndex
)
{
    if (segmentIndex == 0 || segmentIndex > probeTotalSegments_)
    {
        return false;
    }

    ScanDirection segmentDirection = direction_;
    uint32_t pulses = probeAmplitudeSteps_ * 2;

    if (segmentIndex == 1)
    {
        // Move from centre to -A so the first full sweep crosses the centre
        // in the selected direction.
        segmentDirection = oppositeDirection(direction_);
        pulses = probeAmplitudeSteps_;
    }
    else if (segmentIndex == probeTotalSegments_)
    {
        // The last full half-cycle ends at -A; return to centre.
        segmentDirection = direction_;
        pulses = probeAmplitudeSteps_;
    }
    else
    {
        // Segment 2 is the first -A -> +A sweep. Directions alternate.
        segmentDirection = (segmentIndex % 2 == 0)
            ? direction_
            : oppositeDirection(direction_);
    }

    return axis_.startMove(
        toStepDirection(segmentDirection),
        pulses,
        Calibration::WHEEL_STEP_INTERVAL_US
    );
}

bool WheelController::emitSweepBoundaries(
    uint32_t completedPulses
)
{
    while (nextSweepBoundaryIndex_ < sweepSectorCount_)
    {
        const uint32_t boundaryStep =
            static_cast<uint32_t>(
                nextSweepBoundaryIndex_
            ) * sweepSectorSteps_;

        if (completedPulses < boundaryStep)
        {
            break;
        }

        if (!pushEvent(
                WheelEventType::DIGIT_BOUNDARY,
                nextSweepBoundaryIndex_,
                boundaryStep
            ))
        {
            return false;
        }

        ++nextSweepBoundaryIndex_;
    }

    return true;
}

bool WheelController::pushEvent(
    WheelEventType type,
    uint8_t digitIndex,
    uint32_t step
)
{
    if (eventCount_ >= EVENT_QUEUE_SIZE)
    {
        return false;
    }

    WheelEvent& event = eventQueue_[eventTail_];

    event.type = type;
    event.digitIndex = digitIndex;
    event.step = step;
    event.timestampUs = esp_timer_get_time();

    eventTail_ =
        (eventTail_ + 1) % EVENT_QUEUE_SIZE;

    ++eventCount_;

    return true;
}

void WheelController::finishOperation()
{
    operation_ = Operation::IDLE;
    operationCompleted_ = true;
    probeSegmentIndex_ = 0;
    probeAmplitudeSteps_ = 0;
    probeCycles_ = 0;
    probeTotalSegments_ = 0;
    nextSweepBoundaryIndex_ = 1;
}

void WheelController::clearEvents()
{
    eventHead_ = 0;
    eventTail_ = 0;
    eventCount_ = 0;
}
