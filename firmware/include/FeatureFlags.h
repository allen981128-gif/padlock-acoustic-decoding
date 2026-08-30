#pragma once

namespace FeatureFlags
{
    // Hardware verification
    constexpr bool LIMIT_SWITCH_VERIFIED = true;

    // Automatic data collection
    constexpr bool AUTO_ACQUISITION_ENABLED = true;

    // Manual test commands
    constexpr bool ALLOW_WHEEL_JOG = true;
    constexpr bool ALLOW_SHORT_RAIL_JOG = true;
    constexpr bool ALLOW_SERVO_TEST = true;

    // Serial debug messages
    constexpr bool ENABLE_DEBUG_OUTPUT = true;
}