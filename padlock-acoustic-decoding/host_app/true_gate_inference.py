from __future__ import annotations

import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import soundfile as sf
from scipy import fft, signal
from scipy.stats import rankdata


MODEL_FILENAME = "MAIN_v8_ACCURACY_ENSEMBLE_RUNTIME.npz"
MODEL_META_FILENAME = "MAIN_v8_ACCURACY_ENSEMBLE_RUNTIME.json"
EXPECTED_SOURCE_SHA256 = "bfffd49453315d7cb835a409105e4bf3a29412f6b5a51c75a9ac48d41f007e6a"
SUPPORTED_WHEELS = (1, 2, 4)
SAMPLE_RATE = 44_100
FFT_SIZE = 1024
HOP_LENGTH = 256
N_MELS = 32
N_FULL_BINS = 6
FULL_PRE_S = 0.020
FULL_POST_S = 0.100
RANK_STD_10 = 2.8722813232690143


class TrueGateModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProfileResult:
    profile_id: str
    wheel: int
    status: str
    message: str
    true_digit: int | None = None
    pred_digit: int | None = None
    true_rank: int | None = None
    top2: tuple[int, ...] = ()
    top3: tuple[int, ...] = ()
    margin: float | None = None
    fused_scores: tuple[tuple[int, float], ...] = ()
    component_scores: tuple[tuple[str, tuple[tuple[int, float], ...]], ...] = ()
    direction_scores: tuple[tuple[str, tuple[tuple[int, float], ...]], ...] = ()

    @property
    def top1_hit(self) -> bool | None:
        if self.true_rank is None:
            return None
        return self.true_rank <= 1

    @property
    def top2_hit(self) -> bool | None:
        if self.true_rank is None:
            return None
        return self.true_rank <= 2

    @property
    def top3_hit(self) -> bool | None:
        if self.true_rank is None:
            return None
        return self.true_rank <= 3

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "wheel": self.wheel,
            "status": self.status,
            "message": self.message,
            "true_digit": self.true_digit,
            "pred_digit": self.pred_digit,
            "true_rank": self.true_rank,
            "top2": "|".join(str(v) for v in self.top2),
            "top3": "|".join(str(v) for v in self.top3),
            "margin": self.margin,
            "top1_hit": self.top1_hit,
            "top2_hit": self.top2_hit,
            "top3_hit": self.top3_hit,
            "fused_scores": {str(k): v for k, v in self.fused_scores},
            "component_scores": {
                name: {str(k): v for k, v in scores}
                for name, scores in self.component_scores
            },
            "direction_scores": {
                name: {str(k): v for k, v in scores}
                for name, scores in self.direction_scores
            },
        }


@dataclass(frozen=True)
class SessionResult:
    session_id: str
    model_version: str
    source_model_sha256: str
    profiles: tuple[ProfileResult, ...]
    summary: dict[str, object]
    result_csv: Path | None = None
    summary_json: Path | None = None


@dataclass(frozen=True)
class _Decision:
    path: Path
    raw: dict[str, object]
    profile_id: str
    decision_key: str
    session_id: str
    direction: str
    repeat_id: str
    wheel: int
    true_digit: int | None
    candidates: tuple[dict[str, object], ...]

    @property
    def component(self) -> str:
        return f"{self.direction}_{self.repeat_id}"


class TrueGateInferenceEngine:
    """Frozen MAIN v8 inference implemented from exported NumPy arrays.

    The runtime uses the saved feature indices, scalers and logistic-regression
    coefficients directly, avoiding a sklearn/joblib dependency at deployment.
    """

    def __init__(self, asset_dir: Path | None = None) -> None:
        self.asset_dir = asset_dir or self.default_asset_dir()
        self.model_path = self.asset_dir / MODEL_FILENAME
        self.meta_path = self.asset_dir / MODEL_META_FILENAME
        if not self.model_path.exists():
            raise TrueGateModelError(f"Runtime model not found: {self.model_path}")
        if not self.meta_path.exists():
            raise TrueGateModelError(f"Runtime model metadata not found: {self.meta_path}")

        self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        source_sha = str(self.meta.get("source_model_sha256", ""))
        if source_sha != EXPECTED_SOURCE_SHA256:
            raise TrueGateModelError(
                "MAIN v8 source SHA mismatch. "
                f"Expected {EXPECTED_SOURCE_SHA256}, got {source_sha or 'missing'}."
            )

        expected_runtime_sha = str(self.meta.get("runtime_npz_sha256", ""))
        actual_runtime_sha = hashlib.sha256(self.model_path.read_bytes()).hexdigest()
        if expected_runtime_sha and actual_runtime_sha != expected_runtime_sha:
            raise TrueGateModelError(
                "Runtime NPZ SHA mismatch. "
                f"Expected {expected_runtime_sha}, got {actual_runtime_sha}."
            )
        self.runtime_sha256 = actual_runtime_sha

        package = np.load(self.model_path, allow_pickle=False)
        self.context_feature_names = tuple(str(v) for v in package["context_feature_names"].tolist())
        self.mel_basis = np.asarray(package["mel_basis"], dtype=np.float32)

        self.shared_selected_indices = np.asarray(package["shared_selected_indices"], dtype=np.int32)
        self.shared_scaler_mean = np.asarray(package["shared_scaler_mean"], dtype=np.float64)
        self.shared_scaler_scale = np.asarray(package["shared_scaler_scale"], dtype=np.float64)
        self.shared_coef = np.asarray(package["shared_coef"], dtype=np.float64)
        self.shared_intercept = float(np.asarray(package["shared_intercept"], dtype=np.float64).reshape(-1)[0])
        self.shared_direction_alpha = float(np.asarray(package["shared_direction_alpha"]).reshape(-1)[0])
        self.shared_wheel_beta = float(np.asarray(package["shared_wheel_beta"]).reshape(-1)[0])

        self.wheel_models: dict[int, dict[str, object]] = {}
        for wheel in SUPPORTED_WHEELS:
            selected = np.asarray(package[f"w{wheel}_selected_indices"], dtype=np.int32)
            mean = np.asarray(package[f"w{wheel}_scaler_mean"], dtype=np.float64)
            scale = np.asarray(package[f"w{wheel}_scaler_scale"], dtype=np.float64)
            coef = np.asarray(package[f"w{wheel}_coef"], dtype=np.float64)
            intercept = float(np.asarray(package[f"w{wheel}_intercept"], dtype=np.float64).reshape(-1)[0])
            alpha = float(np.asarray(package[f"w{wheel}_direction_alpha"]).reshape(-1)[0])
            shared_weight = float(np.asarray(package[f"w{wheel}_shared_weight"]).reshape(-1)[0])
            if mean.shape != selected.shape or scale.shape != selected.shape:
                raise TrueGateModelError(f"MAIN v8 W{wheel} scaler shape is invalid")
            if coef.shape != (2 * len(selected),):
                raise TrueGateModelError(f"MAIN v8 W{wheel} coefficient shape is invalid")
            self.wheel_models[wheel] = {
                "selected": selected,
                "mean": mean,
                "scale": scale,
                "coef": coef,
                "intercept": intercept,
                "alpha": alpha,
                "shared_weight": shared_weight,
            }

        if len(self.context_feature_names) != 695:
            raise TrueGateModelError("MAIN v8 runtime context feature count must be 695")
        if self.shared_selected_indices.shape != (128,):
            raise TrueGateModelError("MAIN v8 shared branch feature count must be 128")
        if self.shared_scaler_mean.shape != (128,) or self.shared_scaler_scale.shape != (128,):
            raise TrueGateModelError("MAIN v8 shared scaler shape is invalid")
        if self.shared_coef.shape != (768,):
            raise TrueGateModelError("MAIN v8 shared coefficient shape is invalid")
        if self.mel_basis.shape != (N_MELS, FFT_SIZE // 2 + 1):
            raise TrueGateModelError("MAIN v8 runtime mel filter shape is invalid")

        self._window = signal.get_window("hann", FFT_SIZE, fftbins=True).astype(np.float32)
        self._freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / SAMPLE_RATE).astype(np.float64)

    @staticmethod
    def default_asset_dir() -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(getattr(sys, "_MEIPASS")) / "model_assets"
        return Path(__file__).resolve().parent / "model_assets"

    @property
    def model_version(self) -> str:
        return str(self.meta.get("runtime_version", "MAIN_v8_ACCURACY_ENSEMBLE_RUNTIME_v1"))

    @property
    def source_model_sha256(self) -> str:
        return str(self.meta.get("source_model_sha256", EXPECTED_SOURCE_SHA256))

    def _frames(self, y: np.ndarray) -> np.ndarray:
        y = np.asarray(y, dtype=np.float32)
        if y.size < FFT_SIZE:
            y = np.pad(y, (0, FFT_SIZE - y.size))
        return np.lib.stride_tricks.sliding_window_view(y, FFT_SIZE)[::HOP_LENGTH]

    def _stft_magnitude(self, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        frames = self._frames(y)
        spectrum = fft.rfft(frames * self._window[None, :], axis=1).T
        return np.abs(spectrum).astype(np.float32), frames

    @staticmethod
    def _safe_log(x: np.ndarray | float) -> np.ndarray | float:
        return np.log10(np.maximum(x, 1e-12))

    @staticmethod
    def _bin_reduce(matrix: np.ndarray, n_bins: int) -> np.ndarray:
        total = matrix.shape[1]
        edges = np.linspace(0, total, n_bins + 1).astype(int)
        output: list[np.ndarray] = []
        for index in range(n_bins):
            start, end = int(edges[index]), int(edges[index + 1])
            if end <= start:
                end = min(total, start + 1)
            output.append(matrix[:, start:end].mean(axis=1))
        return np.concatenate(output)

    def _full_mel(self, y: np.ndarray) -> np.ndarray:
        magnitude, _ = self._stft_magnitude(y)
        power = magnitude * magnitude
        mel = self.mel_basis @ power
        return self._bin_reduce(np.log10(mel + 1e-12), N_FULL_BINS).astype(np.float32)

    def _spectral_summary(self, y: np.ndarray) -> np.ndarray:
        y = np.asarray(y, dtype=np.float32)
        if y.size < FFT_SIZE:
            y = np.pad(y, (0, FFT_SIZE - y.size))
        magnitude, frames = self._stft_magnitude(y)
        magnitude = magnitude + 1e-10
        power = magnitude * magnitude
        denominator = magnitude.sum(axis=0) + 1e-12
        centroid = (self._freqs[:, None] * magnitude).sum(axis=0) / denominator
        bandwidth = np.sqrt(
            (((self._freqs[:, None] - centroid[None, :]) ** 2) * magnitude).sum(axis=0)
            / denominator
        )
        flatness = np.exp(np.mean(np.log(magnitude), axis=0)) / (np.mean(magnitude, axis=0) + 1e-12)
        cumulative = np.cumsum(power, axis=0)
        total = cumulative[-1] + 1e-12
        roll_index = (cumulative >= 0.85 * total[None, :]).argmax(axis=0)
        rolloff = self._freqs[roll_index]
        rms = np.sqrt(np.mean(frames.astype(np.float32) ** 2, axis=1))
        zcr = np.sum((frames[:, :-1] >= 0) != (frames[:, 1:] >= 0), axis=1) / FFT_SIZE
        log_power = np.log(power + 1e-12)
        flux = np.sqrt(
            np.mean(np.diff(log_power, axis=1, prepend=log_power[:, :1]) ** 2, axis=0)
        )
        stacked = np.vstack(
            [
                self._safe_log(rms),
                self._safe_log(centroid + 1),
                self._safe_log(bandwidth + 1),
                flatness,
                self._safe_log(rolloff + 1),
                zcr,
                flux,
            ]
        )
        return self._bin_reduce(stacked, N_FULL_BINS).astype(np.float32)

    def _envelope_summary(self, y: np.ndarray) -> np.ndarray:
        y64 = np.asarray(y, dtype=np.float64)
        absolute = np.abs(y64)
        if absolute.size < 4:
            return np.zeros(16, dtype=np.float32)
        kernel_size = max(3, int(SAMPLE_RATE * 0.001))
        envelope = np.convolve(
            absolute,
            np.ones(kernel_size, dtype=np.float64) / kernel_size,
            mode="same",
        )
        rms = float(np.sqrt(np.mean(y64 * y64)) + 1e-12)
        peak = float(absolute.max())
        quantiles = np.quantile(envelope, [0.5, 0.75, 0.9, 0.95, 0.99])
        difference = np.abs(np.diff(envelope, prepend=envelope[0]))
        peaks, _ = signal.find_peaks(
            envelope,
            distance=max(1, int(SAMPLE_RATE * 0.008)),
            prominence=max(1e-8, float(np.std(envelope)) * 0.7),
        )
        peak_values = envelope[peaks] if len(peaks) else np.array([0.0])
        peak_position = int(np.argmax(envelope)) / max(1, len(envelope) - 1)
        thirds = np.array_split(y64, 3)
        energies = [float(np.mean(part * part) + 1e-12) for part in thirds]
        energy_total = sum(energies)
        values = [
            self._safe_log(peak),
            self._safe_log(rms),
            peak / rms,
            *self._safe_log(quantiles),
            self._safe_log(float(difference.mean()) + 1e-12),
            self._safe_log(float(difference.max()) + 1e-12),
            len(peaks) / max(1, len(y64) / SAMPLE_RATE),
            self._safe_log(float(np.max(peak_values)) + 1e-12),
            peak_position,
            energies[0] / energy_total,
            energies[1] / energy_total,
            energies[2] / energy_total,
        ]
        return np.asarray(values, dtype=np.float32)

    def _context_features(self, dual_window: np.ndarray) -> np.ndarray:
        if dual_window.ndim != 2 or dual_window.shape[1] < 2:
            raise TrueGateModelError("MAIN v8 requires dual-channel audio")

        values: list[float] = []
        names: list[str] = []
        mels: list[np.ndarray] = []
        for channel in range(2):
            y = dual_window[:, channel]
            mel = self._full_mel(y)
            spec = self._spectral_summary(y)
            env = self._envelope_summary(y)
            mels.append(mel)
            values.extend(float(v) for v in mel)
            names.extend(
                f"ch{channel + 1}_fullmel_b{bin_index}_m{mel_index}"
                for bin_index in range(N_FULL_BINS)
                for mel_index in range(N_MELS)
            )
            values.extend(float(v) for v in spec)
            names.extend(f"ch{channel + 1}_spec_{i}" for i in range(len(spec)))
            values.extend(float(v) for v in env)
            names.extend(f"ch{channel + 1}_env_{i}" for i in range(len(env)))

        diff_mel = mels[0] - mels[1]
        values.extend(float(v) for v in diff_mel)
        names.extend(f"ch1_minus_ch2_mel_{i}" for i in range(len(diff_mel)))

        ch1 = dual_window[:, 0].astype(np.float64)
        ch2 = dual_window[:, 1].astype(np.float64)
        corr = float(np.corrcoef(ch1, ch2)[0, 1]) if np.std(ch1) > 0 and np.std(ch2) > 0 else 0.0
        rms1 = float(np.sqrt(np.mean(ch1 * ch1)) + 1e-12)
        rms2 = float(np.sqrt(np.mean(ch2 * ch2)) + 1e-12)
        peak1 = float(np.max(np.abs(ch1)) + 1e-12)
        peak2 = float(np.max(np.abs(ch2)) + 1e-12)
        values.extend([corr, float(np.log10(rms1 / rms2)), float(np.log10(peak1 / peak2))])
        names.extend(["full_cross_corr", "full_log_rmsratio", "full_log_peakratio"])

        if tuple(names) != self.context_feature_names:
            raise TrueGateModelError("MAIN v8 runtime context feature order does not match frozen asset")
        output = np.asarray(values, dtype=np.float32)
        if output.shape != (695,) or not np.isfinite(output).all():
            raise TrueGateModelError("Invalid/non-finite MAIN v8 context feature vector")
        return output

    @staticmethod
    def _read_scan_bounds(events_path: Path) -> tuple[int, int]:
        mapping: dict[str, int] = {}
        with events_path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise TrueGateModelError(f"events.csv has no header: {events_path}")
            if "event" not in reader.fieldnames or "aligned_sample_index" not in reader.fieldnames:
                raise TrueGateModelError(
                    f"events.csv is missing event/aligned_sample_index: {events_path}"
                )
            for row in reader:
                name = str(row.get("event") or "").strip()
                raw_index = str(row.get("aligned_sample_index") or "").strip()
                if not name or not raw_index:
                    continue
                try:
                    mapping[name] = int(float(raw_index))
                except ValueError:
                    continue
        if "SCAN_START" not in mapping or "SCAN_END" not in mapping:
            raise TrueGateModelError(f"SCAN_START/SCAN_END missing in {events_path}")
        start, end = mapping["SCAN_START"], mapping["SCAN_END"]
        if end <= start:
            raise TrueGateModelError(f"Invalid SCAN_START/SCAN_END order in {events_path}")
        return start, end

    def _extract_run_features(self, run_dir: Path) -> np.ndarray:
        audio_path = run_dir / "audio_dual.wav"
        events_path = run_dir / "events.csv"
        if not audio_path.exists():
            raise TrueGateModelError(f"audio_dual.wav missing: {run_dir}")
        if not events_path.exists():
            raise TrueGateModelError(f"events.csv missing: {run_dir}")
        audio, sample_rate = sf.read(
            audio_path,
            always_2d=True,
            dtype="float32",
        )
        if int(sample_rate) != SAMPLE_RATE:
            raise TrueGateModelError(
                f"MAIN v8 requires {SAMPLE_RATE} Hz audio; got {sample_rate} in {audio_path}"
            )
        if audio.shape[1] < 2:
            raise TrueGateModelError(f"MAIN v8 requires 2 channels in {audio_path}")
        start, end = self._read_scan_bounds(events_path)
        begin = max(0, start - int(FULL_PRE_S * SAMPLE_RATE))
        finish = min(len(audio), end + int(FULL_POST_S * SAMPLE_RATE))
        if finish <= begin:
            raise TrueGateModelError(f"Invalid model window in {run_dir}")
        return self._context_features(audio[begin:finish, :2])

    @staticmethod
    def _decision_true_digit(raw: dict[str, object], wheel: int) -> int | None:
        target = raw.get("target_digit")
        try:
            value = int(target)  # type: ignore[arg-type]
            if value in range(10):
                return value
        except (TypeError, ValueError):
            pass
        digits = raw.get("true_digits")
        if isinstance(digits, list) and len(digits) >= wheel:
            try:
                value = int(digits[wheel - 1])
                if value in range(10):
                    return value
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _decision_wheel(raw: dict[str, object]) -> int:
        active = raw.get("active_wheels")
        if isinstance(active, list):
            active_values: list[int] = []
            for item in active:
                try:
                    value = int(item)
                except (TypeError, ValueError):
                    continue
                if value in range(1, 5):
                    active_values.append(value)
            if len(active_values) == 1:
                return active_values[0]
        try:
            value = int(raw.get("binding_wheel"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            value = 0
        return value

    @staticmethod
    def _load_decision(path: Path) -> _Decision:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if str(raw.get("task_type", "digit_scan")) != "digit_scan":
            raise TrueGateModelError("Binding Scan rows cannot be scored by MAIN v8")
        profile_id = str(raw.get("profile_id") or "").strip()
        decision_key = str(raw.get("decision_key") or path.parent.name).strip()
        session_id = str(raw.get("session_id") or "").strip()
        direction = str(raw.get("direction") or "").strip().upper()
        repeat_id = str(raw.get("repeat_id") or "").strip().upper()
        wheel = TrueGateInferenceEngine._decision_wheel(raw)
        if not profile_id:
            raise TrueGateModelError(f"profile_id missing in {path}")
        if direction not in {"CW", "CCW"}:
            raise TrueGateModelError(f"Invalid direction in {path}: {direction}")
        if repeat_id not in {"A", "B"}:
            raise TrueGateModelError(f"MAIN v8 requires A/B repeats; got {repeat_id} in {path}")
        candidates_raw = raw.get("candidates")
        if not isinstance(candidates_raw, list):
            raise TrueGateModelError(f"candidates missing in {path}")
        candidates = tuple(item for item in candidates_raw if isinstance(item, dict))
        if len(candidates) != 10:
            raise TrueGateModelError(
                f"MAIN v8 requires one 10-WAV single-wheel decision; got {len(candidates)} in {path}"
            )
        true_digit = TrueGateInferenceEngine._decision_true_digit(raw, wheel)
        return _Decision(
            path=path,
            raw=raw,
            profile_id=profile_id,
            decision_key=decision_key,
            session_id=session_id,
            direction=direction,
            repeat_id=repeat_id,
            wheel=wheel,
            true_digit=true_digit,
            candidates=candidates,
        )

    @staticmethod
    def _resolve_run_dir(dataset_root: Path, decision: _Decision, candidate: dict[str, object]) -> Path:
        run_id = str(candidate.get("run_id") or "").strip()
        if not run_id:
            raise TrueGateModelError(f"candidate run_id missing in {decision.path}")
        candidates: list[Path] = []
        output_raw = str(candidate.get("output_dir") or "").strip()
        if output_raw:
            normalized = output_raw.replace("\\", "/")
            output_path = Path(normalized)
            if output_path.is_absolute():
                candidates.append(output_path)
            else:
                candidates.append(dataset_root / output_path)
                parts = output_path.parts
                if parts and parts[0].lower() in {"raw", "rejected"}:
                    candidates.append(dataset_root.joinpath(*parts))
        session_id = decision.session_id or decision.path.parents[1].name
        candidates.extend(
            [
                dataset_root / "raw" / session_id / run_id,
                dataset_root / "rejected" / session_id / run_id,
            ]
        )
        seen: set[str] = set()
        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.exists() and path.is_dir():
                return path
        raise TrueGateModelError(
            f"Could not locate {run_id} for {decision.decision_key}. Checked: "
            + "; ".join(str(p) for p in candidates)
        )

    def _score_decision(
        self,
        dataset_root: Path,
        decision: _Decision,
        log: Callable[[str], None] | None = None,
    ) -> dict[int, float]:
        if decision.wheel not in SUPPORTED_WHEELS:
            raise TrueGateModelError(
                f"MAIN v8 supports W1/W2/W4 only; {decision.decision_key} is W{decision.wheel}"
            )
        features: list[np.ndarray] = []
        digits: list[int] = []
        for index, candidate in enumerate(decision.candidates, start=1):
            status = str(candidate.get("status") or "VALID").upper()
            if status != "VALID":
                raise TrueGateModelError(
                    f"{decision.decision_key} candidate {index} is {status}, not VALID"
                )
            try:
                to_digit = int(candidate.get("to_digit"))  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise TrueGateModelError(
                    f"Invalid to_digit in {decision.decision_key} candidate {index}"
                ) from exc
            if to_digit not in range(10):
                raise TrueGateModelError(
                    f"Invalid to_digit {to_digit} in {decision.decision_key} candidate {index}"
                )
            run_dir = self._resolve_run_dir(dataset_root, decision, candidate)
            features.append(self._extract_run_features(run_dir))
            digits.append(to_digit)
        if sorted(digits) != list(range(10)):
            raise TrueGateModelError(
                f"{decision.decision_key} must contain each physical digit exactly once; got {digits}"
            )

        x0 = np.vstack(features).astype(np.float32)
        median = np.median(x0, axis=0)
        mad = np.median(np.abs(x0 - median), axis=0)
        std = x0.std(axis=0)
        scale = np.where(
            1.4826 * mad > 1e-6,
            1.4826 * mad,
            np.where(std > 1e-6, std, 1.0),
        )
        robust = np.clip((x0 - median) / scale, -12, 12).astype(np.float64)
        direction_value = 1.0 if decision.direction == "CW" else -1.0

        # Shared gate branch (v7-style shared + direction + small wheel adapters).
        sx = robust[:, self.shared_selected_indices]
        sz = (sx - self.shared_scaler_mean) / self.shared_scaler_scale
        i2 = 1.0 if decision.wheel == 2 else 0.0
        i4 = 1.0 if decision.wheel == 4 else 0.0
        sa = self.shared_direction_alpha
        sb = self.shared_wheel_beta
        shared_expanded = np.concatenate(
            [
                sz,
                sa * direction_value * sz,
                sb * i2 * sz,
                sb * i4 * sz,
                sa * sb * direction_value * i2 * sz,
                sa * sb * direction_value * i4 * sz,
            ],
            axis=1,
        )
        shared_raw = shared_expanded @ self.shared_coef + self.shared_intercept
        shared_rank = (rankdata(shared_raw) - 5.5) / RANK_STD_10

        # Wheel-specific branch, selected/fitted independently for W1/W2/W4.
        wm = self.wheel_models[decision.wheel]
        selected = wm["selected"]
        wx = robust[:, selected]  # type: ignore[index]
        wz = (wx - wm["mean"]) / wm["scale"]  # type: ignore[operator]
        wa = float(wm["alpha"])
        wheel_expanded = np.concatenate([wz, wa * direction_value * wz], axis=1)
        wheel_raw = wheel_expanded @ wm["coef"] + float(wm["intercept"])  # type: ignore[operator]
        wheel_rank = (rankdata(wheel_raw) - 5.5) / RANK_STD_10

        shared_weight = float(wm["shared_weight"])
        blended = shared_weight * shared_rank + (1.0 - shared_weight) * wheel_rank
        if log is not None:
            log(
                f"Scored {decision.decision_key} ({decision.direction} {decision.repeat_id}, "
                f"W{decision.wheel}, MAIN v8 ensemble)"
            )
        return {digit: float(score) for digit, score in zip(digits, blended)}

    @staticmethod
    def _find_session_decisions(dataset_root: Path, session_id: str) -> list[Path]:
        root = dataset_root / "decision_batches" / session_id
        if not root.exists():
            return []
        return sorted(root.glob("*/decision.json"))

    @staticmethod
    def list_sessions(dataset_root: Path) -> list[str]:
        root = dataset_root / "decision_batches"
        if not root.exists():
            return []
        sessions = [path.name for path in root.iterdir() if path.is_dir() and not path.name.startswith("_")]
        sessions.sort(key=lambda name: (root / name).stat().st_mtime, reverse=True)
        return sessions

    def score_session(
        self,
        dataset_root: Path,
        session_id: str,
        *,
        save_results: bool = True,
        log: Callable[[str], None] | None = None,
    ) -> SessionResult:
        dataset_root = Path(dataset_root).resolve()
        session_id = session_id.strip()
        if not session_id:
            raise TrueGateModelError("Session ID is empty")
        paths = self._find_session_decisions(dataset_root, session_id)
        if not paths:
            raise TrueGateModelError(
                f"No finalised Digit Scan decisions found under {dataset_root / 'decision_batches' / session_id}"
            )

        loaded: list[_Decision] = []
        load_errors: list[ProfileResult] = []
        for path in paths:
            try:
                decision = self._load_decision(path)
                loaded.append(decision)
            except Exception as exc:
                load_errors.append(
                    ProfileResult(
                        profile_id=path.parent.name,
                        wheel=0,
                        status="ERROR",
                        message=str(exc),
                    )
                )

        grouped: dict[tuple[str, int], list[_Decision]] = {}
        for decision in loaded:
            grouped.setdefault((decision.profile_id, decision.wheel), []).append(decision)

        results: list[ProfileResult] = []
        expected_components = {"CCW_A", "CCW_B", "CW_A", "CW_B"}
        for (profile_id, wheel), decisions in sorted(grouped.items(), key=lambda item: item[0]):
            if wheel not in SUPPORTED_WHEELS:
                results.append(
                    ProfileResult(
                        profile_id=profile_id,
                        wheel=wheel,
                        status="UNSUPPORTED",
                        message="MAIN v8 supports W1/W2/W4 only",
                    )
                )
                continue
            component_map: dict[str, _Decision] = {}
            duplicate = False
            for decision in decisions:
                if decision.component in component_map:
                    duplicate = True
                component_map[decision.component] = decision
            missing = sorted(expected_components - set(component_map))
            extras = sorted(set(component_map) - expected_components)
            if duplicate or missing or extras:
                details: list[str] = []
                if duplicate:
                    details.append("duplicate direction/repeat component")
                if missing:
                    details.append("missing " + ", ".join(missing))
                if extras:
                    details.append("unexpected " + ", ".join(extras))
                results.append(
                    ProfileResult(
                        profile_id=profile_id,
                        wheel=wheel,
                        status="INCOMPLETE",
                        message="; ".join(details),
                    )
                )
                continue
            try:
                component_scores: dict[str, dict[int, float]] = {}
                for component in ("CCW_A", "CCW_B", "CW_A", "CW_B"):
                    component_scores[component] = self._score_decision(
                        dataset_root,
                        component_map[component],
                        log=log,
                    )

                direction_scores: dict[str, dict[int, float]] = {}
                for direction in ("CCW", "CW"):
                    a_scores = component_scores[f"{direction}_A"]
                    b_scores = component_scores[f"{direction}_B"]
                    direction_scores[direction] = {
                        digit: 0.5 * a_scores[digit] + 0.5 * b_scores[digit]
                        for digit in range(10)
                    }
                fused = {
                    digit: 0.5 * direction_scores["CCW"][digit]
                    + 0.5 * direction_scores["CW"][digit]
                    for digit in range(10)
                }
                order = sorted(range(10), key=lambda digit: fused[digit], reverse=True)
                margin = float(fused[order[0]] - fused[order[1]])

                # Truth is intentionally attached only after the prediction has been
                # fully computed.  It is not part of any feature or scoring input.
                truths = {
                    decision.true_digit
                    for decision in component_map.values()
                    if decision.true_digit is not None
                }
                if len(truths) == 1:
                    true_digit = int(next(iter(truths)))
                    true_rank = order.index(true_digit) + 1
                    truth_message = ""
                elif len(truths) == 0:
                    true_digit = None
                    true_rank = None
                    truth_message = "prediction only; no validation truth stored"
                else:
                    true_digit = None
                    true_rank = None
                    truth_message = "prediction computed, but stored truth is inconsistent across A/B/directions"

                results.append(
                    ProfileResult(
                        profile_id=profile_id,
                        wheel=wheel,
                        status="SCORED",
                        message=truth_message,
                        true_digit=true_digit,
                        pred_digit=order[0],
                        true_rank=true_rank,
                        top2=tuple(order[:2]),
                        top3=tuple(order[:3]),
                        margin=margin,
                        fused_scores=tuple((digit, float(fused[digit])) for digit in range(10)),
                        component_scores=tuple(
                            (
                                component,
                                tuple(
                                    (digit, float(component_scores[component][digit]))
                                    for digit in range(10)
                                ),
                            )
                            for component in ("CCW_A", "CCW_B", "CW_A", "CW_B")
                        ),
                        direction_scores=tuple(
                            (
                                direction,
                                tuple(
                                    (digit, float(direction_scores[direction][digit]))
                                    for digit in range(10)
                                ),
                            )
                            for direction in ("CCW", "CW")
                        ),
                    )
                )
            except Exception as exc:
                results.append(
                    ProfileResult(
                        profile_id=profile_id,
                        wheel=wheel,
                        status="ERROR",
                        message=str(exc),
                    )
                )

        results.extend(load_errors)
        results.sort(key=lambda item: (item.profile_id, item.wheel, item.status))
        summary = self._summarize(results)

        csv_path: Path | None = None
        json_path: Path | None = None
        if save_results:
            output_dir = dataset_root / "recognition_results" / session_id
            output_dir.mkdir(parents=True, exist_ok=True)
            csv_path = output_dir / "MAIN_v8_profile_results.csv"
            json_path = output_dir / "MAIN_v8_summary.json"
            self._write_results(csv_path, json_path, session_id, results, summary)
            if log is not None:
                log(f"Saved MAIN v8 results: {csv_path}")

        return SessionResult(
            session_id=session_id,
            model_version=self.model_version,
            source_model_sha256=self.source_model_sha256,
            profiles=tuple(results),
            summary=summary,
            result_csv=csv_path,
            summary_json=json_path,
        )

    @staticmethod
    def _summarize(results: Iterable[ProfileResult]) -> dict[str, object]:
        result_list = list(results)
        scored = [item for item in result_list if item.status == "SCORED"]
        validated = [item for item in scored if item.true_rank is not None]

        def metrics(items: list[ProfileResult]) -> dict[str, object]:
            n = len(items)
            if n == 0:
                return {"n": 0, "top1_correct": 0, "top2_correct": 0, "top3_correct": 0,
                        "top1": None, "top2": None, "top3": None, "mean_rank": None}
            ranks = np.asarray([int(item.true_rank) for item in items if item.true_rank is not None], dtype=int)
            return {
                "n": n,
                "top1_correct": int(np.sum(ranks <= 1)),
                "top2_correct": int(np.sum(ranks <= 2)),
                "top3_correct": int(np.sum(ranks <= 3)),
                "top1": float(np.mean(ranks <= 1)),
                "top2": float(np.mean(ranks <= 2)),
                "top3": float(np.mean(ranks <= 3)),
                "mean_rank": float(np.mean(ranks)),
            }

        overall = metrics(validated)
        by_wheel: dict[str, object] = {}
        for wheel in SUPPORTED_WHEELS:
            by_wheel[f"W{wheel}"] = metrics([item for item in validated if item.wheel == wheel])
        return {
            "profiles_found": len(result_list),
            "profiles_scored": len(scored),
            "profiles_validated": len(validated),
            "overall": overall,
            "by_wheel": by_wheel,
            "errors_or_incomplete": len([item for item in result_list if item.status != "SCORED"]),
        }

    @staticmethod
    def _score_rank_map(score_map: dict[int, float]) -> dict[int, int]:
        order = sorted(score_map, key=lambda digit: (score_map[digit], -digit), reverse=True)
        return {digit: index + 1 for index, digit in enumerate(order)}

    def _candidate_evidence_rows(
        self,
        results: Iterable[ProfileResult],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for item in results:
            if item.status != "SCORED" or not item.fused_scores or not item.component_scores:
                continue
            fused = dict(item.fused_scores)
            components = {name: dict(scores) for name, scores in item.component_scores}
            directions = {name: dict(scores) for name, scores in item.direction_scores}
            required_components = ("CCW_A", "CCW_B", "CW_A", "CW_B")
            if any(name not in components for name in required_components):
                continue
            if any(name not in directions for name in ("CCW", "CW")):
                continue

            fused_ranks = self._score_rank_map(fused)
            component_ranks = {
                name: self._score_rank_map(components[name]) for name in required_components
            }
            direction_ranks = {
                name: self._score_rank_map(directions[name]) for name in ("CCW", "CW")
            }

            for digit in range(10):
                component_values = np.asarray(
                    [components[name][digit] for name in required_components], dtype=np.float64
                )
                component_rank_values = [component_ranks[name][digit] for name in required_components]
                ccw_ab_gap = abs(components["CCW_A"][digit] - components["CCW_B"][digit])
                cw_ab_gap = abs(components["CW_A"][digit] - components["CW_B"][digit])
                rows.append(
                    {
                        "profile_id": item.profile_id,
                        "wheel": item.wheel,
                        "digit": digit,
                        "fused_rank_score": float(fused[digit]),
                        "fused_rank": int(fused_ranks[digit]),
                        "ccw_rank_score": float(directions["CCW"][digit]),
                        "cw_rank_score": float(directions["CW"][digit]),
                        "ccw_rank": int(direction_ranks["CCW"][digit]),
                        "cw_rank": int(direction_ranks["CW"][digit]),
                        "ccw_a_rank_score": float(components["CCW_A"][digit]),
                        "ccw_b_rank_score": float(components["CCW_B"][digit]),
                        "cw_a_rank_score": float(components["CW_A"][digit]),
                        "cw_b_rank_score": float(components["CW_B"][digit]),
                        "ccw_a_rank": int(component_ranks["CCW_A"][digit]),
                        "ccw_b_rank": int(component_ranks["CCW_B"][digit]),
                        "cw_a_rank": int(component_ranks["CW_A"][digit]),
                        "cw_b_rank": int(component_ranks["CW_B"][digit]),
                        "component_top1_votes": int(sum(rank <= 1 for rank in component_rank_values)),
                        "component_top2_votes": int(sum(rank <= 2 for rank in component_rank_values)),
                        "component_top3_votes": int(sum(rank <= 3 for rank in component_rank_values)),
                        "component_score_std": float(np.std(component_values)),
                        "component_score_range": float(np.max(component_values) - np.min(component_values)),
                        "ccw_ab_gap": float(ccw_ab_gap),
                        "cw_ab_gap": float(cw_ab_gap),
                        "mean_ab_gap": float(0.5 * (ccw_ab_gap + cw_ab_gap)),
                        "direction_gap": float(
                            abs(directions["CCW"][digit] - directions["CW"][digit])
                        ),
                    }
                )
        return rows

    def _prefix_hypothesis_rows(
        self,
        results: Iterable[ProfileResult],
        evidence_rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        scored_by_wheel: dict[int, list[ProfileResult]] = {wheel: [] for wheel in SUPPORTED_WHEELS}
        for item in results:
            if item.status == "SCORED" and item.wheel in scored_by_wheel and item.fused_scores:
                scored_by_wheel[item.wheel].append(item)
        if any(len(scored_by_wheel[wheel]) != 1 for wheel in SUPPORTED_WHEELS):
            return []

        profile_by_wheel = {wheel: scored_by_wheel[wheel][0] for wheel in SUPPORTED_WHEELS}
        fused_by_wheel = {
            wheel: dict(profile_by_wheel[wheel].fused_scores) for wheel in SUPPORTED_WHEELS
        }
        ranks_by_wheel = {
            wheel: self._score_rank_map(fused_by_wheel[wheel]) for wheel in SUPPORTED_WHEELS
        }
        top_score_by_wheel = {
            wheel: max(fused_by_wheel[wheel].values()) for wheel in SUPPORTED_WHEELS
        }
        evidence_lookup = {
            (int(row["wheel"]), int(row["digit"])): row for row in evidence_rows
        }

        rows: list[dict[str, object]] = []
        for d1 in range(10):
            for d2 in range(10):
                for d4 in range(10):
                    selected = {1: d1, 2: d2, 4: d4}
                    joint_fused = sum(fused_by_wheel[wheel][digit] for wheel, digit in selected.items())
                    evidence_loss = sum(
                        top_score_by_wheel[wheel] - fused_by_wheel[wheel][digit]
                        for wheel, digit in selected.items()
                    )
                    ranks = {wheel: ranks_by_wheel[wheel][digit] for wheel, digit in selected.items()}
                    support = {
                        wheel: evidence_lookup.get((wheel, digit), {}) for wheel, digit in selected.items()
                    }
                    rows.append(
                        {
                            "prefix": f"{d1}{d2}?{d4}",
                            "w1_digit": d1,
                            "w2_digit": d2,
                            "w4_digit": d4,
                            "joint_fused_score": float(joint_fused),
                            "evidence_loss_from_top1": float(evidence_loss),
                            "w1_rank": int(ranks[1]),
                            "w2_rank": int(ranks[2]),
                            "w4_rank": int(ranks[4]),
                            "max_wheel_rank": int(max(ranks.values())),
                            "in_top2_cube": int(all(rank <= 2 for rank in ranks.values())),
                            "in_top3_cube": int(all(rank <= 3 for rank in ranks.values())),
                            "w1_fused_score": float(fused_by_wheel[1][d1]),
                            "w2_fused_score": float(fused_by_wheel[2][d2]),
                            "w4_fused_score": float(fused_by_wheel[4][d4]),
                            "w1_component_top1_votes": int(support[1].get("component_top1_votes", 0) or 0),
                            "w2_component_top1_votes": int(support[2].get("component_top1_votes", 0) or 0),
                            "w4_component_top1_votes": int(support[4].get("component_top1_votes", 0) or 0),
                            "w1_component_score_std": float(support[1].get("component_score_std", 0.0) or 0.0),
                            "w2_component_score_std": float(support[2].get("component_score_std", 0.0) or 0.0),
                            "w4_component_score_std": float(support[4].get("component_score_std", 0.0) or 0.0),
                            "w1_mean_ab_gap": float(support[1].get("mean_ab_gap", 0.0) or 0.0),
                            "w2_mean_ab_gap": float(support[2].get("mean_ab_gap", 0.0) or 0.0),
                            "w4_mean_ab_gap": float(support[4].get("mean_ab_gap", 0.0) or 0.0),
                            "w1_direction_gap": float(support[1].get("direction_gap", 0.0) or 0.0),
                            "w2_direction_gap": float(support[2].get("direction_gap", 0.0) or 0.0),
                            "w4_direction_gap": float(support[4].get("direction_gap", 0.0) or 0.0),
                        }
                    )

        rows.sort(
            key=lambda row: (
                -float(row["joint_fused_score"]),
                int(row["w1_digit"]),
                int(row["w2_digit"]),
                int(row["w4_digit"]),
            )
        )
        top3_rank = 0
        for global_rank, row in enumerate(rows, start=1):
            row["global_rank"] = global_rank
            if int(row["in_top3_cube"]):
                top3_rank += 1
                row["top3_cube_rank"] = top3_rank
            else:
                row["top3_cube_rank"] = ""
        return rows

    @staticmethod
    def _write_dict_rows(path: Path, rows: list[dict[str, object]]) -> None:
        if not rows:
            if path.exists():
                path.unlink()
            return
        fieldnames = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write_results(
        self,
        csv_path: Path,
        json_path: Path,
        session_id: str,
        results: list[ProfileResult],
        summary: dict[str, object],
    ) -> None:
        fieldnames = [
            "profile_id", "wheel", "status", "message", "true_digit", "pred_digit",
            "true_rank", "top2", "top3", "margin", "top1_hit", "top2_hit", "top3_hit",
            "score_d0", "score_d1", "score_d2", "score_d3", "score_d4", "score_d5",
            "score_d6", "score_d7", "score_d8", "score_d9",
        ]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for item in results:
                score_map = dict(item.fused_scores)
                row = {
                    "profile_id": item.profile_id,
                    "wheel": item.wheel,
                    "status": item.status,
                    "message": item.message,
                    "true_digit": "" if item.true_digit is None else item.true_digit,
                    "pred_digit": "" if item.pred_digit is None else item.pred_digit,
                    "true_rank": "" if item.true_rank is None else item.true_rank,
                    "top2": "|".join(str(v) for v in item.top2),
                    "top3": "|".join(str(v) for v in item.top3),
                    "margin": "" if item.margin is None else f"{item.margin:.9f}",
                    "top1_hit": "" if item.top1_hit is None else int(item.top1_hit),
                    "top2_hit": "" if item.top2_hit is None else int(item.top2_hit),
                    "top3_hit": "" if item.top3_hit is None else int(item.top3_hit),
                }
                for digit in range(10):
                    row[f"score_d{digit}"] = "" if digit not in score_map else f"{score_map[digit]:.9f}"
                writer.writerow(row)

        evidence_rows = self._candidate_evidence_rows(results)
        evidence_path = csv_path.parent / "MAIN_v8_candidate_evidence.csv"
        prefix_rows = self._prefix_hypothesis_rows(results, evidence_rows)
        prefix_path = csv_path.parent / "MAIN_v8_prefix_hypotheses.csv"
        self._write_dict_rows(evidence_path, evidence_rows)
        self._write_dict_rows(prefix_path, prefix_rows)

        payload = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "model_version": self.model_version,
            "source_model_sha256": self.source_model_sha256,
            "runtime_npz_sha256": self.runtime_sha256,
            "anti_leakage": (
                "Prediction is computed from audio + known direction + wheel identity only. "
                "Stored true digits are attached after ranking solely to calculate validation accuracy."
            ),
            "evidence_exports": {
                "candidate_evidence_csv": evidence_path.name if evidence_rows else None,
                "prefix_hypotheses_csv": prefix_path.name if prefix_rows else None,
                "prefix_ranking_rule": (
                    "joint_fused_score = W1 fused rank-score + W2 fused rank-score + W4 fused rank-score. "
                    "No truth labels and no historical wheel-priority heuristic are used. "
                    "Component/direction agreement columns are exported for analysis only and are not yet used to rerank."
                ),
            },
            "summary": summary,
            "profiles": [item.to_dict() for item in results],
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
