#pragma once

#include <Arduino.h>

namespace Pins
{
    // Wheel motor — restored to the previously working wiring.
    constexpr uint8_t WHEEL_EN   = 11;
    constexpr uint8_t WHEEL_STEP = 12;
    constexpr uint8_t WHEEL_DIR  = 13;

    // Rail motor — restored to the previously working wiring.
    constexpr uint8_t RAIL_EN   = 6;
    constexpr uint8_t RAIL_STEP = 9;
    constexpr uint8_t RAIL_DIR  = 10;

    // Servo signal
    constexpr uint8_t SERVO = 5;

    // Rail limit switch
    constexpr uint8_t RAIL_LIMIT = 18;
}

namespace LogicLevels
{
    constexpr uint8_t DRIVER_ENABLE  = LOW;
    constexpr uint8_t DRIVER_DISABLE = HIGH;

    constexpr uint8_t STEP_IDLE   = LOW;
    constexpr uint8_t STEP_ACTIVE = HIGH;

    constexpr uint8_t LIMIT_RELEASED  = LOW;
    constexpr uint8_t LIMIT_TRIGGERED = HIGH;
}

namespace Communication
{
    constexpr uint32_t SERIAL_BAUD = 115200;
    constexpr size_t SERIAL_RX_BUFFER_SIZE = 128;
    constexpr char LINE_TERMINATOR = '\n';
}
