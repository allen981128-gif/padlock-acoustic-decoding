from __future__ import annotations

import queue
import threading
import time

import numpy as np
import sounddevice as sd

from config import CONFIG, AudioConfig
from device_discovery import (
    AudioInputInfo,
    find_audio_input,
)
from models import AudioResult


class AudioRecorderError(RuntimeError):
    pass


class AudioRecorderStateError(AudioRecorderError):
    pass


class AudioRecorder:
    def __init__(
        self,
        config: AudioConfig = CONFIG.audio,
        device_index: int | None = None,
    ) -> None:
        self._config = config
        self._requested_device_index = device_index
        self._target_channel = int(config.target_channel)
        self._reference_channel = int(config.reference_channel)

        self._device: AudioInputInfo | None = None
        self._stream: sd.InputStream | None = None

        self._blocks: queue.Queue[np.ndarray] = (
            queue.Queue()
        )

        self._status_lock = threading.Lock()
        self._statuses: list[str] = []
        self._overflowed = False

        self._recording = False
        self._started_at_ns = 0
        self._stopped_at_ns = 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def device(self) -> AudioInputInfo | None:
        return self._device

    def start(self) -> None:
        if self._recording:
            raise AudioRecorderStateError(
                "Audio recording is already active"
            )

        self._reset_capture()

        if self._requested_device_index is None:
            self._device = find_audio_input(
                self._config
            )
        else:
            self._device = self._read_device_info(
                self._requested_device_index
            )

        selected_channels = (
            self._target_channel,
            self._reference_channel,
        )

        if self._target_channel == self._reference_channel:
            raise AudioRecorderError(
                "Target and reference input channels must be different"
            )

        if any(
            channel < 0 or channel >= self._config.capture_channels
            for channel in selected_channels
        ):
            raise AudioRecorderError(
                "Target or reference input channel is outside the "
                "configured capture-channel range"
            )

        try:
            sd.check_input_settings(
                device=self._device.index,
                channels=self._config.capture_channels,
                dtype=self._config.dtype,
                samplerate=self._config.sample_rate,
            )

            self._stream = sd.InputStream(
                device=self._device.index,
                samplerate=self._config.sample_rate,
                channels=self._config.capture_channels,
                dtype=self._config.dtype,
                blocksize=self._config.block_size,
                callback=self._audio_callback,
            )

            self._stream.start()
            self._started_at_ns = (
                time.perf_counter_ns()
            )
            self._recording = True

        except (
            sd.PortAudioError,
            ValueError,
        ) as exc:
            self._close_stream()

            raise AudioRecorderError(
                f"Could not start audio recording: {exc}"
            ) from exc

    def stop(self) -> AudioResult:
        if not self._recording:
            raise AudioRecorderStateError(
                "Audio recording is not active"
            )

        try:
            if self._stream is not None:
                self._stream.stop()
        except sd.PortAudioError as exc:
            self._close_stream()
            self._recording = False

            raise AudioRecorderError(
                f"Could not stop audio recording: {exc}"
            ) from exc

        self._stopped_at_ns = time.perf_counter_ns()
        self._recording = False
        self._close_stream()

        samples = self._collect_samples()

        with self._status_lock:
            statuses = list(self._statuses)
            overflowed = self._overflowed

        return AudioResult(
            samples=samples,
            sample_rate=self._config.sample_rate,
            channels=2,
            started_at_ns=self._started_at_ns,
            stopped_at_ns=self._stopped_at_ns,
            statuses=statuses,
            overflowed=overflowed,
        )

    def abort(self) -> None:
        if self._stream is not None:
            try:
                if self._stream.active:
                    self._stream.abort()
            except sd.PortAudioError:
                pass

        self._recording = False
        self._stopped_at_ns = time.perf_counter_ns()
        self._close_stream()
        self._reset_capture()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        del frames
        del time_info

        if status:
            with self._status_lock:
                self._statuses.append(str(status))

                if status.input_overflow:
                    self._overflowed = True

        dual = indata[
            :, [self._target_channel, self._reference_channel]
        ]

        self._blocks.put(dual.copy())

    def _collect_samples(self) -> np.ndarray:
        blocks: list[np.ndarray] = []

        while True:
            try:
                blocks.append(
                    self._blocks.get_nowait()
                )
            except queue.Empty:
                break

        if not blocks:
            return np.empty(
                (0, 2),
                dtype=np.float32,
            )

        samples = np.concatenate(
            blocks,
            axis=0,
        )

        return np.asarray(
            samples,
            dtype=np.float32,
        )

    def _read_device_info(
        self,
        device_index: int,
    ) -> AudioInputInfo:
        try:
            device = sd.query_devices(
                device_index,
                "input",
            )
            host_api = sd.query_hostapis(
                int(device["hostapi"])
            )
        except (
            sd.PortAudioError,
            ValueError,
        ) as exc:
            raise AudioRecorderError(
                f"Invalid audio device {device_index}: {exc}"
            ) from exc

        max_channels = int(
            device["max_input_channels"]
        )

        if max_channels < self._config.capture_channels:
            raise AudioRecorderError(
                f"Audio device {device_index} only "
                f"supports {max_channels} input channel(s); "
                f"{self._config.capture_channels} are required"
            )

        return AudioInputInfo(
            index=device_index,
            name=str(device["name"]),
            host_api=str(host_api["name"]),
            max_input_channels=max_channels,
            default_sample_rate=float(
                device["default_samplerate"]
            ),
        )

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None

        if stream is None:
            return

        try:
            stream.close()
        except sd.PortAudioError:
            pass

    def _reset_capture(self) -> None:
        while True:
            try:
                self._blocks.get_nowait()
            except queue.Empty:
                break

        with self._status_lock:
            self._statuses.clear()
            self._overflowed = False

        self._started_at_ns = 0
        self._stopped_at_ns = 0
