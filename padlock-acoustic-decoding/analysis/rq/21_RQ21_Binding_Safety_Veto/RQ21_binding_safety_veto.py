from __future__ import annotations

import csv
import json
import math
import re
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf
from scipy import signal
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

SAMPLE_RATE = 44_100
PRE_S = 0.020
POST_S = 0.100
TOP_K_FEATURES = 12

SESSIONS = {
    "B01": "Binding_B01_3175",
    "B02": "Binding_B02_8642",
    "B03": "Binding_B03_0528",
}

DARK_BLUE = "#315B7D"
LIGHT_BLUE = "#AFC5D5"
DARK_GREY = "#596168"

ARCHIVED_REFERENCE = pd.DataFrame(
    [
        {"stage": 1, "direction": "CCW", "auc": 0.85},
        {"stage": 1, "direction": "CW", "auc": 0.84},
        {"stage": 2, "direction": "CCW", "auc": 0.57},
        {"stage": 2, "direction": "CW", "auc": 0.63},
    ]
)


def locate_repro_root(mydrive: Path) -> Path:
    candidates = [
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1",
        mydrive / "Padlock_Reproduction_v1",
    ]
    for root in candidates:
        if (root / "results").exists():
            return root
    raise FileNotFoundError("Could not locate Padlock_Reproduction_v1.")


def locate_results_root(mydrive: Path) -> Path:
    root = locate_repro_root(mydrive)
    results = root / "results"
    if not results.exists():
        raise FileNotFoundError("Could not locate the active results folder.")
    return results


def locate_zip(mydrive: Path, session: str) -> Path:
    candidates = [
        mydrive / "dataset" / "raw" / f"{session}.zip",
        mydrive / "dataset" / "dataset" / "raw" / f"{session}.zip",
    ]
    for path in candidates:
        if path.exists() and path.stat().st_size > 50_000_000:
            return path
    raise FileNotFoundError(f"Could not locate full raw ZIP for {session}.")


def locate_decision_dir(mydrive: Path, session: str) -> Path:
    candidates = [
        mydrive / "dataset" / "binding_scans" / "_progress" / session,
        mydrive / "dataset" / "dataset" / "binding_scans" / "_progress" / session,
    ]
    for path in candidates:
        if not path.is_dir():
            continue
        files = list(path.glob("*.json"))
        if len(files) >= 120:
            return path
    raise FileNotFoundError(
        f"Could not locate Binding decision JSON folder for {session}."
    )


def archive_summary(mydrive: Path) -> pd.DataFrame:
    rows = []
    for batch, session in SESSIONS.items():
        zip_path = locate_zip(mydrive, session)
        decision_dir = locate_decision_dir(mydrive, session)
        rows.append(
            {
                "batch": batch,
                "session": session,
                "zip_mb": zip_path.stat().st_size / 1e6,
                "decision_jsons": len(list(decision_dir.glob("*.json"))),
            }
        )
    return pd.DataFrame(rows)


def _read_scan_bounds(events_path: Path) -> tuple[int, int]:
    mapping: dict[str, int] = {}
    with events_path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "event" not in fields or "aligned_sample_index" not in fields:
            raise ValueError(f"Invalid events.csv: {events_path}")
        for row in reader:
            event = str(row.get("event") or "").strip()
            raw = str(row.get("aligned_sample_index") or "").strip()
            if not event or not raw:
                continue
            try:
                mapping[event] = int(float(raw))
            except ValueError:
                continue
    if "SCAN_START" not in mapping or "SCAN_END" not in mapping:
        raise ValueError(f"SCAN_START/SCAN_END missing: {events_path}")
    start, end = mapping["SCAN_START"], mapping["SCAN_END"]
    if end <= start:
        raise ValueError(f"Invalid scan bounds: {events_path}")
    return start, end


def _spectral_descriptors(x: np.ndarray, sr: int) -> dict[str, float]:
    x = np.asarray(x, dtype=np.float64)
    if len(x) < 8:
        return {
            "centroid": 0.0,
            "bandwidth": 0.0,
            "rolloff85": 0.0,
            "hf_ratio": 0.0,
            "flatness": 0.0,
        }
    window = np.hanning(len(x))
    mag = np.abs(np.fft.rfft(x * window)) + 1e-12
    power = mag * mag
    freqs = np.fft.rfftfreq(len(x), d=1.0 / sr)
    total = float(power.sum()) + 1e-12
    centroid_hz = float((freqs * power).sum() / total)
    bandwidth_hz = float(
        np.sqrt((((freqs - centroid_hz) ** 2) * power).sum() / total)
    )
    cumulative = np.cumsum(power)
    roll_idx = int(np.searchsorted(cumulative, 0.85 * cumulative[-1]))
    roll_idx = min(roll_idx, len(freqs) - 1)
    hf_ratio = float(power[freqs >= 4_000].sum() / total)
    flatness = float(np.exp(np.mean(np.log(mag))) / np.mean(mag))
    nyquist = sr / 2.0
    return {
        "centroid": centroid_hz / nyquist,
        "bandwidth": bandwidth_hz / nyquist,
        "rolloff85": float(freqs[roll_idx] / nyquist),
        "hf_ratio": hf_ratio,
        "flatness": flatness,
    }


def _channel_descriptors(x: np.ndarray, sr: int, prefix: str) -> dict[str, float]:
    x = np.asarray(x, dtype=np.float64)
    eps = 1e-12
    rms = float(np.sqrt(np.mean(x * x)) + eps)
    peak = float(np.max(np.abs(x)) + eps)
    diff = np.diff(x, prepend=x[0])
    drms = float(np.sqrt(np.mean(diff * diff)) + eps)
    zcr = float(np.mean(np.signbit(x[1:]) != np.signbit(x[:-1]))) if len(x) > 1 else 0.0
    out = {
        f"{prefix}_log_rms": float(np.log10(rms)),
        f"{prefix}_log_peak": float(np.log10(peak)),
        f"{prefix}_crest": float(peak / rms),
        f"{prefix}_log_drms": float(np.log10(drms)),
        f"{prefix}_zcr": zcr,
    }
    for name, value in _spectral_descriptors(x, sr).items():
        out[f"{prefix}_{name}"] = value
    return out


def run_descriptors(run_dir: Path) -> dict[str, float]:
    audio_path = run_dir / "audio_dual.wav"
    events_path = run_dir / "events.csv"
    if not audio_path.exists() or not events_path.exists():
        raise FileNotFoundError(f"Missing audio/events in {run_dir}")
    audio, sr = sf.read(audio_path, always_2d=True, dtype="float32")
    if int(sr) != SAMPLE_RATE or audio.shape[1] < 2:
        raise ValueError(f"Unexpected audio format in {audio_path}")
    start, end = _read_scan_bounds(events_path)
    begin = max(0, start - int(PRE_S * sr))
    finish = min(len(audio), end + int(POST_S * sr))
    window = audio[begin:finish, :2].astype(np.float64)
    if len(window) < 8:
        raise ValueError(f"Audio window too short in {run_dir}")
    out: dict[str, float] = {"duration_s": float((end - start) / sr)}
    out.update(_channel_descriptors(window[:, 0], sr, "ch1"))
    out.update(_channel_descriptors(window[:, 1], sr, "ch2"))
    ch1, ch2 = window[:, 0], window[:, 1]
    s1, s2 = float(np.std(ch1)), float(np.std(ch2))
    corr = float(np.corrcoef(ch1, ch2)[0, 1]) if s1 > 0 and s2 > 0 else 0.0
    rms1 = float(np.sqrt(np.mean(ch1 * ch1)) + 1e-12)
    rms2 = float(np.sqrt(np.mean(ch2 * ch2)) + 1e-12)
    peak1 = float(np.max(np.abs(ch1)) + 1e-12)
    peak2 = float(np.max(np.abs(ch2)) + 1e-12)
    out["cross_corr"] = corr
    out["log_rms_ratio"] = float(np.log10(rms1 / rms2))
    out["log_peak_ratio"] = float(np.log10(peak1 / peak2))
    return out


def _find_raw_session(extract_root: Path, session: str) -> Path:
    candidates = [extract_root / session, extract_root / "raw" / session]
    for path in candidates:
        if path.is_dir() and len(list(path.glob("run_*"))) >= 1_000:
            return path
    matches = []
    for path in extract_root.rglob(session):
        if path.is_dir() and len(list(path.glob("run_*"))) >= 1_000:
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(f"Could not locate extracted raw session {session}.")


def _copy_decisions(source: Path, dest: Path) -> Path:
    if dest.exists() and len(list(dest.glob("*.json"))) >= 120:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest)
    return dest


def prepare_session(
    zip_path: Path,
    decision_source: Path,
    work_dir: Path,
    session: str,
) -> tuple[Path, Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    extract_root = work_dir / session
    local_zip = work_dir / f"{session}.zip"
    marker = extract_root / ".rq21_extract_complete"
    if not marker.exists():
        if extract_root.exists():
            shutil.rmtree(extract_root)
        print(f"[{session}] copy raw ZIP to local Colab ({zip_path.stat().st_size / 1e6:.1f} MB)")
        shutil.copy2(zip_path, local_zip)
        extract_root.mkdir(parents=True, exist_ok=True)
        print(f"[{session}] extract locally")
        with zipfile.ZipFile(local_zip, "r") as archive:
            archive.extractall(extract_root)
        marker.touch()
        local_zip.unlink(missing_ok=True)
    else:
        print(f"[{session}] reusing local extraction")
    raw_session = _find_raw_session(extract_root, session)
    local_decisions = _copy_decisions(
        decision_source,
        work_dir / f"{session}_decisions",
    )
    return raw_session, local_decisions


def _candidate_list(raw: dict) -> list[dict]:
    candidates = raw.get("candidates")
    if isinstance(candidates, dict):
        items = [v for _, v in sorted(candidates.items(), key=lambda kv: int(kv[0])) if isinstance(v, dict)]
    elif isinstance(candidates, list):
        items = [v for v in candidates if isinstance(v, dict)]
    else:
        items = []
    if len(items) != 10:
        raise ValueError("Expected ten candidates in Binding decision JSON.")
    return items


def _upstream_digit(raw: dict, stage: int) -> int:
    start_code = str(raw.get("start_code") or "").strip()
    if len(start_code) == 4 and start_code.isdigit():
        idx = 0 if stage == 1 else 1
        return int(start_code[idx])
    profile_id = str(raw.get("profile_id") or "")
    match = re.search(r"_W[12](\d)", profile_id)
    if match:
        return int(match.group(1))
    raise ValueError("Could not determine upstream candidate digit.")


def _latest_candidate_timestamp(candidates: list[dict]) -> str:
    stamps = [str(item.get("recorded_at_utc") or "").strip() for item in candidates]
    stamps = [stamp for stamp in stamps if stamp]
    return max(stamps) if stamps else ""


def build_decision_manifest(
    decision_dir: Path,
    raw_session: Path,
    batch: str,
    session: str,
    audit_path: Path | None = None,
) -> pd.DataFrame:
    rows = []
    for path in sorted(decision_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if str(raw.get("task_type") or "") != "binding_scan":
            continue
        stage = int(raw.get("prefix_stage"))
        direction = str(raw.get("direction") or "").upper()
        prefix_valid = int(raw.get("prefix_valid"))
        binding_wheel = int(raw.get("binding_wheel"))
        upstream_digit = _upstream_digit(raw, stage)
        profile_id = str(raw.get("profile_id") or path.stem)
        match = re.search(r"_R(\d+)_", profile_id + "_")
        replicate = int(match.group(1)) if match else int(str(raw.get("group_id") or "R1")[-1])
        candidates = _candidate_list(raw)
        run_ids = [str(item.get("run_id") or "").strip() for item in candidates]
        if any(not run_id for run_id in run_ids):
            raise ValueError(f"Missing run_id in {path}")
        valid_candidates = sum(str(item.get("status") or "VALID").upper() == "VALID" for item in candidates)
        missing_raw_run_ids = []
        raw_complete_candidates = 0
        for run_id in run_ids:
            run_dir = raw_session / run_id
            if (run_dir / "audio_dual.wav").exists() and (run_dir / "events.csv").exists():
                raw_complete_candidates += 1
            else:
                missing_raw_run_ids.append(run_id)
        rows.append(
            {
                "batch": batch,
                "session": session,
                "decision_file": path.name,
                "profile_id": profile_id,
                "stage": stage,
                "direction": direction,
                "prefix_valid": prefix_valid,
                "probe_wheel": binding_wheel,
                "upstream_digit": upstream_digit,
                "replicate": replicate,
                "run_ids": "|".join(run_ids),
                "valid_candidates": int(valid_candidates),
                "raw_complete_candidates": int(raw_complete_candidates),
                "missing_raw_run_ids": "|".join(missing_raw_run_ids),
                "latest_recorded_at_utc": _latest_candidate_timestamp(candidates),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"No binding_scan decisions found in {decision_dir}")

    allowed = (
        frame["stage"].isin([1, 2])
        & frame["replicate"].isin([1, 2, 3])
        & frame["upstream_digit"].between(0, 9)
        & frame["direction"].isin(["CCW", "CW"])
    )
    unexpected = frame.loc[~allowed].copy()
    frame = frame.loc[allowed].copy()

    context_cols = ["stage", "replicate", "upstream_digit", "direction"]
    frame = frame.sort_values(
        context_cols + ["raw_complete_candidates", "valid_candidates", "latest_recorded_at_utc", "decision_file"],
        ascending=[True, True, True, True, False, False, False, False],
    )

    complete_frame = frame.loc[frame["raw_complete_candidates"].eq(10)].copy()
    canonical = complete_frame.drop_duplicates(context_cols, keep="first").copy()
    canonical_files = set(canonical["decision_file"].astype(str))

    audit = frame.copy()
    audit["selected"] = audit["decision_file"].astype(str).isin(canonical_files).astype(int)
    audit["selection_reason"] = np.where(
        audit["selected"].eq(1),
        "canonical raw-complete latest/highest-quality record for context",
        np.where(
            audit["raw_complete_candidates"].lt(10),
            "excluded because one or more referenced raw runs lack audio_dual.wav/events.csv",
            "superseded duplicate/re-record for same experimental context",
        ),
    )
    if not unexpected.empty:
        unexpected = unexpected.copy()
        unexpected["selected"] = 0
        unexpected["selection_reason"] = "outside expected Stage/Repeat/Digit/Direction grid"
        audit = pd.concat([audit, unexpected], ignore_index=True, sort=False)

    if audit_path is not None:
        Path(audit_path).parent.mkdir(parents=True, exist_ok=True)
        audit.sort_values(context_cols + ["selected"], ascending=[True, True, True, True, False]).to_csv(
            audit_path, index=False
        )

    duplicate_count = int(len(frame) - len(canonical))
    raw_incomplete_count = int(frame["raw_complete_candidates"].lt(10).sum())
    print(
        f"[{session}] binding decisions: {len(rows)} raw JSON -> "
        f"{len(canonical)} canonical contexts; {duplicate_count} non-canonical record(s) excluded "
        f"({raw_incomplete_count} with incomplete raw runs)"
    )

    if len(canonical) != 120:
        counts = canonical.groupby(["stage", "direction"]).size().to_dict()
        raise ValueError(
            f"Expected 120 unique Binding contexts in {session}; got {len(canonical)}. "
            f"Stage/direction counts: {counts}"
        )
    if canonical[context_cols].duplicated().any():
        raise ValueError(f"Duplicate canonical Binding contexts remain in {session}")

    expected_per_stage_direction = canonical.groupby(["stage", "direction"]).size()
    if not expected_per_stage_direction.eq(30).all():
        raise ValueError(
            f"Incomplete Binding context grid in {session}: "
            f"{expected_per_stage_direction.to_dict()}"
        )

    return (
        canonical.drop(columns=[
            "valid_candidates", "raw_complete_candidates", "missing_raw_run_ids", "latest_recorded_at_utc"
        ])
        .sort_values(context_cols)
        .reset_index(drop=True)
    )


def _aggregate_movement_features(feature_rows: list[dict[str, float]]) -> dict[str, float]:
    frame = pd.DataFrame(feature_rows)
    out: dict[str, float] = {}
    for column in frame.columns:
        values = frame[column].to_numpy(dtype=float)
        out[f"{column}__mean"] = float(np.mean(values))
        out[f"{column}__std"] = float(np.std(values, ddof=0))
        out[f"{column}__min"] = float(np.min(values))
        out[f"{column}__max"] = float(np.max(values))
    return out


def build_session_features(
    manifest: pd.DataFrame,
    raw_session: Path,
) -> pd.DataFrame:
    rows = []
    total = len(manifest)
    for i, item in manifest.iterrows():
        feature_rows = []
        for run_id in str(item["run_ids"]).split("|"):
            feature_rows.append(run_descriptors(raw_session / run_id))
        row = item.drop(labels=["run_ids"]).to_dict()
        row.update(_aggregate_movement_features(feature_rows))
        rows.append(row)
        if (i + 1) % 20 == 0 or i + 1 == total:
            print(f"    {i + 1}/{total} scans")
    return pd.DataFrame(rows)


def prepare_feature_cache(
    mydrive: Path,
    result_dir: Path,
    work_dir: Path,
    force: bool = False,
) -> pd.DataFrame:
    cache_path = result_dir / "RQ21_Scan_Features.csv"
    if cache_path.exists() and not force:
        cached = pd.read_csv(cache_path)
        if len(cached) == 360:
            print("Reusing persistent RQ21 scan-feature cache")
            return cached
    parts = []
    for batch, session in SESSIONS.items():
        raw_session, decisions = prepare_session(
            locate_zip(mydrive, session),
            locate_decision_dir(mydrive, session),
            work_dir,
            session,
        )
        manifest = build_decision_manifest(
            decisions,
            raw_session,
            batch,
            session,
            audit_path=result_dir / f"RQ21_{batch}_Decision_Canonicalisation.csv",
        )
        print(f"[{session}] extract compact scan-level features")
        part = build_session_features(manifest, raw_session)
        parts.append(part)
        shutil.rmtree(work_dir / session, ignore_errors=True)
        shutil.rmtree(work_dir / f"{session}_decisions", ignore_errors=True)
    features = pd.concat(parts, ignore_index=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    features.to_csv(cache_path, index=False)
    return features


def feature_columns(frame: pd.DataFrame) -> list[str]:
    metadata = {
        "batch", "session", "decision_file", "profile_id", "stage", "direction",
        "prefix_valid", "probe_wheel", "upstream_digit", "replicate",
    }
    return [column for column in frame.columns if column not in metadata]


def _auc_strength(y: np.ndarray, x: np.ndarray) -> float:
    if np.nanstd(x) < 1e-12:
        return 0.5
    try:
        auc = float(roc_auc_score(y, x))
    except ValueError:
        return 0.5
    return max(auc, 1.0 - auc)


def select_features(frame: pd.DataFrame, columns: list[str], k: int = TOP_K_FEATURES) -> list[str]:
    y = frame["prefix_valid"].to_numpy(dtype=int)
    ranked = sorted(
        ((column, _auc_strength(y, frame[column].to_numpy(dtype=float))) for column in columns),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return [column for column, _ in ranked[:k]]


def _fit_logistic(train: pd.DataFrame, selected: list[str]):
    scaler = StandardScaler()
    X = scaler.fit_transform(train[selected].to_numpy(dtype=float))
    y = train["prefix_valid"].to_numpy(dtype=int)
    model = LogisticRegression(
        C=0.5,
        class_weight="balanced",
        solver="liblinear",
        max_iter=3000,
        random_state=21,
    )
    model.fit(X, y)
    return scaler, model


def _score(model_bundle, frame: pd.DataFrame, selected: list[str]) -> np.ndarray:
    scaler, model = model_bundle
    X = scaler.transform(frame[selected].to_numpy(dtype=float))
    return model.predict_proba(X)[:, 1]


def fit_and_score(features: pd.DataFrame, result_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    columns = feature_columns(features)
    test_rows = []
    model_rows = []
    dev_rows = []
    for stage in [1, 2]:
        for direction in ["CCW", "CW"]:
            dev = features[
                features["batch"].isin(["B01", "B02"])
                & (features["stage"] == stage)
                & (features["direction"] == direction)
            ].copy()
            test = features[
                (features["batch"] == "B03")
                & (features["stage"] == stage)
                & (features["direction"] == direction)
            ].copy()
            selected = select_features(dev, columns)
            bundle = _fit_logistic(dev, selected)
            dev_score = _score(bundle, dev, selected)
            test_score = _score(bundle, test, selected)
            correct_dev = dev_score[dev["prefix_valid"].to_numpy(dtype=int) == 1]
            threshold = float(np.min(correct_dev) - 1e-9)
            dev["binding_score"] = dev_score
            dev["veto"] = (dev_score < threshold).astype(int)
            test["binding_score"] = test_score
            test["veto"] = (test_score < threshold).astype(int)
            dev_rows.append(dev)
            test_rows.append(test)
            auc = float(roc_auc_score(test["prefix_valid"], test_score))
            model_rows.append(
                {
                    "stage": stage,
                    "direction": direction,
                    "n_dev": len(dev),
                    "n_test": len(test),
                    "selected_features": "|".join(selected),
                    "threshold": threshold,
                    "b03_auc": auc,
                }
            )
    dev_scores = pd.concat(dev_rows, ignore_index=True)
    b03_scores = pd.concat(test_rows, ignore_index=True)
    model_summary = pd.DataFrame(model_rows)
    dev_scores.to_csv(result_dir / "RQ21_Development_Scores.csv", index=False)
    b03_scores.to_csv(result_dir / "RQ21_B03_Direction_Scores.csv", index=False)
    model_summary.to_csv(result_dir / "RQ21_Model_Summary.csv", index=False)
    return dev_scores, b03_scores, model_summary


def _pair_direction_scores(frame: pd.DataFrame) -> pd.DataFrame:
    keys = ["batch", "stage", "replicate", "upstream_digit", "prefix_valid", "probe_wheel"]
    pivot = frame.pivot_table(
        index=keys,
        columns="direction",
        values=["binding_score", "veto"],
        aggfunc="first",
    )
    pivot.columns = [f"{a}_{b}" for a, b in pivot.columns]
    return pivot.reset_index()


def select_veto_rules(dev_scores: pd.DataFrame, result_dir: Path) -> pd.DataFrame:
    paired = _pair_direction_scores(dev_scores)
    rows = []
    for stage in [1, 2]:
        part = paired[paired["stage"] == stage].copy()
        rule_masks = {
            "CCW_ONLY": part["veto_CCW"].astype(bool),
            "BOTH_DIRECTIONS": part["veto_CCW"].astype(bool) & part["veto_CW"].astype(bool),
        }
        candidates = []
        for rule, mask in rule_masks.items():
            y = part["prefix_valid"].to_numpy(dtype=int)
            correct = y == 1
            wrong = y == 0
            false_reject = int(np.sum(mask.to_numpy()[correct]))
            wrong_reject = int(np.sum(mask.to_numpy()[wrong]))
            candidates.append((rule, false_reject, wrong_reject))
        safe = [item for item in candidates if item[1] == 0]
        if not safe:
            selected = min(candidates, key=lambda item: (item[1], -item[2], item[0]))
        else:
            selected = max(safe, key=lambda item: (item[2], item[0] == "BOTH_DIRECTIONS"))
        rows.append(
            {
                "stage": stage,
                "selected_rule": selected[0],
                "development_correct_false_rejects": selected[1],
                "development_wrong_rejects": selected[2],
            }
        )
    rules = pd.DataFrame(rows)
    rules.to_csv(result_dir / "RQ21_Development_Veto_Rules.csv", index=False)
    return rules


def evaluate_b03_veto(
    b03_scores: pd.DataFrame,
    rules: pd.DataFrame,
    result_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paired = _pair_direction_scores(b03_scores)
    detail_rows = []
    summary_rows = []
    for stage in [1, 2]:
        rule = str(rules.loc[rules["stage"] == stage, "selected_rule"].iloc[0])
        part = paired[paired["stage"] == stage].copy()
        if rule == "CCW_ONLY":
            veto = part["veto_CCW"].astype(bool)
        else:
            veto = part["veto_CCW"].astype(bool) & part["veto_CW"].astype(bool)
        part["selected_rule"] = rule
        part["selected_veto"] = veto.astype(int)
        detail_rows.append(part)
        y = part["prefix_valid"].to_numpy(dtype=int)
        mask = veto.to_numpy(dtype=bool)
        correct = y == 1
        wrong = y == 0
        correct_rejected = int(np.sum(mask[correct]))
        wrong_rejected = int(np.sum(mask[wrong]))
        summary_rows.append(
            {
                "stage": stage,
                "selected_rule": rule,
                "correct_n": int(correct.sum()),
                "correct_rejected": correct_rejected,
                "correct_false_reject_rate": float(correct_rejected / correct.sum()),
                "wrong_n": int(wrong.sum()),
                "wrong_rejected": wrong_rejected,
                "wrong_reject_rate": float(wrong_rejected / wrong.sum()),
            }
        )
    detail = pd.concat(detail_rows, ignore_index=True)
    summary = pd.DataFrame(summary_rows)
    detail.to_csv(result_dir / "RQ21_B03_Veto_Detail.csv", index=False)
    summary.to_csv(result_dir / "RQ21_B03_Veto_Summary.csv", index=False)
    return detail, summary


def save_figures(model_summary: pd.DataFrame, veto_summary: pd.DataFrame, result_dir: Path) -> None:
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.size": 10,
        "axes.labelsize": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    stage_labels = ["W2 after W1", "W4 after W1+W2"]
    x = np.arange(2)
    width = 0.28
    ccw = [
        float(model_summary[(model_summary["stage"] == stage) & (model_summary["direction"] == "CCW")]["b03_auc"].iloc[0])
        for stage in [1, 2]
    ]
    cw = [
        float(model_summary[(model_summary["stage"] == stage) & (model_summary["direction"] == "CW")]["b03_auc"].iloc[0])
        for stage in [1, 2]
    ]
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    b1 = ax.bar(x - width / 2, ccw, width, color=DARK_BLUE, label="CCW")
    b2 = ax.bar(x + width / 2, cw, width, color=LIGHT_BLUE, label="CW")
    for bars in (b1, b2):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.025,
                f"{bar.get_height():.2f}",
                ha="center",
                va="bottom",
                fontsize=9,
                color=DARK_GREY,
            )
    ax.axhline(0.5, color=DARK_GREY, linewidth=1, linestyle="--", alpha=0.5)
    ax.set_ylabel("B03 ROC AUC")
    ax.set_xticks(x)
    ax.set_xticklabels(stage_labels)
    ax.set_ylim(0, 1.08)
    ax.grid(axis="y", alpha=0.12)
    ax.legend(frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout()
    fig.savefig(result_dir / "RQ21_Fig1_B03_AUC.png", dpi=300, bbox_inches="tight")
    fig.savefig(result_dir / "RQ21_Fig1_B03_AUC.pdf", bbox_inches="tight")
    plt.show()

    correct = [
        float(veto_summary.loc[veto_summary["stage"] == stage, "correct_false_reject_rate"].iloc[0]) * 100
        for stage in [1, 2]
    ]
    wrong = [
        float(veto_summary.loc[veto_summary["stage"] == stage, "wrong_reject_rate"].iloc[0]) * 100
        for stage in [1, 2]
    ]
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    b1 = ax.bar(x - width / 2, wrong, width, color=DARK_BLUE, label="Wrong prefix rejected")
    b2 = ax.bar(x + width / 2, correct, width, color=LIGHT_BLUE, label="Correct prefix falsely rejected")
    for bars in (b1, b2):
        for bar in bars:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 2,
                f"{bar.get_height():.1f}%",
                ha="center",
                va="bottom",
                fontsize=9,
                color=DARK_GREY,
            )
    ax.set_ylabel("B03 veto rate")
    ax.set_xticks(x)
    ax.set_xticklabels(stage_labels)
    ax.set_ylim(0, max(30, max(wrong + correct) + 12))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, pos: f"{y:.0f}%"))
    ax.grid(axis="y", alpha=0.12)
    ax.legend(frameon=False, ncol=1, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout()
    fig.savefig(result_dir / "RQ21_Fig2_B03_Veto.png", dpi=300, bbox_inches="tight")
    fig.savefig(result_dir / "RQ21_Fig2_B03_Veto.pdf", bbox_inches="tight")
    plt.show()


def write_report(
    model_summary: pd.DataFrame,
    veto_summary: pd.DataFrame,
    result_dir: Path,
) -> None:
    def auc(stage: int, direction: str) -> float:
        return float(
            model_summary[(model_summary["stage"] == stage) & (model_summary["direction"] == direction)]["b03_auc"].iloc[0]
        )

    s1 = veto_summary[veto_summary["stage"] == 1].iloc[0]
    s2 = veto_summary[veto_summary["stage"] == 2].iloc[0]
    report = f"""# RQ21 — Binding as a Scan-Level State Detector / Safety Veto

## Research question

Can the ten movements in a Binding scan identify whether the upstream prefix is mechanically binding-like strongly enough to provide conservative backtracking evidence?

## Reproduction status

The exact historical state-detector training script was not recovered. This notebook is therefore a clean reimplementation of the frozen experimental formulation rather than a bitwise replay. The experimental boundary is preserved: Binding B01 and B02 are development-only; Binding B03 is held out from fitting and threshold selection. Archived B03 values are retained separately as historical reference and are not used for tuning.

## B03 direction-specific discrimination

| Stage | CCW AUC | CW AUC |
|---|---:|---:|
| W2 after W1 | {auc(1, 'CCW'):.3f} | {auc(1, 'CW'):.3f} |
| W4 after W1+W2 | {auc(2, 'CCW'):.3f} | {auc(2, 'CW'):.3f} |

Archived reference: Stage 1 approximately 0.85 CCW / 0.84 CW; Stage 2 approximately 0.57 CCW / 0.63 CW.

## Conservative veto on B03

| Stage | Frozen rule | Correct rejected | Wrong rejected |
|---|---|---:|---:|
| W2 after W1 | {s1['selected_rule']} | {int(s1['correct_rejected'])}/{int(s1['correct_n'])} | {int(s1['wrong_rejected'])}/{int(s1['wrong_n'])} |
| W4 after W1+W2 | {s2['selected_rule']} | {int(s2['correct_rejected'])}/{int(s2['correct_n'])} | {int(s2['wrong_rejected'])}/{int(s2['wrong_n'])} |

The veto threshold and the choice between CCW-only and both-direction agreement are selected using B01+B02 only. B03 is scored once after these choices are frozen.

## Interpretation

Binding is evaluated here as auxiliary state evidence, not as the primary True-Gate ranker. A useful safety veto should reject some clearly wrong prefixes while avoiding false rejection of correct prefixes. Stage 1 and Stage 2 are interpreted separately because the mechanical state changes as more upstream wheels are fixed.

## Limitations

B03 is only one password and was not pristine historically because it had been inspected in earlier exploratory work. The clean reimplementation also cannot claim identity with the unrecovered historical detector code. The dissertation should distinguish reproduced metrics from archived reference values.

## Decision

The clean reimplementation does not support deploying the reconstructed Binding veto because correct B03 prefixes are falsely rejected. Archived historical results remain comparison evidence only.
"""
    (result_dir / "RQ21_Report.md").write_text(report, encoding="utf-8")

    conclusion = {
        "research_question": "Can Binding act as a scan-level state detector / safety veto?",
        "development_data": ["Binding_B01_3175", "Binding_B02_8642"],
        "heldout_data": "Binding_B03_0528",
        "reproduction_type": "clean reimplementation; exact historical training script not recovered",
        "b03_auc": {
            "stage1_ccw": auc(1, "CCW"),
            "stage1_cw": auc(1, "CW"),
            "stage2_ccw": auc(2, "CCW"),
            "stage2_cw": auc(2, "CW"),
        },
        "b03_veto": {
            "stage1": s1.to_dict(),
            "stage2": s2.to_dict(),
        },
        "archived_reference": {
            "stage1_auc_ccw": 0.85,
            "stage1_auc_cw": 0.84,
            "stage1_correct_rejected": "0/3",
            "stage1_wrong_rejected": "6/27",
            "stage2_auc_ccw": 0.57,
            "stage2_auc_cw": 0.63,
        },
        "role": "reconstructed veto not supported for deployment; archived result retained as historical reference",
        "next_step": "RQ22 asks whether physical opening itself provides a more reliable confirmation signal than the reconstructed Binding veto.",
    }
    (result_dir / "RQ21_conclusion.json").write_text(
        json.dumps(conclusion, indent=2), encoding="utf-8"
    )

    run_info = {
        "development_sessions": [SESSIONS["B01"], SESSIONS["B02"]],
        "heldout_session": SESSIONS["B03"],
        "unit": "one 10-movement scan",
        "directions": ["CCW", "CW"],
        "stages": [1, 2],
        "model": "top-12 univariate scan features + StandardScaler + balanced LogisticRegression",
        "threshold": "minimum correct-prefix binding score on B01+B02 development data, minus epsilon",
        "rule_candidates": ["CCW_ONLY", "BOTH_DIRECTIONS"],
        "b03_used_for_tuning": False,
    }
    (result_dir / "RQ21_run_info.json").write_text(
        json.dumps(run_info, indent=2), encoding="utf-8"
    )
