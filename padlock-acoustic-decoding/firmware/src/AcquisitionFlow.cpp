#include "AcquisitionFlow.h"

#include <string.h>

#include "Calibration.h"
#include "FeatureFlags.h"
#include "LimitSwitch.h"
#include "RailController.h"
#include "SafetyController.h"
#include "SerialProtocol.h"
#include "ServoLift.h"
#include "WheelController.h"

AcquisitionFlow::AcquisitionFlow(
    WheelController& wheel,
    RailController& rail,
    ServoLift& servo,
    LimitSwitch& limitSwitch,
    SerialProtocol& protocol,
    SafetyController& safety
)
    : wheel_(wheel),
      rail_(rail),
      servo_(servo),
      limitSwitch_(limitSwitch),
      protocol_(protocol),
      safety_(safety)
{
}

void AcquisitionFlow::begin()
{
    protocol_.begin();
    limitSwitch_.begin();
    wheel_.begin();
    rail_.begin();
    servo_.begin();
    safety_.begin();

    state_ = AcquisitionState::BOOT;
    activeOperation_ = ActiveOperation::NONE;
    pendingRailAction_ = PendingRailAction::NONE;

    targetWheelIndex_ = 0;
    scanDirection_ = ScanDirection::CW;
    wheelAction_ = WheelActionType::DIGIT_MOVE;
    digitMoveSteps_ = Calibration::WHEEL_STEPS_PER_DIGIT;
    probeAmplitude_ = 0;
    probeCycles_ = 0;

    clearRun();
    clearDeadline();

    leaveDoneState_ = false;

    protocol_.sendSystemReady();

    protocol_.sendConfigStatus(
        Calibration::servoConfigured(),
        Calibration::wheelConfigured(),
        Calibration::railConfigured(),
        FeatureFlags::LIMIT_SWITCH_VERIFIED,
        FeatureFlags::AUTO_ACQUISITION_ENABLED
    );

    setState(AcquisitionState::IDLE);
}

void AcquisitionFlow::update()
{
    protocol_.update();
    limitSwitch_.update();

    if (state_ == AcquisitionState::DONE &&
        leaveDoneState_)
    {
        leaveDoneState_ = false;
        clearRun();
        setState(AcquisitionState::IDLE);
    }

    processCommands();

    wheel_.update();
    rail_.update();
    servo_.update();
    safety_.update();

    updateSafety();
    updateWheelEvents();
    updateRailState();
    updateCompletions();
    updateTimeout();
}

AcquisitionState AcquisitionFlow::state() const
{
    return state_;
}

FaultCode AcquisitionFlow::faultCode() const
{
    if (safety_.hasFault())
    {
        return safety_.faultCode();
    }

    if (rail_.hasFault())
    {
        return rail_.faultCode();
    }

    return FaultCode::NONE;
}

bool AcquisitionFlow::isIdle() const
{
    return state_ == AcquisitionState::IDLE &&
           activeOperation_ == ActiveOperation::NONE &&
           !wheel_.isBusy() &&
           !rail_.isBusy() &&
           !servo_.isBusy() &&
           !safety_.hasFault() &&
           !safety_.isStopping();
}

const char* AcquisitionFlow::runId() const
{
    return runId_;
}

uint8_t AcquisitionFlow::targetWheelIndex() const
{
    return targetWheelIndex_;
}

ScanDirection AcquisitionFlow::scanDirection() const
{
    return scanDirection_;
}

void AcquisitionFlow::processCommands()
{
    Command command;

    while (protocol_.takeCommand(command))
    {
        handleCommand(command);
    }
}

void AcquisitionFlow::handleCommand(
    const Command& command
)
{
    switch (command.type)
    {
        case CommandType::PING:
            protocol_.sendAck("PING");
            return;

        case CommandType::STATUS:
            sendCurrentStatus();
            return;

        case CommandType::LIMIT_READ:
            protocol_.sendLimitState(
                limitSwitch_.rawTriggered(),
                limitSwitch_.isTriggered()
            );
            return;

        case CommandType::STOP:
            protocol_.sendAck("STOP");

            if (safety_.hasFault())
            {
                setState(AcquisitionState::FAULT);
                return;
            }

            activeOperation_ =
                ActiveOperation::STOPPING;

            pendingRailAction_ =
                PendingRailAction::NONE;

            clearDeadline();
            setState(AcquisitionState::ABORTING);

            safety_.requestStop();
            return;

        case CommandType::RESET_FAULT:
            if (!safety_.resetFault())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::NONE;

            pendingRailAction_ =
                PendingRailAction::NONE;

            clearDeadline();
            clearRun();

            setState(AcquisitionState::IDLE);
            protocol_.sendAck("RESET_FAULT");
            return;

        case CommandType::JOG_WHEEL:
            if (!FeatureFlags::ALLOW_WHEEL_JOG)
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "WHEEL_JOG_DISABLED"
                );
                return;
            }

            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!wheel_.startJog(
                    command.scanDirection,
                    command.steps
                ))
            {
                protocol_.sendError(
                    FaultCode::INVALID_ARGUMENT
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::WHEEL_JOG;

            protocol_.sendAck("JOG_WHEEL");
            return;

        case CommandType::PROBE_WHEEL:
            if (!FeatureFlags::ALLOW_WHEEL_JOG)
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "WHEEL_PROBE_DISABLED"
                );
                return;
            }

            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!Calibration::probeAmplitudeValid(
                    command.probeAmplitude
                ))
            {
                protocol_.sendError(
                    FaultCode::INVALID_ARGUMENT,
                    "PROBE_AMPLITUDE"
                );
                return;
            }

            clearRun();
            copyRunId("manual");

            scanDirection_ = command.scanDirection;
            wheelAction_ = WheelActionType::PROBE;
            probeAmplitude_ = command.probeAmplitude;

            if (!wheel_.startProbe(
                    scanDirection_,
                    probeAmplitude_
                ))
            {
                clearRun();
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::MANUAL_PROBE;

            setState(AcquisitionState::PROBING);
            setDeadline(
                Calibration::PROBE_TIMEOUT_MS
            );

            protocol_.sendAck("PROBE");
            return;

        case CommandType::JOG_RAIL:
            if (!FeatureFlags::ALLOW_SHORT_RAIL_JOG)
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "RAIL_JOG_DISABLED"
                );
                return;
            }

            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (Calibration::servoConfigured() &&
                !servo_.isUp())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "SERVO_NOT_UP"
                );
                return;
            }

            if (!rail_.startJog(
                    command.stepDirection,
                    command.steps
                ))
            {
                protocol_.sendError(
                    FaultCode::INVALID_ARGUMENT
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::RAIL_JOG;

            protocol_.sendAck("JOG_RAIL");
            return;

        case CommandType::SERVO_UP:
            if (!FeatureFlags::ALLOW_SERVO_TEST)
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "SERVO_TEST_DISABLED"
                );
                return;
            }

            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!Calibration::servoConfigured())
            {
                protocol_.sendError(
                    FaultCode::CALIBRATION_REQUIRED,
                    "SERVO"
                );
                return;
            }

            // A consecutive AUTO digit batch may intentionally leave the
            // wheel driver enabled between WAVs. Release it before lifting
            // the drive head.
            wheel_.disable();

            if (!servo_.moveUp())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::SERVO_MOVE;

            protocol_.sendAck("SERVO_UP");
            return;

        case CommandType::SERVO_DOWN:
            if (!FeatureFlags::ALLOW_SERVO_TEST)
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "SERVO_TEST_DISABLED"
                );
                return;
            }

            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!Calibration::servoConfigured())
            {
                protocol_.sendError(
                    FaultCode::CALIBRATION_REQUIRED,
                    "SERVO"
                );
                return;
            }

            if (!servo_.moveDown())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::SERVO_MOVE;

            protocol_.sendAck("SERVO_DOWN");
            return;

        case CommandType::SERVO_ANGLE:
            if (!FeatureFlags::ALLOW_SERVO_TEST)
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "SERVO_TEST_DISABLED"
                );
                return;
            }

            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!servo_.moveToAngle(
                    command.servoAngle
                ))
            {
                protocol_.sendError(
                    FaultCode::INVALID_ARGUMENT
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::SERVO_MOVE;

            protocol_.sendAck("SERVO_ANGLE");
            return;

        case CommandType::HOME:
            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!FeatureFlags::LIMIT_SWITCH_VERIFIED)
            {
                protocol_.sendError(
                    FaultCode::LIMIT_NOT_VERIFIED
                );
                return;
            }

            if (Calibration::HOME_BACKOFF_STEPS == 0 ||
                Calibration::RAIL_MAX_TRAVEL_STEPS <= 0)
            {
                protocol_.sendError(
                    FaultCode::CALIBRATION_REQUIRED,
                    "RAIL_HOME"
                );
                return;
            }

            if (Calibration::servoConfigured() &&
                !servo_.isUp())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "SERVO_NOT_UP"
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::HOME;

            if (!startRailHome())
            {
                activeOperation_ =
                    ActiveOperation::NONE;

                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            protocol_.sendAck("HOME");
            return;

        case CommandType::GOTO_WHEEL:
            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!FeatureFlags::LIMIT_SWITCH_VERIFIED)
            {
                protocol_.sendError(
                    FaultCode::LIMIT_NOT_VERIFIED
                );
                return;
            }

            if (!Calibration::railConfigured())
            {
                protocol_.sendError(
                    FaultCode::CALIBRATION_REQUIRED,
                    "RAIL"
                );
                return;
            }

            if (!rail_.isHomed())
            {
                protocol_.sendError(
                    FaultCode::RAIL_NOT_HOMED
                );
                return;
            }

            if (Calibration::servoConfigured() &&
                !servo_.isUp())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE,
                    "SERVO_NOT_UP"
                );
                return;
            }

            targetWheelIndex_ =
                command.wheelIndex;

            activeOperation_ =
                ActiveOperation::GOTO_WHEEL;

            if (!startRailMoveToTarget())
            {
                activeOperation_ =
                    ActiveOperation::NONE;

                protocol_.sendError(
                    FaultCode::RAIL_RANGE_ERROR
                );
                return;
            }

            protocol_.sendAck("GOTO");
            return;

        case CommandType::SCAN_WHEEL:
            if (!canStartOperation())
            {
                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            if (!Calibration::wheelConfigured())
            {
                protocol_.sendError(
                    FaultCode::CALIBRATION_REQUIRED,
                    "WHEEL"
                );
                return;
            }

            clearRun();
            copyRunId("manual");

            scanDirection_ =
                command.scanDirection;

            wheelAction_ =
                WheelActionType::DIGIT_MOVE;
            probeAmplitude_ = 0;
            probeCycles_ = 0;

            if (!wheel_.startMoveOneDigit(
                    scanDirection_
                ))
            {
                clearRun();

                protocol_.sendError(
                    FaultCode::INVALID_STATE
                );
                return;
            }

            activeOperation_ =
                ActiveOperation::MANUAL_SCAN;

            setState(AcquisitionState::SCANNING);
            setDeadline(
                Calibration::SCAN_TIMEOUT_MS
            );

            protocol_.sendAck("SCAN");
            return;

        case CommandType::PREPARE:
            startPrepare(command);
            return;

        case CommandType::RECORDING:
            startRecording(command);
            return;

        case CommandType::NONE:
        default:
            protocol_.sendError(
                FaultCode::INVALID_COMMAND
            );
            return;
    }
}

void AcquisitionFlow::sendCurrentStatus()
{
    protocol_.sendStatus(
        state_,
        faultCode(),
        wheel_.isBusy(),
        rail_.isBusy(),
        rail_.isHomed(),
        servo_.isBusy(),
        limitSwitch_.isTriggered(),
        rail_.currentPosition()
    );

    protocol_.sendConfigStatus(
        Calibration::servoConfigured(),
        Calibration::wheelConfigured(),
        Calibration::railConfigured(),
        FeatureFlags::LIMIT_SWITCH_VERIFIED,
        FeatureFlags::AUTO_ACQUISITION_ENABLED
    );
}

void AcquisitionFlow::updateSafety()
{
    FaultCode code = FaultCode::NONE;

    if (safety_.takeFault(code))
    {
        activeOperation_ =
            ActiveOperation::NONE;

        pendingRailAction_ =
            PendingRailAction::NONE;

        clearDeadline();
        leaveDoneState_ = false;

        setState(AcquisitionState::FAULT);
        protocol_.sendError(code);
    }

    if (safety_.takeStopCompleted())
    {
        activeOperation_ =
            ActiveOperation::NONE;

        pendingRailAction_ =
            PendingRailAction::NONE;

        clearDeadline();
        clearRun();

        setState(AcquisitionState::IDLE);
        protocol_.sendCompleted("STOP");
    }
}

void AcquisitionFlow::updateWheelEvents()
{
    WheelEvent event;

    while (wheel_.takeEvent(event))
    {
        const char* eventRunId =
            runId_[0] != '\0'
                ? runId_
                : "manual";

        protocol_.sendWheelEvent(
            eventRunId,
            event
        );
    }
}

void AcquisitionFlow::updateRailState()
{
    if (activeOperation_ != ActiveOperation::HOME &&
        activeOperation_ != ActiveOperation::GOTO_WHEEL &&
        activeOperation_ != ActiveOperation::AUTO_PREPARE)
    {
        return;
    }

    switch (rail_.state())
    {
        case RailController::State::HOMING_FAST:
            setState(
                AcquisitionState::HOMING_FAST
            );
            break;

        case RailController::State::HOMING_BACKOFF:
            setState(
                AcquisitionState::HOMING_BACKOFF
            );
            break;

        case RailController::State::HOMING_SLOW:
            setState(
                AcquisitionState::HOMING_SLOW
            );
            break;

        case RailController::State::MOVING_TO_WHEEL:
            setState(
                AcquisitionState::MOVING_TO_WHEEL
            );
            break;

        case RailController::State::SETTLING:
            setState(
                AcquisitionState::RAIL_SETTLING
            );
            break;

        default:
            break;
    }
}

void AcquisitionFlow::updateCompletions()
{
    if (safety_.hasFault() ||
        safety_.isStopping())
    {
        return;
    }

    if (rail_.takeOperationCompleted())
    {
        handleRailCompleted();
    }

    if (wheel_.takeOperationCompleted())
    {
        handleWheelCompleted();
    }

    if (servo_.takeMoveCompleted())
    {
        handleServoCompleted();
    }
}

void AcquisitionFlow::updateTimeout()
{
    if (!deadlineExpired() ||
        safety_.hasFault() ||
        safety_.isStopping())
    {
        return;
    }

    clearDeadline();

    switch (state_)
    {
        case AcquisitionState::WAITING_FOR_RECORDING:
            enterFault(
                FaultCode::RECORDING_WAIT_TIMEOUT
            );
            break;

        case AcquisitionState::SCANNING:
        case AcquisitionState::PROBING:
            enterFault(
                FaultCode::SCAN_TIMEOUT
            );
            break;

        case AcquisitionState::HOMING_FAST:
        case AcquisitionState::HOMING_BACKOFF:
        case AcquisitionState::HOMING_SLOW:
            enterFault(
                FaultCode::HOME_TIMEOUT
            );
            break;

        case AcquisitionState::MOVING_TO_WHEEL:
        case AcquisitionState::RAIL_SETTLING:
            enterFault(
                FaultCode::RAIL_MOVE_TIMEOUT
            );
            break;

        default:
            enterFault(
                FaultCode::INVALID_STATE
            );
            break;
    }
}

bool AcquisitionFlow::startPrepare(
    const Command& command
)
{
    if (!canStartOperation())
    {
        protocol_.sendError(
            FaultCode::INVALID_STATE
        );
        return false;
    }

    if (!FeatureFlags::AUTO_ACQUISITION_ENABLED)
    {
        protocol_.sendError(
            FaultCode::AUTO_ACQUISITION_DISABLED
        );
        return false;
    }

    if (!FeatureFlags::LIMIT_SWITCH_VERIFIED)
    {
        protocol_.sendError(
            FaultCode::LIMIT_NOT_VERIFIED
        );
        return false;
    }

    if (!Calibration::acquisitionConfigured())
    {
        protocol_.sendError(
            FaultCode::CALIBRATION_REQUIRED
        );
        return false;
    }

    // reuseContact=true means this is the next one-digit recording in the
    // same physical contact batch. Any other PREPARE starts a new mechanical
    // setup, so release residual wheel holding torque before servo/rail moves.
    if (!command.reuseContact)
    {
        wheel_.disable();
    }

    copyRunId(command.runId);

    targetWheelIndex_ =
        command.wheelIndex;

    scanDirection_ =
        command.scanDirection;

    wheelAction_ = command.wheelAction;
    digitMoveSteps_ = (
        wheelAction_ == WheelActionType::DIGIT_MOVE &&
        command.steps > 0
    )
        ? command.steps
        : Calibration::WHEEL_STEPS_PER_DIGIT;
    probeAmplitude_ = command.probeAmplitude;
    probeCycles_ = command.probeCycles;

    if (wheelAction_ == WheelActionType::DIGIT_MOVE &&
        (digitMoveSteps_ == 0 ||
         digitMoveSteps_ > Calibration::MAX_WHEEL_JOG_STEPS))
    {
        clearRun();
        protocol_.sendError(
            FaultCode::INVALID_ARGUMENT,
            "DIGIT_STEPS"
        );
        return false;
    }

    if (wheelAction_ == WheelActionType::PROBE &&
        !Calibration::probeAmplitudeValid(
            probeAmplitude_
        ))
    {
        clearRun();
        protocol_.sendError(
            FaultCode::INVALID_ARGUMENT,
            "PROBE_AMPLITUDE"
        );
        return false;
    }

    if (wheelAction_ == WheelActionType::WIDE_PROBE &&
        !Calibration::wideProbeValid(
            probeAmplitude_,
            probeCycles_
        ))
    {
        clearRun();
        protocol_.sendError(
            FaultCode::INVALID_ARGUMENT,
            "WIDE_PROBE_PARAMETERS"
        );
        return false;
    }

    activeOperation_ =
        ActiveOperation::AUTO_PREPARE;

    pendingRailAction_ =
        PendingRailAction::NONE;

    // Fast path for consecutive one-digit recordings on the same wheel.
    // The previous run intentionally leaves the drive head down, so there is
    // no servo cycle and no rail movement between candidates.
    if (command.reuseContact)
    {
        const long expectedRailPosition =
            Calibration::RAIL_WHEEL_POSITIONS[
                targetWheelIndex_ - 1
            ];

        if (wheelAction_ != WheelActionType::DIGIT_MOVE ||
            !servo_.isDown() ||
            !rail_.isHomed() ||
            rail_.currentPosition() != expectedRailPosition)
        {
            activeOperation_ = ActiveOperation::NONE;
            clearRun();
            protocol_.sendError(
                FaultCode::INVALID_STATE,
                "REUSE_CONTACT_STATE"
            );
            return false;
        }

        protocol_.sendAck(
            "PREPARE",
            runId_
        );

        setState(
            AcquisitionState::WAITING_FOR_RECORDING
        );
        setDeadline(
            Calibration::RECORDING_WAIT_TIMEOUT_MS
        );
        protocol_.sendReadyToRecord(
            runId_
        );
        return true;
    }

    if (!servo_.isUp())
    {
        if (!startServoUp())
        {
            activeOperation_ =
                ActiveOperation::NONE;

            clearRun();

            protocol_.sendError(
                FaultCode::INVALID_STATE,
                "SERVO_UP_FAILED"
            );

            return false;
        }

        protocol_.sendAck(
            "PREPARE",
            runId_
        );

        return true;
    }

    if (!rail_.isHomed())
    {
        if (!queueRailAction(
                PendingRailAction::GOTO_WHEEL
            ) ||
            !startRailHome())
        {
            activeOperation_ =
                ActiveOperation::NONE;

            pendingRailAction_ =
                PendingRailAction::NONE;

            clearRun();

            protocol_.sendError(
                FaultCode::INVALID_STATE,
                "HOME_FAILED"
            );

            return false;
        }
    }
    else
    {
        if (!startRailMoveToTarget())
        {
            activeOperation_ =
                ActiveOperation::NONE;

            clearRun();

            protocol_.sendError(
                FaultCode::RAIL_RANGE_ERROR
            );

            return false;
        }
    }

    protocol_.sendAck(
        "PREPARE",
        runId_
    );

    return true;
}

bool AcquisitionFlow::startRecording(
    const Command& command
)
{
    if (state_ !=
            AcquisitionState::WAITING_FOR_RECORDING ||
        activeOperation_ !=
            ActiveOperation::AUTO_PREPARE)
    {
        protocol_.sendError(
            FaultCode::INVALID_STATE
        );
        return false;
    }

    if (!runIdMatches(command.runId))
    {
        protocol_.sendError(
            FaultCode::RUN_ID_MISMATCH
        );
        return false;
    }

    if (!automaticReady())
    {
        protocol_.sendError(
            FaultCode::CALIBRATION_REQUIRED
        );
        return false;
    }

    clearDeadline();

    if (!startConfiguredWheelAction())
    {
        enterFault(
            FaultCode::INVALID_STATE
        );
        return false;
    }

    activeOperation_ =
        ActiveOperation::AUTO_SCAN;

    if (wheelAction_ == WheelActionType::PROBE ||
        wheelAction_ == WheelActionType::WIDE_PROBE)
    {
        setState(AcquisitionState::PROBING);
        setDeadline(
            Calibration::PROBE_TIMEOUT_MS
        );
    }
    else
    {
        setState(AcquisitionState::SCANNING);
        setDeadline(
            Calibration::SCAN_TIMEOUT_MS
        );
    }

    protocol_.sendAck(
        "RECORDING",
        runId_
    );

    return true;
}

bool AcquisitionFlow::queueRailAction(
    PendingRailAction action
)
{
    if (action == PendingRailAction::NONE ||
        pendingRailAction_ !=
            PendingRailAction::NONE)
    {
        return false;
    }

    pendingRailAction_ = action;
    return true;
}

bool AcquisitionFlow::startPendingRailAction()
{
    const PendingRailAction action =
        pendingRailAction_;

    pendingRailAction_ =
        PendingRailAction::NONE;

    switch (action)
    {
        case PendingRailAction::HOME:
            return startRailHome();

        case PendingRailAction::GOTO_WHEEL:
            return startRailMoveToTarget();

        case PendingRailAction::NONE:
        default:
            return false;
    }
}

bool AcquisitionFlow::startRailHome()
{
    if (!rail_.startHome())
    {
        return false;
    }

    setDeadline(
        Calibration::HOME_TIMEOUT_MS
    );

    updateRailState();
    return true;
}

bool AcquisitionFlow::startRailMoveToTarget()
{
    if (!rail_.startMoveToWheel(
            targetWheelIndex_
        ))
    {
        return false;
    }

    setDeadline(
        Calibration::RAIL_MOVE_TIMEOUT_MS
    );

    updateRailState();
    return true;
}

bool AcquisitionFlow::startServoDown()
{
    clearDeadline();

    if (!servo_.moveDown())
    {
        return false;
    }

    setState(
        AcquisitionState::LOWERING_SERVO
    );

    return true;
}

bool AcquisitionFlow::startServoUp()
{
    clearDeadline();

    // Release any holding torque retained by a consecutive AUTO digit batch
    // before the drive head is lifted or the rail is allowed to move.
    wheel_.disable();

    if (!servo_.moveUp())
    {
        return false;
    }

    setState(
        AcquisitionState::RAISING_SERVO
    );

    return true;
}


bool AcquisitionFlow::startConfiguredWheelAction()
{
    if (wheelAction_ == WheelActionType::PROBE)
    {
        return wheel_.startProbe(
            scanDirection_,
            probeAmplitude_
        );
    }

    if (wheelAction_ == WheelActionType::WIDE_PROBE)
    {
        return wheel_.startWideProbe(
            scanDirection_,
            probeAmplitude_,
            probeCycles_
        );
    }

    if (wheelAction_ == WheelActionType::BINDING_SWEEP)
    {
        return wheel_.startScanOneRevolution(
            scanDirection_
        );
    }

    if (wheelAction_ == WheelActionType::BINDING_REFERENCE_SWEEP)
    {
        return wheel_.startBindingReferenceSweep(
            scanDirection_
        );
    }

    return wheel_.startMoveOneDigit(
        scanDirection_,
        digitMoveSteps_
    );
}

uint32_t AcquisitionFlow::expectedWheelPulseCount() const
{
    if (wheelAction_ == WheelActionType::PROBE)
    {
        return probeAmplitude_ * 4;
    }

    if (wheelAction_ == WheelActionType::WIDE_PROBE)
    {
        return probeAmplitude_ *
               (4 * static_cast<uint32_t>(probeCycles_) + 2);
    }

    if (wheelAction_ == WheelActionType::BINDING_SWEEP)
    {
        return Calibration::BINDING_SWEEP_STEPS_PER_REV;
    }

    if (wheelAction_ == WheelActionType::BINDING_REFERENCE_SWEEP)
    {
        return Calibration::BINDING_REFERENCE_SWEEP_STEPS;
    }

    return digitMoveSteps_;
}

void AcquisitionFlow::handleRailCompleted()
{
    clearDeadline();

    switch (activeOperation_)
    {
        case ActiveOperation::RAIL_JOG:
            rail_.disable();

            completeManualOperation(
                "JOG_RAIL"
            );
            return;

        case ActiveOperation::HOME:
            rail_.disable();

            completeManualOperation(
                "HOME"
            );
            return;

        case ActiveOperation::GOTO_WHEEL:
            rail_.disable();

            completeManualOperation(
                "GOTO"
            );
            return;

        case ActiveOperation::AUTO_PREPARE:
            if (pendingRailAction_ !=
                PendingRailAction::NONE)
            {
                if (!startPendingRailAction())
                {
                    enterFault(
                        FaultCode::INVALID_STATE
                    );
                }

                return;
            }

            if (!startServoDown())
            {
                enterFault(
                    FaultCode::INVALID_STATE
                );
            }

            return;

        default:
            return;
    }
}

void AcquisitionFlow::handleWheelCompleted()
{
    clearDeadline();

    switch (activeOperation_)
    {
        case ActiveOperation::WHEEL_JOG:
            wheel_.disable();

            completeManualOperation(
                "JOG_WHEEL"
            );
            return;

        case ActiveOperation::MANUAL_SCAN:
            wheel_.disable();

            completeManualOperation(
                "SCAN"
            );

            clearRun();
            return;

        case ActiveOperation::MANUAL_PROBE:
            if (wheel_.currentStep() !=
                expectedWheelPulseCount())
            {
                enterFault(
                    FaultCode::STEP_COUNT_ERROR
                );
                return;
            }

            wheel_.disable();
            completeManualOperation(
                "PROBE"
            );
            clearRun();
            return;

        case ActiveOperation::AUTO_SCAN:
            if (wheel_.currentStep() !=
                expectedWheelPulseCount())
            {
                enterFault(
                    FaultCode::STEP_COUNT_ERROR
                );
                return;
            }

            // Finish the scan while the servo remains down.
            // Python stops recording before sending SERVO,UP.
            finishAutomaticRun();
            return;

        default:
            return;
    }
}

void AcquisitionFlow::handleServoCompleted()
{
    switch (activeOperation_)
    {
        case ActiveOperation::SERVO_MOVE:
            completeManualOperation(
                "SERVO"
            );
            return;

        case ActiveOperation::AUTO_PREPARE:
            if (state_ ==
                AcquisitionState::RAISING_SERVO)
            {
                if (!rail_.isHomed())
                {
                    if (!queueRailAction(
                            PendingRailAction::GOTO_WHEEL
                        ) ||
                        !startRailHome())
                    {
                        enterFault(
                            FaultCode::INVALID_STATE
                        );
                    }
                }
                else
                {
                    if (!startRailMoveToTarget())
                    {
                        enterFault(
                            FaultCode::RAIL_RANGE_ERROR
                        );
                    }
                }

                return;
            }

            if (state_ ==
                AcquisitionState::LOWERING_SERVO)
            {
                setState(
                    AcquisitionState::
                        WAITING_FOR_RECORDING
                );

                setDeadline(
                    Calibration::
                        RECORDING_WAIT_TIMEOUT_MS
                );

                protocol_.sendReadyToRecord(
                    runId_
                );
            }

            return;

        default:
            return;
    }
}

bool AcquisitionFlow::canStartOperation() const
{
    return state_ == AcquisitionState::IDLE &&
           activeOperation_ ==
               ActiveOperation::NONE &&
           !wheel_.isBusy() &&
           !rail_.isBusy() &&
           !servo_.isBusy() &&
           !safety_.hasFault() &&
           !safety_.isStopping();
}

bool AcquisitionFlow::automaticReady() const
{
    return FeatureFlags::AUTO_ACQUISITION_ENABLED &&
           FeatureFlags::LIMIT_SWITCH_VERIFIED &&
           Calibration::acquisitionConfigured() &&
           !safety_.hasFault();
}

void AcquisitionFlow::completeManualOperation(
    const char* operation
)
{
    activeOperation_ =
        ActiveOperation::NONE;

    pendingRailAction_ =
        PendingRailAction::NONE;

    clearDeadline();

    setState(AcquisitionState::IDLE);
    protocol_.sendCompleted(operation);
}

void AcquisitionFlow::finishAutomaticRun()
{
    // Consecutive one-digit recordings on the same wheel intentionally keep
    // the wheel driver enabled while the servo remains down. This preserves
    // rotor holding torque between candidates and avoids a disable/enable hard
    // restart before every digit. Non-digit AUTO operations retain the old
    // behaviour and are disabled immediately.
    const bool keepWheelHolding =
        wheelAction_ == WheelActionType::DIGIT_MOVE &&
        servo_.isDown();

    if (!keepWheelHolding)
    {
        wheel_.disable();
    }

    rail_.disable();

    activeOperation_ =
        ActiveOperation::NONE;

    pendingRailAction_ =
        PendingRailAction::NONE;

    clearDeadline();

    protocol_.sendDone(runId_);
    setState(AcquisitionState::DONE);

    leaveDoneState_ = true;
}

void AcquisitionFlow::enterFault(
    FaultCode code
)
{
    if (code == FaultCode::NONE)
    {
        return;
    }

    activeOperation_ =
        ActiveOperation::NONE;

    pendingRailAction_ =
        PendingRailAction::NONE;

    clearDeadline();
    leaveDoneState_ = false;

    safety_.raiseFault(code);
    setState(AcquisitionState::FAULT);

    FaultCode pendingCode = FaultCode::NONE;

    if (safety_.takeFault(pendingCode))
    {
        protocol_.sendError(pendingCode);
    }
}

void AcquisitionFlow::setState(
    AcquisitionState state
)
{
    if (state_ == state)
    {
        return;
    }

    state_ = state;
    protocol_.sendState(state_);
}

void AcquisitionFlow::setDeadline(
    uint32_t durationMs
)
{
    deadlineMs_ = millis() + durationMs;
    deadlineActive_ = true;
}

void AcquisitionFlow::clearDeadline()
{
    deadlineMs_ = 0;
    deadlineActive_ = false;
}

bool AcquisitionFlow::deadlineExpired() const
{
    if (!deadlineActive_)
    {
        return false;
    }

    return timeReached(
        millis(),
        deadlineMs_
    );
}

bool AcquisitionFlow::runIdMatches(
    const char* value
) const
{
    if (value == nullptr ||
        runId_[0] == '\0')
    {
        return false;
    }

    return strcmp(runId_, value) == 0;
}

void AcquisitionFlow::copyRunId(
    const char* value
)
{
    clearRun();

    if (value == nullptr)
    {
        return;
    }

    strncpy(
        runId_,
        value,
        RUN_ID_SIZE - 1
    );

    runId_[RUN_ID_SIZE - 1] = '\0';
}

void AcquisitionFlow::clearRun()
{
    memset(
        runId_,
        0,
        sizeof(runId_)
    );

    targetWheelIndex_ = 0;
    scanDirection_ = ScanDirection::CW;
    wheelAction_ = WheelActionType::DIGIT_MOVE;
    digitMoveSteps_ = Calibration::WHEEL_STEPS_PER_DIGIT;
    probeAmplitude_ = 0;
    probeCycles_ = 0;
}

bool AcquisitionFlow::timeReached(
    uint32_t now,
    uint32_t target
)
{
    return static_cast<int32_t>(
        now - target
    ) >= 0;
}