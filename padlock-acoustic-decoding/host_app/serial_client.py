from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager

import serial

from config import CONFIG, SerialConfig
from device_discovery import find_serial_port
from models import (
    ConfigSnapshot,
    MessageType,
    SerialMessage,
    StatusSnapshot,
)
from protocol import (
    ProtocolError,
    build_ping_command,
    build_status_command,
    parse_message,
)


class SerialClientError(RuntimeError):
    pass


class SerialConnectionError(SerialClientError):
    pass


class SerialCancelledError(SerialClientError):
    pass


class SerialTimeoutError(SerialClientError):
    pass


class SerialProtocolError(SerialClientError):
    pass


class Esp32ResponseError(SerialClientError):
    def __init__(self, message: SerialMessage) -> None:
        detail = (
            f": {message.detail}"
            if message.detail
            else ""
        )

        super().__init__(
            f"ESP32 error {message.fault}{detail}"
        )

        self.message = message


class SerialClient(AbstractContextManager["SerialClient"]):
    def __init__(
        self,
        config: SerialConfig = CONFIG.serial,
        port: str | None = None,
    ) -> None:
        self._config = config
        self._requested_port = port

        self._serial: serial.Serial | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_reader = threading.Event()

        self._cancel_waits = threading.Event()

        self._messages: queue.Queue[SerialMessage] = (
            queue.Queue()
        )
        self._pending_messages: deque[SerialMessage] = deque()
        self._reader_errors: queue.Queue[BaseException] = (
            queue.Queue()
        )

        self._history: list[SerialMessage] = []
        self._history_lock = threading.Lock()
        self._raw_history: deque[str] = deque(maxlen=200)
        self._raw_history_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._wait_lock = threading.RLock()

    @property
    def port(self) -> str:
        if self._serial is not None:
            return str(self._serial.port)

        return self._requested_port or self._config.port

    @property
    def is_open(self) -> bool:
        return (
            self._serial is not None
            and self._serial.is_open
        )

    def open(self) -> None:
        if self.is_open:
            return

        port = (
            self._requested_port
            if self._requested_port is not None
            else find_serial_port(self._config)
        )

        self._clear_queues()
        self._stop_reader.clear()
        self._cancel_waits.clear()

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=self._config.baud_rate,
                timeout=self._config.read_timeout_s,
                write_timeout=self._config.write_timeout_s,
            )
        except serial.SerialException as exc:
            self._serial = None
            raise SerialConnectionError(
                f"Could not open serial port {port}: {exc}"
            ) from exc

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="esp32-serial-reader",
            daemon=True,
        )
        self._reader_thread.start()

        if self._config.startup_wait_s > 0:
            time.sleep(self._config.startup_wait_s)

        self._raise_reader_error()

    def close(self) -> None:
        self._stop_reader.set()

        thread = self._reader_thread

        if thread is not None and thread.is_alive():
            thread.join(
                timeout=max(
                    1.0,
                    self._config.read_timeout_s * 4,
                )
            )

        self._reader_thread = None

        port = self._serial
        self._serial = None

        if port is not None and port.is_open:
            try:
                port.close()
            except serial.SerialException:
                pass

    def __enter__(self) -> "SerialClient":
        self.open()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.close()

    def cancel_pending_waits(self) -> None:
        self._cancel_waits.set()

    def clear_cancel(self) -> None:
        self._cancel_waits.clear()

    def send_line(self, line: str) -> None:
        port = self._require_open_port()

        command = line.rstrip("\r\n")

        if not command:
            raise ValueError("Serial command cannot be empty")

        payload = f"{command}\n".encode("ascii")

        try:
            with self._write_lock:
                port.write(payload)
        except (
            serial.SerialException,
            serial.SerialTimeoutException,
        ) as exc:
            raise SerialConnectionError(
                f"Could not write to {self.port}: {exc}"
            ) from exc

    def read_message(
        self,
        timeout_s: float,
    ) -> SerialMessage | None:
        if timeout_s < 0:
            raise ValueError("timeout_s cannot be negative")

        with self._wait_lock:
            return self._read_message_unlocked(timeout_s)

    def wait_for(
        self,
        predicate: Callable[[SerialMessage], bool],
        timeout_s: float,
        description: str,
        collected: list[SerialMessage] | None = None,
        raise_on_esp_error: bool = True,
    ) -> SerialMessage:
        deadline = time.monotonic() + timeout_s
        deferred: deque[SerialMessage] = deque()

        # Keep one message consumer active at a time. Any message that does
        # not match this wait is restored in order instead of being discarded.
        # This matters when ACK and COMPLETED arrive in one USB packet or in an
        # unexpected order.
        with self._wait_lock:
            try:
                while True:
                    remaining = deadline - time.monotonic()

                    if remaining <= 0:
                        raise SerialTimeoutError(
                            f"Timed out waiting for {description}"
                        )

                    message = self._read_message_unlocked(remaining)

                    if message is None:
                        raise SerialTimeoutError(
                            f"Timed out waiting for {description}"
                        )

                    if collected is not None:
                        collected.append(message)

                    if (
                        raise_on_esp_error
                        and message.message_type
                        is MessageType.ERROR
                    ):
                        raise Esp32ResponseError(message)

                    if predicate(message):
                        return message

                    deferred.append(message)
            finally:
                while deferred:
                    self._pending_messages.appendleft(
                        deferred.pop()
                    )

    def wait_for_type(
        self,
        message_type: MessageType,
        timeout_s: float,
        *,
        name: str = "",
        run_id: str = "",
        collected: list[SerialMessage] | None = None,
        raise_on_esp_error: bool = True,
    ) -> SerialMessage:
        expected_name = name.upper()

        def matches(message: SerialMessage) -> bool:
            if message.message_type is not message_type:
                return False

            if (
                expected_name
                and message.name.upper() != expected_name
            ):
                return False

            if run_id and message.run_id != run_id:
                return False

            return True

        description = message_type.value

        if expected_name:
            description += f" {expected_name}"

        if run_id:
            description += f" for {run_id}"

        return self.wait_for(
            matches,
            timeout_s,
            description,
            collected,
            raise_on_esp_error,
        )

    def ping(
        self,
        timeout_s: float,
        collected: list[SerialMessage] | None = None,
    ) -> SerialMessage:
        self.send_line(build_ping_command())

        return self.wait_for_type(
            MessageType.ACK,
            timeout_s,
            name="PING",
            collected=collected,
        )

    def request_status(
        self,
        timeout_s: float,
        collected: list[SerialMessage] | None = None,
    ) -> tuple[StatusSnapshot, ConfigSnapshot]:
        self.send_line(build_status_command())

        status_message = self.wait_for_type(
            MessageType.STATUS,
            timeout_s,
            collected=collected,
        )

        config_message = self.wait_for_type(
            MessageType.CONFIG,
            timeout_s,
            collected=collected,
        )

        if status_message.status is None:
            raise SerialProtocolError(
                "STATUS message did not contain a snapshot"
            )

        if config_message.config is None:
            raise SerialProtocolError(
                "CONFIG message did not contain a snapshot"
            )

        return (
            status_message.status,
            config_message.config,
        )

    def drain_messages(self) -> list[SerialMessage]:
        drained: list[SerialMessage] = []

        with self._wait_lock:
            while self._pending_messages:
                drained.append(self._pending_messages.popleft())

            while True:
                try:
                    drained.append(
                        self._messages.get_nowait()
                    )
                except queue.Empty:
                    break

            self._raise_reader_error()
        return drained

    def recent_raw_lines(self, limit: int = 12) -> list[str]:
        if limit <= 0:
            return []

        with self._raw_history_lock:
            return list(self._raw_history)[-limit:]

    def diagnostic_summary(self) -> str:
        thread = self._reader_thread
        reader_state = (
            "alive"
            if thread is not None and thread.is_alive()
            else "stopped"
        )

        with self._wait_lock:
            pending_count = len(self._pending_messages)
            queued_count = self._messages.qsize()

        return (
            f"port={self.port}, open={self.is_open}, "
            f"reader={reader_state}, pending={pending_count}, "
            f"queued={queued_count}"
        )

    def history_mark(self) -> int:
        with self._history_lock:
            return len(self._history)

    def history_since(
        self,
        mark: int,
    ) -> list[SerialMessage]:
        if mark < 0:
            raise ValueError("History mark cannot be negative")

        with self._history_lock:
            return list(self._history[mark:])

    def history(self) -> list[SerialMessage]:
        return self.history_since(0)

    def _reader_loop(self) -> None:
        line_buffer = bytearray()

        while not self._stop_reader.is_set():
            port = self._serial

            if port is None or not port.is_open:
                return

            try:
                data = port.readline()
            except serial.SerialException as exc:
                if not self._stop_reader.is_set():
                    self._reader_errors.put(
                        SerialConnectionError(
                            f"Serial read failed: {exc}"
                        )
                    )
                return

            if not data:
                continue

            line_buffer.extend(data)

            while b"\n" in line_buffer:
                raw_line, _, remaining = (
                    line_buffer.partition(b"\n")
                )
                line_buffer = bytearray(remaining)

                text = raw_line.rstrip(b"\r").decode(
                    "utf-8",
                    errors="replace",
                )

                if not text.strip():
                    continue

                received_at_ns = time.perf_counter_ns()

                with self._raw_history_lock:
                    self._raw_history.append(text)

                try:
                    message = parse_message(
                        text,
                        pc_time_ns=received_at_ns,
                    )
                except ProtocolError as exc:
                    # A single malformed/debug line must not poison all later
                    # waits and leave the UI locked until a long timeout.
                    message = SerialMessage(
                        message_type=MessageType.UNKNOWN,
                        raw=text,
                        pc_time_ns=received_at_ns,
                        name="MALFORMED",
                        detail=str(exc),
                    )

                with self._history_lock:
                    self._history.append(message)

                self._messages.put(message)

    def _require_open_port(self) -> serial.Serial:
        if self._serial is None or not self._serial.is_open:
            raise SerialConnectionError(
                "Serial port is not open"
            )

        return self._serial

    def _raise_reader_error(self) -> None:
        try:
            error = self._reader_errors.get_nowait()
        except queue.Empty:
            return

        if isinstance(error, BaseException):
            raise error

        raise SerialClientError(str(error))

    def _read_message_unlocked(
        self,
        timeout_s: float,
    ) -> SerialMessage | None:
        deadline = time.monotonic() + timeout_s

        while True:
            self._raise_reader_error()

            if self._cancel_waits.is_set():
                raise SerialCancelledError(
                    "Serial wait cancelled"
                )

            if self._pending_messages:
                return self._pending_messages.popleft()

            remaining = deadline - time.monotonic()

            if remaining <= 0:
                return None

            try:
                return self._messages.get(
                    timeout=min(remaining, 0.1)
                )
            except queue.Empty:
                continue

    def _clear_queues(self) -> None:
        with self._wait_lock:
            self._pending_messages.clear()

        while not self._messages.empty():
            try:
                self._messages.get_nowait()
            except queue.Empty:
                break

        while not self._reader_errors.empty():
            try:
                self._reader_errors.get_nowait()
            except queue.Empty:
                break

        with self._history_lock:
            self._history.clear()

        with self._raw_history_lock:
            self._raw_history.clear()
