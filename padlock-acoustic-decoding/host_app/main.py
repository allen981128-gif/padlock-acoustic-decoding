from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from acquisition_controller import AcquisitionController
from audio_recorder import AudioRecorder, AudioRecorderError
from config import CONFIG, ensure_storage_directories
from device_discovery import (
    DeviceDiscoveryError,
    find_audio_input,
    find_serial_port,
    print_devices,
)
from models import RunStatus
from quality_control import QualityControl
from run_writer import RunWriter
from serial_client import SerialClient, SerialClientError
from session_controller import (
    CollectionPlanError,
    SessionController,
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Padlock audio data collector"
    )

    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List serial and audio devices",
    )

    parser.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session folder name",
    )

    parser.add_argument(
        "--plan",
        type=Path,
        default=None,
        help="Collection plan CSV path",
    )

    parser.add_argument(
        "--serial-port",
        type=str,
        default=None,
        help="ESP32 serial port",
    )

    parser.add_argument(
        "--audio-device",
        type=int,
        default=None,
        help="Focusrite input device index",
    )

    parser.add_argument(
        "--expected-final-step",
        type=int,
        default=None,
        help="Expected wheel steps per digit",
    )

    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run without confirmation between runs",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_arguments()

    if args.list_devices:
        print_devices()
        return 0

    if (
        args.expected_final_step is not None
        and args.expected_final_step <= 0
    ):
        print(
            "Configuration error: "
            "--expected-final-step must be positive"
        )
        return 1

    app_config = CONFIG

    if args.continuous:
        app_config = replace(
            app_config,
            session=replace(
                app_config.session,
                require_confirmation=False,
            ),
        )

    ensure_storage_directories(app_config)

    try:
        serial_port = (
            args.serial_port
            if args.serial_port is not None
            else find_serial_port(app_config.serial)
        )

        audio_device = (
            args.audio_device
            if args.audio_device is not None
            else find_audio_input(
                app_config.audio
            ).index
        )

        print(f"Serial port: {serial_port}")
        print(f"Audio device index: {audio_device}")

        with SerialClient(
            config=app_config.serial,
            port=serial_port,
        ) as serial_client:
            audio_recorder = AudioRecorder(
                config=app_config.audio,
                device_index=audio_device,
            )

            run_writer = RunWriter(
                storage_config=app_config.storage,
                audio_config=app_config.audio,
            )

            quality_control = QualityControl(
                config=app_config.quality,
            )

            acquisition_controller = (
                AcquisitionController(
                    serial_client=serial_client,
                    audio_recorder=audio_recorder,
                    run_writer=run_writer,
                    quality_control=quality_control,
                    config=app_config,
                    expected_final_step=(
                        args.expected_final_step
                    ),
                )
            )

            session_controller = SessionController(
                acquisition_controller=(
                    acquisition_controller
                ),
                config=app_config,
            )

            results = session_controller.run_session(
                session_id=args.session_id,
                plan_path=args.plan,
            )

    except KeyboardInterrupt:
        print()
        print("Collection stopped by operator")
        return 130

    except (
        AudioRecorderError,
        CollectionPlanError,
        DeviceDiscoveryError,
        SerialClientError,
        ValueError,
    ) as exc:
        print(f"Collection error: {exc}")
        return 1

    valid_count = sum(
        result.status is RunStatus.VALID
        for result in results
    )

    rejected_count = sum(
        result.status is RunStatus.REJECTED
        for result in results
    )

    failed_count = len(results) - (
        valid_count + rejected_count
    )

    print()
    print("Session finished")
    print(f"Valid runs: {valid_count}")
    print(f"Rejected runs: {rejected_count}")
    print(f"Failed or aborted runs: {failed_count}")

    return 0 if rejected_count == 0 and failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
