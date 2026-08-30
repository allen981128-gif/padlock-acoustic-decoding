from __future__ import annotations

from dataclasses import dataclass

import serial.tools.list_ports
import sounddevice as sd

from config import CONFIG, AudioConfig, SerialConfig


class DeviceDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str
    hardware_id: str
    manufacturer: str
    product: str
    serial_number: str


@dataclass(frozen=True)
class AudioInputInfo:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    default_sample_rate: float


def list_serial_ports() -> list[SerialPortInfo]:
    ports: list[SerialPortInfo] = []

    for port in serial.tools.list_ports.comports():
        ports.append(
            SerialPortInfo(
                device=port.device,
                description=port.description or "",
                hardware_id=port.hwid or "",
                manufacturer=port.manufacturer or "",
                product=port.product or "",
                serial_number=port.serial_number or "",
            )
        )

    return sorted(
        ports,
        key=lambda item: item.device.lower(),
    )


def find_serial_port(
    config: SerialConfig = CONFIG.serial,
) -> str:
    ports = list_serial_ports()

    for port in ports:
        if port.device.lower() == config.port.lower():
            return port.device

    available = ", ".join(
        port.device for port in ports
    ) or "none"

    raise DeviceDiscoveryError(
        f"Serial port {config.port} was not found. "
        f"Available ports: {available}"
    )


def list_audio_inputs() -> list[AudioInputInfo]:
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()

    inputs: list[AudioInputInfo] = []

    for index, device in enumerate(devices):
        max_channels = int(
            device["max_input_channels"]
        )

        if max_channels <= 0:
            continue

        host_index = int(device["hostapi"])
        host_name = str(
            host_apis[host_index]["name"]
        )

        inputs.append(
            AudioInputInfo(
                index=index,
                name=str(device["name"]),
                host_api=host_name,
                max_input_channels=max_channels,
                default_sample_rate=float(
                    device["default_samplerate"]
                ),
            )
        )

    return inputs


def find_audio_input(
    config: AudioConfig = CONFIG.audio,
) -> AudioInputInfo:
    search_text = config.device_name.casefold()

    matches = [
        device
        for device in list_audio_inputs()
        if search_text in device.name.casefold()
    ]

    if not matches:
        raise DeviceDiscoveryError(
            f"No audio input matched "
            f"{config.device_name!r}"
        )

    supported = [
        device
        for device in matches
        if _supports_audio_config(device, config)
    ]

    if not supported:
        names = ", ".join(
            f"{device.index}: {device.name} "
            f"({device.host_api})"
            for device in matches
        )

        raise DeviceDiscoveryError(
            "Matching audio devices do not support "
            f"{config.sample_rate} Hz, "
            f"{config.capture_channels} channel(s), "
            f"{config.dtype}. Matches: {names}"
        )

    supported.sort(
        key=lambda device: (
            _host_api_priority(device.host_api),
            device.index,
        )
    )

    return supported[0]


def check_devices() -> tuple[str, AudioInputInfo]:
    serial_port = find_serial_port()
    audio_input = find_audio_input()

    return serial_port, audio_input


def print_devices() -> None:
    print("Serial ports:")

    serial_ports = list_serial_ports()

    if not serial_ports:
        print("  None")

    for port in serial_ports:
        description = (
            f" - {port.description}"
            if port.description
            else ""
        )
        print(f"  {port.device}{description}")

    print()
    print("Audio inputs:")

    audio_inputs = list_audio_inputs()

    if not audio_inputs:
        print("  None")

    for device in audio_inputs:
        print(
            f"  {device.index}: {device.name} "
            f"[{device.host_api}] "
            f"channels={device.max_input_channels} "
            f"default={device.default_sample_rate:.0f} Hz"
        )


def _supports_audio_config(
    device: AudioInputInfo,
    config: AudioConfig,
) -> bool:
    if device.max_input_channels < config.capture_channels:
        return False

    try:
        sd.check_input_settings(
            device=device.index,
            channels=config.capture_channels,
            dtype=config.dtype,
            samplerate=config.sample_rate,
        )
    except (sd.PortAudioError, ValueError):
        return False

    return True


def _host_api_priority(host_api: str) -> int:
    name = host_api.casefold()

    priorities = (
        "asio",
        "wasapi",
        "wdm-ks",
        "core audio",
        "alsa",
        "directsound",
        "mme",
    )

    for priority, value in enumerate(priorities):
        if value in name:
            return priority

    return len(priorities)


def main() -> None:
    print_devices()
    print()

    try:
        serial_port, audio_input = check_devices()
    except DeviceDiscoveryError as exc:
        print(f"Configuration error: {exc}")
        raise SystemExit(1) from exc

    print(f"Selected serial port: {serial_port}")
    print(
        "Selected audio input: "
        f"{audio_input.index}: {audio_input.name} "
        f"[{audio_input.host_api}]"
    )


if __name__ == "__main__":
    main()
