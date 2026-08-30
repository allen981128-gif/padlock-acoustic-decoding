#pragma once

#include <Arduino.h>

class LimitSwitch
{
public:
    LimitSwitch(
        uint8_t pin,
        uint8_t triggeredLevel
    );

    void begin();
    void update();

    bool rawTriggered() const;
    bool isTriggered() const;

    bool takeStateChanged();

private:
    uint8_t pin_;
    uint8_t triggeredLevel_;

    bool initialized_ = false;
    bool rawTriggered_ = false;
    bool stableTriggered_ = false;
    bool stateChanged_ = false;

    uint32_t rawChangedAtMs_ = 0;
};