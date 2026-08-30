# ESP32-S3 firmware

PlatformIO project for the mechanical actuation controller.

## Target

- Board: Adafruit Feather ESP32-S3
- Framework: Arduino
- Serial monitor: 115200 baud
- Library: `madhephaestus/ESP32Servo`

## Build

From this directory:

```bash
pio run
```

Upload through PlatformIO using the connected Feather ESP32-S3.

The repository deliberately excludes `.pio/` generated build output and machine-specific VS Code configuration.
