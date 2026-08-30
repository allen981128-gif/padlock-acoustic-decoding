#include "ServoLift.h"

#include "Calibration.h"

ServoLift::ServoLift(uint8_t pin)
    : pin_(pin)
{
}

void ServoLift::begin()
{
    if (servo_.attached())
    {
        servo_.detach();
    }

    attached_ = false;
    busy_ = false;
    moveCompleted_ = false;
    commandedAngle_ = -1;
    settleDeadlineMs_ = 0;
}

void ServoLift::update()
{
    if (!busy_)
    {
        return;
    }

    const uint32_t now = millis();

    if (!timeReached(now, settleDeadlineMs_))
    {
        return;
    }

    busy_ = false;
    moveCompleted_ = true;
}

bool ServoLift::moveUp()
{
    if (!Calibration::servoConfigured())
    {
        return false;
    }

    return startMove(Calibration::SERVO_UP_ANGLE);
}

bool ServoLift::moveDown()
{
    if (!Calibration::servoConfigured())
    {
        return false;
    }

    return startMove(Calibration::SERVO_DOWN_ANGLE);
}

bool ServoLift::moveToAngle(int angle)
{
    return startMove(angle);
}

bool ServoLift::isAttached() const
{
    return attached_;
}

bool ServoLift::isBusy() const
{
    return busy_;
}

bool ServoLift::isUp() const
{
    if (!Calibration::servoConfigured())
    {
        return false;
    }

    return attached_ &&
           !busy_ &&
           commandedAngle_ == Calibration::SERVO_UP_ANGLE;
}

bool ServoLift::isDown() const
{
    if (!Calibration::servoConfigured())
    {
        return false;
    }

    return attached_ &&
           !busy_ &&
           commandedAngle_ == Calibration::SERVO_DOWN_ANGLE;
}

bool ServoLift::takeMoveCompleted()
{
    const bool completed = moveCompleted_;
    moveCompleted_ = false;

    return completed;
}

int ServoLift::currentCommandedAngle() const
{
    return commandedAngle_;
}

bool ServoLift::startMove(int angle)
{
    if (angle < 0 || angle > 180)
    {
        return false;
    }

    if (!attached_)
    {
        servo_.setPeriodHertz(
            Calibration::SERVO_FREQUENCY_HZ
        );

        servo_.attach(
            pin_,
            Calibration::SERVO_MIN_PULSE_US,
            Calibration::SERVO_MAX_PULSE_US
        );

        attached_ = servo_.attached();

        if (!attached_)
        {
            return false;
        }
    }

    servo_.write(angle);

    commandedAngle_ = angle;
    busy_ = true;
    moveCompleted_ = false;

    settleDeadlineMs_ =
        millis() + Calibration::SERVO_SETTLE_MS;

    return true;
}

bool ServoLift::timeReached(
    uint32_t now,
    uint32_t target
)
{
    return static_cast<int32_t>(now - target) >= 0;
}