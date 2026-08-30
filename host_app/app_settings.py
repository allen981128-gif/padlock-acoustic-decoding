from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
SETTINGS_PATH = APP_DIR / "settings.json"


@dataclass
class AppSettings:
    serial_port: str = "COM4"
    audio_device: int = 17
    dataset_dir: str = "dataset"

    lock_id: str = "test_lock_01"
    scenario: str = "single_digit_scan"
    tape_version: str = "no_tape"
    microphone_position: str = "fixed_position_v1"
    focusrite_gain: str = "gain_setting_v1"
    spring_setting: str = "spring_setting_v1"

    direction: str = "CW"
    repetitions: int = 1
    collection_mode: str = "digit_scan"
    tension_state: str = "UNSPECIFIED"
    probe_amplitude: int = 20
    wide_probe_amplitude: int = 65
    wide_probe_cycles: int = 4
    wheel_order: str = "1,2,3,4"
    wheel_click_order: str = ""
    current_code: str = "0000"
    decision_true_code: str = "1111"
    digit_steps: int = 171
    keep_contact_between_digits: bool = True
    pre_roll_s: float = 0.5
    post_roll_s: float = 0.7
    pause_between_runs_s: float = 1.0

    stop_on_rejected: bool = False

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "AppSettings":
        if not path.exists():
            return cls()

        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        if not isinstance(raw, dict):
            return cls()

        defaults = asdict(cls())
        values = {
            key: raw.get(key, default)
            for key, default in defaults.items()
        }

        # Older builds sometimes persisted an absolute dataset path inside a
        # versioned PadlockCollectorApp_v3 folder.  If the app directory is
        # renamed or replaced, that stale absolute path silently keeps sending
        # new recordings to the old tree.  Migrate only that known legacy
        # setting back to the portable app-relative default.
        dataset_raw = str(values.get("dataset_dir", "dataset") or "dataset").strip()
        dataset_norm = dataset_raw.replace("\\", "/").lower()
        if "padlockcollectorapp_v3" in dataset_norm:
            values["dataset_dir"] = "dataset"

        try:
            return cls(**values)
        except (TypeError, ValueError):
            return cls()

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path.write_text(
            json.dumps(asdict(self), indent=2),
            encoding="utf-8",
        )
