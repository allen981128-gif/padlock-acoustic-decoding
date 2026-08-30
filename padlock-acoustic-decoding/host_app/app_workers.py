from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from app_backend import PadlockBackend
from models import RunRequest, RunResult


class TaskWorker(QObject):
    result = Signal(object)
    error = Signal(str)
    log = Signal(str)
    finished = Signal()

    def __init__(self, function: Callable[..., Any]) -> None:
        super().__init__()
        self._function = function

    @Slot()
    def run(self) -> None:
        try:
            result = self._function(self.log.emit)
            self.result.emit(result)
        except Exception as exc:
            self.error.emit(
                f"{type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            )
        finally:
            self.finished.emit()


class CollectionWorker(QObject):
    log = Signal(str)
    state_changed = Signal(str)
    progress = Signal(int, int, object)
    result_ready = Signal(int, object)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        backend: PadlockBackend,
        *,
        requests: Sequence[RunRequest],
        dataset_dir: Path,
        pre_roll_s: float,
        post_roll_s: float,
        pause_between_runs_s: float,
        stop_on_rejected: bool,
        keep_contact_between_digits: bool,
        stop_after_result: Callable[[int, RunResult], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._requests = list(requests)
        self._dataset_dir = dataset_dir
        self._pre_roll_s = pre_roll_s
        self._post_roll_s = post_roll_s
        self._pause_between_runs_s = pause_between_runs_s
        self._stop_on_rejected = stop_on_rejected
        self._keep_contact_between_digits = keep_contact_between_digits
        self._stop_after_result = stop_after_result

    @Slot()
    def run(self) -> None:
        try:
            results: list[RunResult] = self._backend.collect_batch(
                requests=self._requests,
                dataset_dir=self._dataset_dir,
                pre_roll_s=self._pre_roll_s,
                post_roll_s=self._post_roll_s,
                pause_between_runs_s=self._pause_between_runs_s,
                stop_on_rejected=self._stop_on_rejected,
                keep_contact_between_digits=self._keep_contact_between_digits,
                log=self.log.emit,
                state_changed=self.state_changed.emit,
                progress=self.progress.emit,
                result_ready=self.result_ready.emit,
                stop_after_result=self._stop_after_result,
            )
            self.completed.emit(results)
        except Exception as exc:
            self.error.emit(
                f"{type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()}"
            )
        finally:
            self.finished.emit()
