#include "LimitSwitch.h"

#include "Calibration.h"

LimitSwitch::LimitSwitch(
    uint8_t pin,
    uint8_t triggeredLevel
)
    : pin_(pin),
      triggeredLevel_(triggeredLevel)
{
}

void LimitSwitch::begin()
{
    pinMode(pin_, INPUT);

    const bool triggered =
        digitalRead(pin_) == triggeredLevel_;

    rawTriggered_ = triggered;
    stableTriggered_ = triggered;

    stateChanged_ = false;
    rawChangedAtMs_ = millis();
    initialized_ = true;
}

void LimitSwitch::update()
{
    if (!initialized_)
    {
        return;
    }

    const uint32_t now = millis();

    const bool currentTriggered =
        digitalRead(pin_) == triggeredLevel_;

    // Restart debounce when the raw state changes
    if (currentTriggered != rawTriggered_)
    {
        rawTriggered_ = currentTriggered;
        rawChangedAtMs_ = now;
        return;
    }

    // Accept the new state after the debounce time
    if (rawTriggered_ != stableTriggered_ &&
        now - rawChangedAtMs_ >=
            Calibration::LIMIT_DEBOUNCE_MS)
    {
        stableTriggered_ = rawTriggered_;
        stateChanged_ = true;
    }
}

bool LimitSwitch::rawTriggered() const
{
    return rawTriggered_;
}

bool LimitSwitch::isTriggered() const
{
    return stableTriggered_;
}

bool LimitSwitch::takeStateChanged()
{
    const bool changed = stateChanged_;
    stateChanged_ = false;

    return changed;
}