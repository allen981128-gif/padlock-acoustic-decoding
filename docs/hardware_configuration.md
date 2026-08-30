# Hardware configuration

This note records the command-level hardware settings reproduced from the final source tree.

## Controller and GPIO

| Function | GPIO / logic |
|---|---:|
| Wheel motor EN | GPIO11 |
| Wheel motor STEP | GPIO12 |
| Wheel motor DIR | GPIO13 |
| Rail motor EN | GPIO6 |
| Rail motor STEP | GPIO9 |
| Rail motor DIR | GPIO10 |
| Servo signal | GPIO5 |
| Rail limit signal | GPIO18 |
| Driver enable | active-low |
| STEP idle | LOW |
| Limit released / triggered | LOW / HIGH |
| USB serial | 115200 baud |

## Motion calibration

| Parameter | Final source value |
|---|---:|
| Wheel steps per revolution | 1710 |
| Wheel steps per digit | 171 |
| Wheel step interval | 1600 us |
| STEP pulse width | 4 us |
| Driver-enable settling | 500 us |
| Rail normal step interval | 100 us |
| Homing fast interval | 200 us |
| Homing slow interval | 900 us |
| Homing backoff | 600 steps |
| Rail W1/W2/W3/W4 positions | 49500 / 62000 / 74400 / 87700 steps |
| Limit debounce | 15 ms |
| Rail settling | 100 ms |
| Servo up / down | 80 / 120 degrees |
| Servo settling | 500 ms |
| Servo PWM | 50 Hz |

## Acoustic acquisition

- 2 x AD-35 contact sensors.
- Focusrite 2i2 dual-channel interface.
- Channel 1: lock-target sensor.
- Channel 2: motor-reference sensor.
- 44.1 kHz, 24-bit PCM WAV.
- Instrument mode.
- Phantom power off.
- AIR off.
- Standard pre-roll 0.5 s.
- Standard post-roll 0.7 s.

## Reproducibility boundary

The final record does not reliably preserve TMC2209 microstepping/current-limit/Vref or the absolute Focusrite gain-knob position. These values are not reconstructed retrospectively.
