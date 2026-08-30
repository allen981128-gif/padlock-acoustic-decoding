#pragma once

#include <Arduino.h>
#include <limits.h>

namespace Calibration
{
    constexpr int INVALID_ANGLE = -1;
    constexpr long INVALID_POSITION = LONG_MIN;

    constexpr uint8_t LOCK_WHEEL_COUNT = 4;
    constexpr uint8_t DIGIT_COUNT = 10;

    // Servo settings
    constexpr uint16_t SERVO_FREQUENCY_HZ = 50;
    constexpr uint16_t SERVO_MIN_PULSE_US = 500;
    constexpr uint16_t SERVO_MAX_PULSE_US = 2500;

    constexpr int SERVO_UP_ANGLE = 80;
    constexpr int SERVO_DOWN_ANGLE = 120;

    constexpr uint32_t SERVO_SETTLE_MS = 500;

    // Stepper settings
    constexpr uint32_t STEP_PULSE_WIDTH_US = 4;

    // Give the driver/rotor a short settling period only when the power stage
    // transitions from disabled to enabled. Consecutive digit moves that keep
    // the wheel driver enabled do not pay this delay again.
    constexpr uint32_t DRIVER_ENABLE_SETTLE_US = 500;

    constexpr uint32_t WHEEL_STEP_INTERVAL_US = 1600;
    constexpr uint32_t RAIL_STEP_INTERVAL_US = 100;

    constexpr uint32_t HOME_FAST_STEP_INTERVAL_US = 200;
    constexpr uint32_t HOME_SLOW_STEP_INTERVAL_US = 900;

    // Direction settings
    constexpr bool WHEEL_CW_IS_HIGH = true;
    constexpr bool RAIL_FORWARD_IS_HIGH = true;
    constexpr bool RAIL_HOME_IS_FORWARD = true;

    // Unified wheel calibration validated on the current mechanism.
    // One visible digit = 171 motor steps; one full revolution = 1710 steps.
    constexpr uint32_t WHEEL_STEPS_PER_REV = 1710;
    constexpr uint32_t WHEEL_STEPS_PER_DIGIT =
        WHEEL_STEPS_PER_REV / DIGIT_COUNT;

    // Binding Sweep uses the same physical calibration as digit moves.
    constexpr uint32_t BINDING_SWEEP_STEPS_PER_REV =
        WHEEL_STEPS_PER_REV;
    constexpr uint32_t BINDING_SWEEP_STEPS_PER_SECTOR =
        BINDING_SWEEP_STEPS_PER_REV / DIGIT_COUNT;

    // Controlled reference sweep: eight CCW digit sectors, excluding the
    // transition into and out of the known true gate.
    constexpr uint8_t BINDING_REFERENCE_SWEEP_SECTOR_COUNT = 8;
    constexpr uint32_t BINDING_REFERENCE_SWEEP_STEPS =
        BINDING_REFERENCE_SWEEP_SECTOR_COUNT * WHEEL_STEPS_PER_DIGIT;
    constexpr uint32_t BINDING_REFERENCE_SWEEP_SECTOR_STEPS =
        WHEEL_STEPS_PER_DIGIT;

    // Micro-probe calibration. The probe travels +A, -2A, +A.
    constexpr uint32_t PROBE_DEFAULT_AMPLITUDE_STEPS = 20;
    constexpr uint32_t PROBE_MIN_AMPLITUDE_STEPS = 5;
    constexpr uint32_t PROBE_MAX_AMPLITUDE_STEPS = 60;

    // Wide local probe: centre -> -A -> (+A <-> -A) x N -> centre.
    constexpr uint32_t WIDE_PROBE_DEFAULT_AMPLITUDE_STEPS = 65;
    constexpr uint32_t WIDE_PROBE_MIN_AMPLITUDE_STEPS = 20;
    constexpr uint32_t WIDE_PROBE_MAX_AMPLITUDE_STEPS = 80;
    constexpr uint8_t WIDE_PROBE_DEFAULT_CYCLES = 4;
    constexpr uint8_t WIDE_PROBE_MIN_CYCLES = 1;
    constexpr uint8_t WIDE_PROBE_MAX_CYCLES = 8;

    // Rail calibration
    constexpr long RAIL_WHEEL_POSITIONS[LOCK_WHEEL_COUNT] = {
        49500,
        62000,
        74400,
        87700
    };

    constexpr uint32_t HOME_BACKOFF_STEPS = 600;
    constexpr long RAIL_MAX_TRAVEL_STEPS = 100000;

    // Timing settings
    constexpr uint32_t LIMIT_DEBOUNCE_MS = 15;
    constexpr uint32_t RAIL_SETTLE_MS = 100;

    constexpr uint32_t HOME_TIMEOUT_MS = 180000;
    constexpr uint32_t RAIL_MOVE_TIMEOUT_MS = 180000;
    constexpr uint32_t SCAN_TIMEOUT_MS = 30000;
    constexpr uint32_t PROBE_TIMEOUT_MS = 30000;
    constexpr uint32_t RECORDING_WAIT_TIMEOUT_MS = 60000;

    // Manual test limits
    constexpr uint32_t MAX_WHEEL_JOG_STEPS = 2000;
    constexpr uint32_t MAX_RAIL_JOG_STEPS = 100000;

    inline bool servoConfigured()
    {
        return SERVO_UP_ANGLE >= 0 &&
               SERVO_UP_ANGLE <= 180 &&
               SERVO_DOWN_ANGLE >= 0 &&
               SERVO_DOWN_ANGLE <= 180 &&
               SERVO_UP_ANGLE != SERVO_DOWN_ANGLE;
    }

    inline bool wheelConfigured()
    {
        return WHEEL_STEPS_PER_REV >= DIGIT_COUNT &&
               WHEEL_STEPS_PER_REV % DIGIT_COUNT == 0 &&
               WHEEL_STEPS_PER_DIGIT > 0 &&
               BINDING_SWEEP_STEPS_PER_REV >= DIGIT_COUNT &&
               BINDING_SWEEP_STEPS_PER_REV % DIGIT_COUNT == 0 &&
               BINDING_SWEEP_STEPS_PER_SECTOR > 0 &&
               BINDING_REFERENCE_SWEEP_SECTOR_COUNT > 1 &&
               BINDING_REFERENCE_SWEEP_STEPS > 0 &&
               BINDING_REFERENCE_SWEEP_SECTOR_STEPS > 0;
    }

    inline bool probeAmplitudeValid(uint32_t amplitude)
    {
        return amplitude >= PROBE_MIN_AMPLITUDE_STEPS &&
               amplitude <= PROBE_MAX_AMPLITUDE_STEPS;
    }

    inline bool wideProbeValid(uint32_t amplitude, uint8_t cycles)
    {
        return amplitude >= WIDE_PROBE_MIN_AMPLITUDE_STEPS &&
               amplitude <= WIDE_PROBE_MAX_AMPLITUDE_STEPS &&
               cycles >= WIDE_PROBE_MIN_CYCLES &&
               cycles <= WIDE_PROBE_MAX_CYCLES;
    }

    inline bool railConfigured()
    {
        if (HOME_BACKOFF_STEPS == 0 ||
            RAIL_MAX_TRAVEL_STEPS <= 0)
        {
            return false;
        }

        for (uint8_t i = 0; i < LOCK_WHEEL_COUNT; ++i)
        {
            const long position = RAIL_WHEEL_POSITIONS[i];

            if (position == INVALID_POSITION ||
                position < 0 ||
                position > RAIL_MAX_TRAVEL_STEPS)
            {
                return false;
            }
        }

        return true;
    }

    inline bool acquisitionConfigured()
    {
        return servoConfigured() &&
               wheelConfigured() &&
               railConfigured();
    }
}
