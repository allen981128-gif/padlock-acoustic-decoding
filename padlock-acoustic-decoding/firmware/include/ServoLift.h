#pragma once

#include <Arduino.h>
#include <ESP32Servo.h>

class ServoLift
{
public:
    explicit ServoLift(uint8_t pin);

    void begin();
    void update();

    bool moveUp();
    bool moveDown();
    bool moveToAngle(int angle);

    bool isAttached() const;
    bool isBusy() const;
    bool isUp() const;
    bool isDown() const;

    bool takeMoveCompleted();

    int currentCommandedAngle() const;

private:
    bool startMove(int angle);
    static bool timeReached(uint32_t now, uint32_t target);

    uint8_t pin_;
    Servo servo_;

    bool attached_ = false;
    bool busy_ = false;
    bool moveCompleted_ = false;

    int commandedAngle_ = -1;
    uint32_t settleDeadlineMs_ = 0;
};