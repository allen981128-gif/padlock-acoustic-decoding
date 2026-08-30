#include <Arduino.h>

#include "AcquisitionFlow.h"
#include "Calibration.h"
#include "HardwareConfig.h"
#include "LimitSwitch.h"
#include "RailController.h"
#include "SafetyController.h"
#include "SerialProtocol.h"
#include "ServoLift.h"
#include "StepperAxis.h"
#include "WheelController.h"

namespace
{
StepperAxis wheelAxis(
    Pins::WHEEL_EN,
    Pins::WHEEL_STEP,
    Pins::WHEEL_DIR,
    Calibration::WHEEL_CW_IS_HIGH
);

StepperAxis railAxis(
    Pins::RAIL_EN,
    Pins::RAIL_STEP,
    Pins::RAIL_DIR,
    Calibration::RAIL_FORWARD_IS_HIGH
);

LimitSwitch railLimit(
    Pins::RAIL_LIMIT,
    LogicLevels::LIMIT_TRIGGERED
);

ServoLift servoLift(Pins::SERVO);

WheelController wheelController(wheelAxis);

RailController railController(
    railAxis,
    railLimit
);

SerialProtocol serialProtocol(Serial);

SafetyController safetyController(
    wheelController,
    railController,
    servoLift,
    railLimit
);

AcquisitionFlow acquisitionFlow(
    wheelController,
    railController,
    servoLift,
    railLimit,
    serialProtocol,
    safetyController
);

void setSafeBootOutputs()
{
    // Disable the wheel driver
    pinMode(Pins::WHEEL_EN, OUTPUT);
    digitalWrite(
        Pins::WHEEL_EN,
        LogicLevels::DRIVER_DISABLE
    );

    pinMode(Pins::WHEEL_STEP, OUTPUT);
    digitalWrite(
        Pins::WHEEL_STEP,
        LogicLevels::STEP_IDLE
    );

    pinMode(Pins::WHEEL_DIR, OUTPUT);
    digitalWrite(Pins::WHEEL_DIR, LOW);

    // Disable the rail driver
    pinMode(Pins::RAIL_EN, OUTPUT);
    digitalWrite(
        Pins::RAIL_EN,
        LogicLevels::DRIVER_DISABLE
    );

    pinMode(Pins::RAIL_STEP, OUTPUT);
    digitalWrite(
        Pins::RAIL_STEP,
        LogicLevels::STEP_IDLE
    );

    pinMode(Pins::RAIL_DIR, OUTPUT);
    digitalWrite(Pins::RAIL_DIR, LOW);
}
}

void setup()
{
    setSafeBootOutputs();

    Serial.begin(Communication::SERIAL_BAUD);

    const uint32_t waitStartedAt = millis();

    while (!Serial &&
           millis() - waitStartedAt < 3000)
    {
        delay(10);
    }

    acquisitionFlow.begin();
}

void loop()
{
    acquisitionFlow.update();

    static uint32_t lastYieldMs = 0;
    const uint32_t now = millis();

    if (now - lastYieldMs >= 100)
    {
        lastYieldMs = now;
        delay(1);
    }
}