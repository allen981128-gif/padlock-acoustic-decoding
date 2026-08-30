from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from acquisition_controller import AcquisitionController
from config import (
    CONFIG,
    AppConfig,
    ensure_storage_directories,
)
from models import RunRequest, RunResult, RunStatus


class CollectionPlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class CollectionPlanItem:
    wheel_index: int
    direction: str
    correct_digit: int
    start_digit: int

    scenario: str
    wheel_1_digit: int
    wheel_2_digit: int
    wheel_3_digit: int
    wheel_4_digit: int

    lock_id: str
    tape_version: str
    microphone_position: str
    focusrite_gain: str
    spring_setting: str

    repetitions: int
    notes: str
    source_row: int


class SessionController:
    def __init__(
        self,
        acquisition_controller: AcquisitionController,
        config: AppConfig = CONFIG,
    ) -> None:
        self._acquisition = acquisition_controller
        self._config = config

    def run_session(
        self,
        session_id: str | None = None,
        plan_path: Path | None = None,
    ) -> list[RunResult]:
        ensure_storage_directories(self._config)

        resolved_session_id = (
            session_id or self.create_session_id()
        )

        self._validate_session_id(
            resolved_session_id
        )

        plan = self.load_plan(plan_path)
        first_run_number = self._next_run_number(
            resolved_session_id
        )

        requests = self._build_requests(
            session_id=resolved_session_id,
            plan=plan,
            first_run_number=first_run_number,
        )

        if not requests:
            raise CollectionPlanError(
                "Collection plan produced no runs"
            )

        results: list[RunResult] = []

        for index, request in enumerate(
            requests,
            start=1,
        ):
            self._print_run_header(
                request=request,
                index=index,
                total=len(requests),
            )

            if (
                self._config.session.require_confirmation
                and not self._confirm_run()
            ):
                print("Session stopped by operator")
                break

            result = self._acquisition.collect_run(
                request
            )

            results.append(result)
            self._append_summary(result)
            self._print_result(result)

            if result.status is not RunStatus.VALID:
                print(
                    "Session stopped because the "
                    "current run was not valid"
                )
                break

            if (
                index < len(requests)
                and self._config.session.pause_between_runs_s
                > 0
            ):
                time.sleep(
                    self._config.session.pause_between_runs_s
                )

        return results

    def load_plan(
        self,
        plan_path: Path | None = None,
    ) -> list[CollectionPlanItem]:
        path = (
            plan_path
            if plan_path is not None
            else self._config.session.plan_file
        )

        if not path.exists():
            raise CollectionPlanError(
                f"Collection plan was not found: {path}"
            )

        required_fields = {
            "wheel_index",
            "direction",
            "correct_digit",
            "start_digit",
            "scenario",
            "wheel_1_digit",
            "wheel_2_digit",
            "wheel_3_digit",
            "wheel_4_digit",
            "lock_id",
            "tape_version",
            "microphone_position",
            "focusrite_gain",
            "spring_setting",
        }

        items: list[CollectionPlanItem] = []

        with path.open(
            "r",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            reader = csv.DictReader(file)

            if reader.fieldnames is None:
                raise CollectionPlanError(
                    "Collection plan has no header"
                )

            fieldnames = {
                name.strip()
                for name in reader.fieldnames
                if name is not None
            }

            missing = required_fields - fieldnames

            if missing:
                missing_text = ", ".join(
                    sorted(missing)
                )

                raise CollectionPlanError(
                    "Collection plan is missing: "
                    f"{missing_text}"
                )

            for row_number, row in enumerate(
                reader,
                start=2,
            ):
                if self._row_is_empty(row):
                    continue

                items.append(
                    self._parse_plan_row(
                        row=row,
                        row_number=row_number,
                    )
                )

        if not items:
            raise CollectionPlanError(
                "Collection plan contains no runs"
            )

        return items

    @staticmethod
    def create_session_id() -> str:
        return datetime.now().strftime(
            "session_%Y%m%d_%H%M%S"
        )

    def _build_requests(
        self,
        session_id: str,
        plan: list[CollectionPlanItem],
        first_run_number: int,
    ) -> list[RunRequest]:
        requests: list[RunRequest] = []
        run_number = first_run_number

        for item in plan:
            for repetition in range(
                1,
                item.repetitions + 1,
            ):
                requests.append(
                    RunRequest(
                        run_id=(
                            f"run_{run_number:06d}"
                        ),
                        session_id=session_id,
                        wheel_index=item.wheel_index,
                        direction=item.direction,
                        correct_digit=(
                            item.correct_digit
                        ),
                        start_digit=item.start_digit,
                        scenario=item.scenario,
                        wheel_1_digit=(
                            item.wheel_1_digit
                        ),
                        wheel_2_digit=(
                            item.wheel_2_digit
                        ),
                        wheel_3_digit=(
                            item.wheel_3_digit
                        ),
                        wheel_4_digit=(
                            item.wheel_4_digit
                        ),
                        lock_id=item.lock_id,
                        tape_version=(
                            item.tape_version
                        ),
                        microphone_position=(
                            item.microphone_position
                        ),
                        focusrite_gain=(
                            item.focusrite_gain
                        ),
                        spring_setting=(
                            item.spring_setting
                        ),
                        repetition=repetition,
                        notes=item.notes,
                    )
                )

                run_number += 1

        return requests

    def _parse_plan_row(
        self,
        row: dict[str, str | None],
        row_number: int,
    ) -> CollectionPlanItem:
        try:
            wheel_index = int(
                self._required_value(
                    row,
                    "wheel_index",
                    row_number,
                )
            )
            correct_digit = int(
                self._required_value(
                    row,
                    "correct_digit",
                    row_number,
                )
            )
            start_digit = int(
                self._required_value(
                    row,
                    "start_digit",
                    row_number,
                )
            )
            wheel_1_digit = int(
                self._required_value(
                    row,
                    "wheel_1_digit",
                    row_number,
                )
            )
            wheel_2_digit = int(
                self._required_value(
                    row,
                    "wheel_2_digit",
                    row_number,
                )
            )
            wheel_3_digit = int(
                self._required_value(
                    row,
                    "wheel_3_digit",
                    row_number,
                )
            )
            wheel_4_digit = int(
                self._required_value(
                    row,
                    "wheel_4_digit",
                    row_number,
                )
            )
        except ValueError as exc:
            raise CollectionPlanError(
                f"Invalid number in row {row_number}"
            ) from exc

        direction = self._required_value(
            row,
            "direction",
            row_number,
        ).upper()

        scenario = self._required_value(
            row,
            "scenario",
            row_number,
        )

        lock_id = self._required_value(
            row,
            "lock_id",
            row_number,
        )

        tape_version = self._required_value(
            row,
            "tape_version",
            row_number,
        )

        microphone_position = self._required_value(
            row,
            "microphone_position",
            row_number,
        )

        focusrite_gain = self._required_value(
            row,
            "focusrite_gain",
            row_number,
        )

        spring_setting = self._required_value(
            row,
            "spring_setting",
            row_number,
        )

        repetition_value = (
            row.get("repetitions")
            or row.get("repetition")
            or "1"
        )

        try:
            repetitions = int(
                repetition_value.strip()
            )
        except ValueError as exc:
            raise CollectionPlanError(
                f"Invalid repetitions in row "
                f"{row_number}"
            ) from exc

        notes = (row.get("notes") or "").strip()

        try:
            RunRequest(
                run_id="validation",
                session_id="validation",
                wheel_index=wheel_index,
                direction=direction,
                correct_digit=correct_digit,
                start_digit=start_digit,
                scenario=scenario,
                wheel_1_digit=wheel_1_digit,
                wheel_2_digit=wheel_2_digit,
                wheel_3_digit=wheel_3_digit,
                wheel_4_digit=wheel_4_digit,
                lock_id=lock_id,
                tape_version=tape_version,
                microphone_position=(
                    microphone_position
                ),
                focusrite_gain=focusrite_gain,
                spring_setting=spring_setting,
                repetition=1,
                notes=notes,
            )
        except ValueError as exc:
            raise CollectionPlanError(
                f"Invalid values in row "
                f"{row_number}: {exc}"
            ) from exc

        if repetitions < 1:
            raise CollectionPlanError(
                f"repetitions must be at least 1 "
                f"in row {row_number}"
            )

        return CollectionPlanItem(
            wheel_index=wheel_index,
            direction=direction,
            correct_digit=correct_digit,
            start_digit=start_digit,
            scenario=scenario,
            wheel_1_digit=wheel_1_digit,
            wheel_2_digit=wheel_2_digit,
            wheel_3_digit=wheel_3_digit,
            wheel_4_digit=wheel_4_digit,
            lock_id=lock_id,
            tape_version=tape_version,
            microphone_position=microphone_position,
            focusrite_gain=focusrite_gain,
            spring_setting=spring_setting,
            repetitions=repetitions,
            notes=notes,
            source_row=row_number,
        )

    def _next_run_number(
        self,
        session_id: str,
    ) -> int:
        highest = 0

        session_dirs = (
            self._config.storage.raw_dir
            / session_id,
            self._config.storage.rejected_dir
            / session_id,
        )

        for directory in session_dirs:
            if not directory.exists():
                continue

            for path in directory.iterdir():
                if (
                    not path.is_dir()
                    or not path.name.startswith(
                        "run_"
                    )
                ):
                    continue

                suffix = path.name[4:]

                if suffix.isdigit():
                    highest = max(
                        highest,
                        int(suffix),
                    )

        return highest + 1

    def _append_summary(
        self,
        result: RunResult,
    ) -> None:
        summary_path = (
            self._config.storage.logs_dir
            / (
                f"{result.request.session_id}"
                "_summary.csv"
            )
        )

        exists = summary_path.exists()

        fieldnames = [
            "run_id",
            "session_id",
            "wheel_index",
            "direction",
            "correct_digit",
            "start_digit",
            "end_digit",
            "action_type",
            "collection_mode",
            "tension_state",
            "probe_amplitude",
            "probe_cycles",
            "sweep_steps",
            "sector_steps",
            "current_code_before",
            "current_code_after",
            "scenario",
            "wheel_1_digit",
            "wheel_2_digit",
            "wheel_3_digit",
            "wheel_4_digit",
            "lock_id",
            "tape_version",
            "microphone_position",
            "focusrite_gain",
            "spring_setting",
            "repetition",
            "status",
            "quality_valid",
            "quality_errors",
            "output_dir",
            "error_message",
            "started_at_utc",
            "finished_at_utc",
        ]

        with summary_path.open(
            "a",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fieldnames,
            )

            if not exists:
                writer.writeheader()

            writer.writerow(
                {
                    "run_id": result.request.run_id,
                    "session_id": (
                        result.request.session_id
                    ),
                    "wheel_index": (
                        result.request.wheel_index
                    ),
                    "direction": (
                        result.request.direction
                    ),
                    "correct_digit": (
                        result.request.correct_digit
                    ),
                    "start_digit": (
                        result.request.start_digit
                    ),
                    "end_digit": result.request.end_digit,
                    "action_type": result.request.action_type,
                    "collection_mode": result.request.collection_mode,
                    "tension_state": result.request.tension_state,
                    "probe_amplitude": result.request.probe_amplitude,
                    "probe_cycles": result.request.probe_cycles,
                    "sweep_steps": result.request.sweep_steps,
                    "sector_steps": result.request.sector_steps,
                    "current_code_before": result.request.current_code_before,
                    "current_code_after": result.request.current_code_after,
                    "scenario": (
                        result.request.scenario
                    ),
                    "wheel_1_digit": (
                        result.request.wheel_1_digit
                    ),
                    "wheel_2_digit": (
                        result.request.wheel_2_digit
                    ),
                    "wheel_3_digit": (
                        result.request.wheel_3_digit
                    ),
                    "wheel_4_digit": (
                        result.request.wheel_4_digit
                    ),
                    "lock_id": (
                        result.request.lock_id
                    ),
                    "tape_version": (
                        result.request.tape_version
                    ),
                    "microphone_position": (
                        result.request.microphone_position
                    ),
                    "focusrite_gain": (
                        result.request.focusrite_gain
                    ),
                    "spring_setting": (
                        result.request.spring_setting
                    ),
                    "repetition": (
                        result.request.repetition
                    ),
                    "status": result.status.value,
                    "quality_valid": (
                        result.quality.valid
                        if result.quality is not None
                        else False
                    ),
                    "quality_errors": (
                        "|".join(
                            result.quality.errors
                        )
                        if result.quality is not None
                        else ""
                    ),
                    "output_dir": (
                        str(result.output_dir)
                        if result.output_dir
                        is not None
                        else ""
                    ),
                    "error_message": (
                        result.error_message
                    ),
                    "started_at_utc": (
                        result.started_at_utc
                    ),
                    "finished_at_utc": (
                        result.finished_at_utc
                    ),
                }
            )

    @staticmethod
    def _required_value(
        row: dict[str, str | None],
        field_name: str,
        row_number: int,
    ) -> str:
        value = row.get(field_name)

        if value is None or not value.strip():
            raise CollectionPlanError(
                f"Missing {field_name} in row "
                f"{row_number}"
            )

        return value.strip()

    @staticmethod
    def _row_is_empty(
        row: dict[str, str | None],
    ) -> bool:
        return not any(
            value is not None and value.strip()
            for value in row.values()
        )

    @staticmethod
    def _validate_session_id(
        session_id: str,
    ) -> None:
        if not session_id:
            raise CollectionPlanError(
                "session_id cannot be empty"
            )

        if len(session_id) >= 64:
            raise CollectionPlanError(
                "session_id is too long"
            )

        for character in session_id:
            if not (
                character.isalnum()
                or character in {"_", "-"}
            ):
                raise CollectionPlanError(
                    "session_id may only contain "
                    "letters, numbers, underscores "
                    "and hyphens"
                )

    @staticmethod
    def _confirm_run() -> bool:
        response = input(
            "Press Enter to start this run, "
            "or enter Q to stop: "
        ).strip()

        return response.casefold() != "q"

    @staticmethod
    def _print_run_header(
        request: RunRequest,
        index: int,
        total: int,
    ) -> None:
        print()
        print(
            f"[{index}/{total}] {request.run_id}"
        )
        print(
            f"Wheel {request.wheel_index}, "
            f"{request.direction}, "
            f"correct digit {request.correct_digit}, "
            f"start digit {request.start_digit}, "
            f"repetition {request.repetition}"
        )
        print(
            "Wheel digits: "
            f"{request.wheel_1_digit}, "
            f"{request.wheel_2_digit}, "
            f"{request.wheel_3_digit}, "
            f"{request.wheel_4_digit}"
        )
        print(
            f"Scenario: {request.scenario}; "
            f"lock: {request.lock_id}; "
            f"tape: {request.tape_version}"
        )
        print(
            f"Microphone: {request.microphone_position}; "
            f"gain: {request.focusrite_gain}; "
            f"spring: {request.spring_setting}"
        )

        if request.notes:
            print(f"Notes: {request.notes}")

    @staticmethod
    def _print_result(
        result: RunResult,
    ) -> None:
        print(f"Status: {result.status.value}")

        if result.output_dir is not None:
            print(
                f"Saved to: {result.output_dir}"
            )

        if (
            result.quality is not None
            and result.quality.errors
        ):
            print(
                "Quality errors: "
                + ", ".join(
                    result.quality.errors
                )
            )

        if result.error_message:
            print(
                f"Error: {result.error_message}"
            )