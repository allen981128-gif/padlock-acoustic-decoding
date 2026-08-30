#include "RailController.h"

#include "Calibration.h"
#include "FeatureFlags.h"

RailController::RailController(
    StepperAxis& axis,
    LimitSwitch& limitSwitch
)
    : axis_(axis),
      limitSwitch_(limitSwitch)
{
}

void RailController::begin()
{
    axis_.begin();

    state_ = State::IDLE;
    faultCode_ = FaultCode::NONE;

    homed_ = false;
    operationCompleted_ = false;
    faultPending_ = false;

    currentPosition_ = 0;
    targetPosition_ = 0;
    targetWheelIndex_ = 0;

    lastAxisPulseCount_ = 0;
    operationDeadlineMs_ = 0;
    settleDeadlineMs_ = 0;
}

void RailController::update()
{
    axis_.update();
    updatePosition();

    if (state_ == State::IDLE ||
        state_ == State::FAULT)
    {
        return;
    }

    const uint32_t now = millis();
    const bool moveCompleted =
        axis_.takeMoveCompleted();

    if (FeatureFlags::LIMIT_SWITCH_VERIFIED &&
        limitSwitch_.isTriggered())
    {
        if (state_ == State::HOMING_FAST)
        {
            axis_.stop();

            if (!startHomeBackoff())
            {
                setFault(FaultCode::INVALID_STATE);
            }

            return;
        }

        if (state_ == State::HOMING_SLOW)
        {
            axis_.stop();

            currentPosition_ = 0;
            targetPosition_ = 0;
            homed_ = true;

            finishOperation();
            return;
        }

        if (state_ == State::JOGGING)
        {
            if (activeDirection_ == homeDirection())
            {
                // Reaching the home switch during a manual
                // jog is a normal end-stop event.
                axis_.stop();

                currentPosition_ = 0;
                targetPosition_ = 0;

                // Precise homing is still completed only
                // by the HOME routine.
                finishOperation();
                return;
            }

            // Moving away from home while the switch is
            // still pressed is allowed. The mechanism may
            // need several jog commands before it releases.
            if (homed_ &&
                Calibration::HOME_BACKOFF_STEPS > 0 &&
                currentPosition_ >
                    static_cast<long>(
                        Calibration::HOME_BACKOFF_STEPS
                    ))
            {
                setFault(FaultCode::LIMIT_UNEXPECTED);
                return;
            }
        }

        if (state_ == State::MOVING_TO_WHEEL)
        {
            if (activeDirection_ == homeDirection() &&
                targetPosition_ == 0)
            {
                axis_.stop();

                currentPosition_ = 0;
                beginSettling();
                return;
            }

            if (activeDirection_ == awayDirection() &&
                currentPosition_ <=
                    static_cast<long>(
                        Calibration::HOME_BACKOFF_STEPS
                    ))
            {
                // Allow the switch to release
            }
            else
            {
                setFault(FaultCode::LIMIT_UNEXPECTED);
                return;
            }
        }

        if (state_ == State::SETTLING &&
            targetPosition_ != 0)
        {
            setFault(FaultCode::LIMIT_UNEXPECTED);
            return;
        }
    }

    switch (state_)
    {
        case State::JOGGING:
            if (moveCompleted)
            {
                // A short jog away from home may complete
                // before the switch has fully released.
                finishOperation();
                return;
            }
            break;

        case State::HOMING_FAST:
            if (moveCompleted)
            {
                setFault(FaultCode::HOME_TIMEOUT);
                return;
            }
            break;

        case State::HOMING_BACKOFF:
            if (moveCompleted)
            {
                if (limitSwitch_.isTriggered())
                {
                    setFault(
                        FaultCode::LIMIT_UNEXPECTED
                    );
                    return;
                }

                if (!startHomeSlow())
                {
                    setFault(FaultCode::INVALID_STATE);
                }

                return;
            }
            break;

        case State::HOMING_SLOW:
            if (moveCompleted)
            {
                setFault(FaultCode::HOME_TIMEOUT);
                return;
            }
            break;

        case State::MOVING_TO_WHEEL:
            if (moveCompleted)
            {
                if (currentPosition_ != targetPosition_)
                {
                    setFault(
                        FaultCode::STEP_COUNT_ERROR
                    );
                    return;
                }

                if (FeatureFlags::LIMIT_SWITCH_VERIFIED &&
                    targetPosition_ > 0 &&
                    limitSwitch_.isTriggered())
                {
                    setFault(
                        FaultCode::LIMIT_UNEXPECTED
                    );
                    return;
                }

                beginSettling();
                return;
            }
            break;

        case State::SETTLING:
            if (timeReached(now, settleDeadlineMs_))
            {
                finishOperation();
                return;
            }
            break;

        default:
            break;
    }

    if (operationDeadlineMs_ == 0 ||
        !timeReached(now, operationDeadlineMs_))
    {
        return;
    }

    switch (state_)
    {
        case State::HOMING_FAST:
        case State::HOMING_BACKOFF:
        case State::HOMING_SLOW:
            setFault(FaultCode::HOME_TIMEOUT);
            break;

        case State::JOGGING:
        case State::MOVING_TO_WHEEL:
            setFault(FaultCode::RAIL_MOVE_TIMEOUT);
            break;

        default:
            break;
    }
}

bool RailController::startJog(
    StepDirection direction,
    uint32_t steps
)
{
    if (state_ != State::IDLE ||
        hasFault() ||
        steps == 0 ||
        steps > Calibration::MAX_RAIL_JOG_STEPS)
    {
        return false;
    }

    const int sign = positionSign(direction);

    const int64_t projectedPosition =
        static_cast<int64_t>(currentPosition_) +
        static_cast<int64_t>(sign) * steps;

    if (homed_ &&
        Calibration::RAIL_MAX_TRAVEL_STEPS > 0)
    {
        if (projectedPosition < 0 ||
            projectedPosition >
                Calibration::RAIL_MAX_TRAVEL_STEPS)
        {
            return false;
        }
    }

    if (FeatureFlags::LIMIT_SWITCH_VERIFIED &&
        limitSwitch_.isTriggered() &&
        direction == homeDirection())
    {
        return false;
    }

    operationCompleted_ = false;
    targetWheelIndex_ = 0;
    targetPosition_ =
        static_cast<long>(projectedPosition);

    if (!startAxisMove(
            direction,
            steps,
            Calibration::RAIL_STEP_INTERVAL_US
        ))
    {
        return false;
    }

    state_ = State::JOGGING;
    operationDeadlineMs_ =
        millis() + Calibration::RAIL_MOVE_TIMEOUT_MS;

    return true;
}

bool RailController::startHome()
{
    if (state_ != State::IDLE ||
        hasFault() ||
        !FeatureFlags::LIMIT_SWITCH_VERIFIED)
    {
        return false;
    }

    if (Calibration::HOME_BACKOFF_STEPS == 0 ||
        Calibration::RAIL_MAX_TRAVEL_STEPS <= 0 ||
        static_cast<uint64_t>(
            Calibration::RAIL_MAX_TRAVEL_STEPS
        ) > UINT32_MAX)
    {
        return false;
    }

    homed_ = false;
    operationCompleted_ = false;
    targetWheelIndex_ = 0;
    targetPosition_ = 0;

    if (limitSwitch_.isTriggered())
    {
        return startHomeBackoff();
    }

    if (!startAxisMove(
            homeDirection(),
            static_cast<uint32_t>(
                Calibration::RAIL_MAX_TRAVEL_STEPS
            ),
            Calibration::HOME_FAST_STEP_INTERVAL_US
        ))
    {
        return false;
    }

    state_ = State::HOMING_FAST;
    operationDeadlineMs_ =
        millis() + Calibration::HOME_TIMEOUT_MS;

    return true;
}

bool RailController::startMoveToWheel(
    uint8_t wheelIndex
)
{
    if (state_ != State::IDLE ||
        hasFault() ||
        !homed_ ||
        !FeatureFlags::LIMIT_SWITCH_VERIFIED ||
        !Calibration::railConfigured())
    {
        return false;
    }

    if (wheelIndex < 1 ||
        wheelIndex > Calibration::LOCK_WHEEL_COUNT)
    {
        return false;
    }

    const long target =
        Calibration::RAIL_WHEEL_POSITIONS[
            wheelIndex - 1
        ];

    if (target < 0 ||
        target > Calibration::RAIL_MAX_TRAVEL_STEPS)
    {
        return false;
    }

    operationCompleted_ = false;
    targetWheelIndex_ = wheelIndex;
    targetPosition_ = target;

    const int64_t difference =
        static_cast<int64_t>(targetPosition_) -
        static_cast<int64_t>(currentPosition_);

    if (difference == 0)
    {
        beginSettling();
        return true;
    }

    const StepDirection direction =
        difference > 0
            ? awayDirection()
            : homeDirection();

    const uint64_t stepCount =
        difference > 0
            ? static_cast<uint64_t>(difference)
            : static_cast<uint64_t>(-difference);

    if (stepCount == 0 ||
        stepCount > UINT32_MAX)
    {
        return false;
    }

    if (!startAxisMove(
            direction,
            static_cast<uint32_t>(stepCount),
            Calibration::RAIL_STEP_INTERVAL_US
        ))
    {
        return false;
    }

    state_ = State::MOVING_TO_WHEEL;
    operationDeadlineMs_ =
        millis() +
        Calibration::RAIL_MOVE_TIMEOUT_MS;

    return true;
}

void RailController::stop()
{
    updatePosition();
    axis_.stop();

    if (state_ == State::HOMING_FAST ||
        state_ == State::HOMING_BACKOFF ||
        state_ == State::HOMING_SLOW)
    {
        homed_ = false;
    }

    if (state_ != State::FAULT)
    {
        state_ = State::IDLE;
    }

    operationCompleted_ = false;
    operationDeadlineMs_ = 0;
    settleDeadlineMs_ = 0;

    targetPosition_ = currentPosition_;
    targetWheelIndex_ = 0;
}

void RailController::disable()
{
    stop();
    axis_.disable();
}

void RailController::clearFault()
{
    if (!hasFault())
    {
        return;
    }

    axis_.disable();

    state_ = State::IDLE;
    faultCode_ = FaultCode::NONE;

    homed_ = false;
    operationCompleted_ = false;
    faultPending_ = false;

    currentPosition_ = 0;
    targetPosition_ = 0;
    targetWheelIndex_ = 0;

    operationDeadlineMs_ = 0;
    settleDeadlineMs_ = 0;
}

bool RailController::isBusy() const
{
    return state_ != State::IDLE &&
           state_ != State::FAULT;
}

bool RailController::isHomed() const
{
    return homed_;
}

bool RailController::hasFault() const
{
    return faultCode_ != FaultCode::NONE;
}

RailController::State RailController::state() const
{
    return state_;
}

FaultCode RailController::faultCode() const
{
    return faultCode_;
}

bool RailController::takeOperationCompleted()
{
    const bool completed = operationCompleted_;
    operationCompleted_ = false;

    return completed;
}

bool RailController::takeFault(FaultCode& code)
{
    if (!faultPending_)
    {
        return false;
    }

    code = faultCode_;
    faultPending_ = false;

    return true;
}

long RailController::currentPosition() const
{
    return currentPosition_;
}

long RailController::targetPosition() const
{
    return targetPosition_;
}

uint8_t RailController::targetWheelIndex() const
{
    return targetWheelIndex_;
}

bool RailController::startAxisMove(
    StepDirection direction,
    uint32_t steps,
    uint32_t stepIntervalUs
)
{
    activeDirection_ = direction;
    lastAxisPulseCount_ = 0;

    return axis_.startMove(
        direction,
        steps,
        stepIntervalUs
    );
}

void RailController::updatePosition()
{
    const uint32_t currentPulseCount =
        axis_.completedPulses();

    if (currentPulseCount < lastAxisPulseCount_)
    {
        lastAxisPulseCount_ = currentPulseCount;
        return;
    }

    const uint32_t pulseDifference =
        currentPulseCount - lastAxisPulseCount_;

    if (pulseDifference == 0)
    {
        return;
    }

    const int sign =
        positionSign(activeDirection_);

    const int64_t newPosition =
        static_cast<int64_t>(currentPosition_) +
        static_cast<int64_t>(sign) *
        pulseDifference;

    currentPosition_ =
        static_cast<long>(newPosition);

    lastAxisPulseCount_ = currentPulseCount;
}

bool RailController::startHomeBackoff()
{
    if (Calibration::HOME_BACKOFF_STEPS == 0)
    {
        return false;
    }

    if (!startAxisMove(
            awayDirection(),
            Calibration::HOME_BACKOFF_STEPS,
            Calibration::HOME_FAST_STEP_INTERVAL_US
        ))
    {
        return false;
    }

    state_ = State::HOMING_BACKOFF;
    operationDeadlineMs_ =
        millis() + Calibration::HOME_TIMEOUT_MS;

    return true;
}

bool RailController::startHomeSlow()
{
    const uint64_t slowSearchSteps =
        static_cast<uint64_t>(
            Calibration::HOME_BACKOFF_STEPS
        ) * 2;

    if (slowSearchSteps == 0 ||
        slowSearchSteps > UINT32_MAX)
    {
        return false;
    }

    if (!startAxisMove(
            homeDirection(),
            static_cast<uint32_t>(slowSearchSteps),
            Calibration::HOME_SLOW_STEP_INTERVAL_US
        ))
    {
        return false;
    }

    state_ = State::HOMING_SLOW;
    operationDeadlineMs_ =
        millis() + Calibration::HOME_TIMEOUT_MS;

    return true;
}

void RailController::beginSettling()
{
    state_ = State::SETTLING;
    operationDeadlineMs_ = 0;

    settleDeadlineMs_ =
        millis() + Calibration::RAIL_SETTLE_MS;
}

void RailController::finishOperation()
{
    state_ = State::IDLE;
    operationCompleted_ = true;

    operationDeadlineMs_ = 0;
    settleDeadlineMs_ = 0;
}

void RailController::setFault(FaultCode code)
{
    updatePosition();
    axis_.disable();

    state_ = State::FAULT;
    faultCode_ = code;

    homed_ = false;
    operationCompleted_ = false;
    faultPending_ = true;

    operationDeadlineMs_ = 0;
    settleDeadlineMs_ = 0;
}

StepDirection RailController::homeDirection() const
{
    return Calibration::RAIL_HOME_IS_FORWARD
        ? StepDirection::FORWARD
        : StepDirection::REVERSE;
}

StepDirection RailController::awayDirection() const
{
    return homeDirection() == StepDirection::FORWARD
        ? StepDirection::REVERSE
        : StepDirection::FORWARD;
}

int RailController::positionSign(
    StepDirection direction
) const
{
    return direction == awayDirection() ? 1 : -1;
}

bool RailController::timeReached(
    uint32_t now,
    uint32_t target
)
{
    return static_cast<int32_t>(now - target) >= 0;
}
