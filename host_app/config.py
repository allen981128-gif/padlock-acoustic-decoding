from dataclasses import dataclass, field
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent


# Unified wheel calibration validated on the current mechanism.
# One visible digit = 171 motor steps; one full revolution = 1710 steps.
WHEEL_STEPS_PER_REV = 1710
WHEEL_STEPS_PER_DIGIT = WHEEL_STEPS_PER_REV // 10

# Binding Sweep uses the same physical calibration as discrete digit moves.
BINDING_SWEEP_STEPS_PER_REV = WHEEL_STEPS_PER_REV
BINDING_SWEEP_STEPS_PER_SECTOR = (
    BINDING_SWEEP_STEPS_PER_REV // 10
)

# Controlled binding-reference sweep: start one digit after the known true
# gate and traverse eight sectors, stopping one digit before the gate.
# This excludes both entry into and exit from the true gate.
BINDING_REFERENCE_SWEEP_SECTORS = 8
BINDING_REFERENCE_SWEEP_STEPS = (
    BINDING_REFERENCE_SWEEP_SECTORS * WHEEL_STEPS_PER_DIGIT
)
BINDING_REFERENCE_SWEEP_SECTOR_STEPS = WHEEL_STEPS_PER_DIGIT

# Wide local probe. The wheel is pre-positioned by -A, swept continuously
# between -A and +A for N cycles, then returned to the centre. The net
# displacement is zero and the default amplitude stays inside one 171-step
# digit sector with a 20-step margin on each side.
WIDE_PROBE_DEFAULT_AMPLITUDE_STEPS = 65
WIDE_PROBE_MIN_AMPLITUDE_STEPS = 20
WIDE_PROBE_MAX_AMPLITUDE_STEPS = 80
WIDE_PROBE_DEFAULT_CYCLES = 4
WIDE_PROBE_MIN_CYCLES = 1
WIDE_PROBE_MAX_CYCLES = 8


@dataclass(frozen=True)
class SerialConfig:
    port: str = "COM4"
    baud_rate: int = 115_200
    read_timeout_s: float = 0.1
    write_timeout_s: float = 1.0
    startup_wait_s: float = 2.0


@dataclass(frozen=True)
class AudioConfig:
    device_name: str = "Focusrite"
    sample_rate: int = 44_100

    # Focusrite WASAPI exposes analogue inputs 1-2 and loopback 1-2.
    capture_channels: int = 4

    # Zero-based analogue input mapping.
    target_channel: int = 0
    reference_channel: int = 1

    dtype: str = "float32"
    block_size: int = 0
    wav_subtype: str = "PCM_24"
    pre_roll_s: float = 0.5
    post_roll_s: float = 0.7


@dataclass(frozen=True)
class TimeoutConfig:
    ping_s: float = 5.0
    status_s: float = 5.0
    prepare_s: float = 60.0
    scan_start_s: float = 5.0
    scan_end_s: float = 30.0
    done_s: float = 15.0
    stop_s: float = 5.0


@dataclass(frozen=True)
class StorageConfig:
    dataset_dir: Path = PROJECT_DIR / "dataset"
    raw_dir_name: str = "raw"
    rejected_dir_name: str = "rejected"
    logs_dir_name: str = "logs"

    # audio.wav remains the mono lock-target file for compatibility.
    audio_filename: str = "audio.wav"
    reference_audio_filename: str = "motor_reference.wav"
    dual_audio_filename: str = "audio_dual.wav"
    events_filename: str = "events.csv"
    metadata_filename: str = "metadata.json"
    quality_filename: str = "quality.json"

    @property
    def raw_dir(self) -> Path:
        return self.dataset_dir / self.raw_dir_name

    @property
    def rejected_dir(self) -> Path:
        return self.dataset_dir / self.rejected_dir_name

    @property
    def logs_dir(self) -> Path:
        return self.dataset_dir / self.logs_dir_name


@dataclass(frozen=True)
class QualityConfig:
    expected_digit_boundaries: int = 0
    expected_final_step: int = WHEEL_STEPS_PER_DIGIT
    clipping_level: float = 0.999
    max_clipped_ratio: float = 0.001
    minimum_rms: float = 1e-5
    minimum_duration_s: float = 1.0


@dataclass(frozen=True)
class SessionConfig:
    plan_file: Path = PROJECT_DIR / "collection_plan.csv"
    require_confirmation: bool = True
    pause_between_runs_s: float = 1.0


@dataclass(frozen=True)
class AppConfig:
    serial: SerialConfig = field(default_factory=SerialConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    session: SessionConfig = field(default_factory=SessionConfig)


CONFIG = AppConfig()


def ensure_storage_directories(
    config: AppConfig = CONFIG,
) -> None:
    config.storage.raw_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    config.storage.rejected_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
    config.storage.logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )
