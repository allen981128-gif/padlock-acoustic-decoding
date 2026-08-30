"""Deterministic W3 physical-unlock detector (v1).

Frozen calibration:
- Contact microphone only (audio.wav / target input 1)
- Event window: SCAN_END - 30 ms to SCAN_END + 120 ms
- Unlock iff RMS > 0.09 AND derivative RMS > 0.03

The detector deliberately does NOT use:
- digit / movement index
- true-gate labels
- clipping as a decision feature
- motor-reference channel
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import csv
import numpy as np


PRE_END_MS = 30.0
POST_END_MS = 120.0
RMS_THRESHOLD = 0.09
DRMS_THRESHOLD = 0.03


@dataclass(frozen=True)
class UnlockResult:
    detected: bool
    rms: float
    drms: float
    peak: float
    clipping_ratio: float
    window_start_sample: int
    window_end_sample: int
    scan_end_sample: int
    sample_rate: int


def _to_float_audio(audio: np.ndarray) -> np.ndarray:
    """Return mono float64 audio in approximately [-1, 1]."""
    x = np.asarray(audio)

    if x.ndim == 2:
        # The detector is defined on contact-mic channel only.
        x = x[:, 0]
    elif x.ndim != 1:
        raise ValueError(f"Expected mono or 2-D audio, got shape {x.shape}")

    if np.issubdtype(x.dtype, np.floating):
        return x.astype(np.float64, copy=False)

    if np.issubdtype(x.dtype, np.signedinteger):
        max_abs = float(max(abs(np.iinfo(x.dtype).min), np.iinfo(x.dtype).max))
        return x.astype(np.float64) / max_abs

    raise TypeError(f"Unsupported audio dtype: {x.dtype}")


def detect_unlock_array(
    audio: np.ndarray,
    sample_rate: int,
    scan_end_sample: int,
    *,
    rms_threshold: float = RMS_THRESHOLD,
    drms_threshold: float = DRMS_THRESHOLD,
    pre_end_ms: float = PRE_END_MS,
    post_end_ms: float = POST_END_MS,
) -> UnlockResult:
    """Detect a physical unlock from an in-memory contact-mic waveform."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    x = _to_float_audio(audio)
    if len(x) < 2:
        raise ValueError("Audio is too short")

    pre = int(round(sample_rate * pre_end_ms / 1000.0))
    post = int(round(sample_rate * post_end_ms / 1000.0))
    start = max(0, int(scan_end_sample) - pre)
    end = min(len(x), int(scan_end_sample) + post)

    if end - start < 2:
        raise ValueError(
            f"Unlock window is too short: start={start}, end={end}, len={len(x)}"
        )

    w = x[start:end]
    rms = float(np.sqrt(np.mean(np.square(w), dtype=np.float64)))
    dw = np.diff(w)
    drms = float(np.sqrt(np.mean(np.square(dw), dtype=np.float64)))
    peak = float(np.max(np.abs(w)))

    # Diagnostic only; never part of the unlock decision.
    clipping_ratio = float(np.mean(np.abs(w) >= 0.9999))

    detected = bool((rms > rms_threshold) and (drms > drms_threshold))

    return UnlockResult(
        detected=detected,
        rms=rms,
        drms=drms,
        peak=peak,
        clipping_ratio=clipping_ratio,
        window_start_sample=start,
        window_end_sample=end,
        scan_end_sample=int(scan_end_sample),
        sample_rate=int(sample_rate),
    )


def read_scan_end_sample(events_csv: str | Path) -> int:
    """Read aligned SCAN_END sample index from the App events.csv."""
    with Path(events_csv).open("r", newline="", encoding="utf-8-sig") as f:
        rows = csv.DictReader(f)
        matches = [row for row in rows if row.get("event") == "SCAN_END"]

    if len(matches) != 1:
        raise ValueError(f"Expected exactly one SCAN_END, found {len(matches)}")

    value = matches[0].get("aligned_sample_index")
    if value is None or value == "":
        raise ValueError("SCAN_END has no aligned_sample_index")
    return int(float(value))


def detect_unlock_files(
    audio_wav: str | Path,
    events_csv: str | Path,
    *,
    rms_threshold: float = RMS_THRESHOLD,
    drms_threshold: float = DRMS_THRESHOLD,
) -> UnlockResult:
    """Convenience wrapper for a saved App run."""
    try:
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("detect_unlock_files requires the 'soundfile' package") from exc

    audio, sample_rate = sf.read(str(audio_wav), always_2d=False)
    scan_end_sample = read_scan_end_sample(events_csv)
    return detect_unlock_array(
        audio,
        sample_rate,
        scan_end_sample,
        rms_threshold=rms_threshold,
        drms_threshold=drms_threshold,
    )
