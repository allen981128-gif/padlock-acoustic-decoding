from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import soundfile as sf

SAMPLE_RATE = 44_100
WINDOW_PRE_S = 0.030
WINDOW_POST_S = 0.120
RMS_THRESHOLD = 0.09
DRMS_THRESHOLD = 0.03
EXPECTED_SCANS = 16
EXPECTED_RUNS = 160
VALID_MOVEMENTS = tuple(range(1, 10))
DARK_BLUE = "#315B7D"
MID_BLUE = "#6F8FA8"
LIGHT_BLUE = "#AFC5D5"
DARK_GREY = "#596168"


def locate_repro_root(mydrive: Path) -> Path:
    candidates = [
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1",
        mydrive / "Padlock_Reproduction_v1",
    ]
    for root in candidates:
        if (root / "results").exists():
            return root
    raise FileNotFoundError("Could not locate Padlock_Reproduction_v1.")


def locate_dataset_root(mydrive: Path) -> Path:
    candidates = [
        mydrive / "dataset",
        mydrive / "Padlock_Reproduction_v1" / "dataset",
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1" / "dataset",
    ]
    for root in candidates:
        if (root / "raw" / "unlock.zip").exists():
            return root
    search_roots = [mydrive / "dataset", mydrive / "Padlock_Reproduction_v1"]
    matches = []
    for root in search_roots:
        if root.exists():
            matches.extend(root.rglob("unlock.zip"))
    matches = [p for p in matches if p.is_file() and p.stat().st_size > 10_000_000]
    if len(matches) == 1:
        return matches[0].parent.parent
    raise FileNotFoundError("Could not locate dataset/raw/unlock.zip.")


def locate_results_root(mydrive: Path) -> Path:
    return locate_repro_root(mydrive) / "results"


def locate_unlock_zip(mydrive: Path) -> Path:
    path = locate_dataset_root(mydrive) / "raw" / "unlock.zip"
    if not path.exists():
        raise FileNotFoundError(f"Missing unlock archive: {path}")
    return path


def locate_recognition_results(mydrive: Path) -> Path | None:
    path = locate_dataset_root(mydrive) / "recognition_results"
    return path if path.exists() else None


def _find_unlock_root(extract_dir: Path) -> Path:
    candidates = []
    for p in extract_dir.rglob("unlock"):
        if p.is_dir():
            n = len(list(p.glob("run_*")))
            if n >= EXPECTED_RUNS:
                candidates.append((n, p))
    if not candidates:
        raise FileNotFoundError("Could not locate extracted unlock/run_* data.")
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _read_run_features(run_dir: Path) -> dict:
    metadata_path = run_dir / "metadata.json"
    audio_path = run_dir / "audio.wav"
    events_path = run_dir / "events.csv"
    if not metadata_path.exists() or not audio_path.exists() or not events_path.exists():
        raise FileNotFoundError(f"Incomplete unlock run: {run_dir}")

    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    if meta.get("status") != "VALID":
        raise ValueError(f"Non-VALID run in unlock archive: {run_dir.name}")
    run = meta["run"]

    events = pd.read_csv(events_path)
    end_rows = events.loc[events["event"].astype(str).eq("SCAN_END")]
    if len(end_rows) != 1:
        raise ValueError(f"Expected one SCAN_END in {run_dir.name}, got {len(end_rows)}")
    end_sample = int(end_rows.iloc[0]["aligned_sample_index"])

    audio, sr = sf.read(audio_path, always_2d=False, dtype="float32")
    if int(sr) != SAMPLE_RATE:
        raise ValueError(f"Unexpected sample rate {sr} in {run_dir.name}")
    if audio.ndim != 1:
        audio = np.asarray(audio).reshape(-1)

    start = max(0, end_sample - int(round(WINDOW_PRE_S * sr)))
    stop = min(len(audio), end_sample + int(round(WINDOW_POST_S * sr)))
    window = np.asarray(audio[start:stop], dtype=np.float64)
    if len(window) < int(0.10 * sr):
        raise ValueError(f"Too-short SCAN_END window in {run_dir.name}: {len(window)} samples")

    rms = float(np.sqrt(np.mean(window ** 2)))
    diff = np.diff(window)
    drms = float(np.sqrt(np.mean(diff ** 2))) if len(diff) else float("nan")
    peak = float(np.max(np.abs(window)))

    move = int(run.get("decision_move_index", -1))
    is_unlock = int(run.get("decision_is_target", 0))
    profile = str(run.get("profile_id", ""))
    if not profile:
        raise ValueError(f"Missing profile_id in {run_dir.name}")

    return {
        "run_id": run_dir.name,
        "profile_id": profile,
        "direction": str(run.get("direction", "")),
        "move_index": move,
        "is_unlock": is_unlock,
        "before_code": str(run.get("current_code_before", "")),
        "after_code": str(run.get("current_code_after", "")),
        "rms": rms,
        "drms": drms,
        "peak": peak,
        "window_samples": int(len(window)),
        "scan_end_sample": end_sample,
    }


def prepare_unlock_feature_cache(
    mydrive: Path,
    result_dir: Path,
    work_dir: Path,
    force: bool = False,
) -> pd.DataFrame:
    result_dir = Path(result_dir)
    work_dir = Path(work_dir)
    cache_path = result_dir / "RQ22_Unlock_Features.csv"
    if cache_path.exists() and not force:
        frame = pd.read_csv(cache_path)
        if len(frame) == EXPECTED_RUNS:
            print(f"Reusing persistent unlock feature cache: {cache_path}")
            return frame

    zip_path = locate_unlock_zip(Path(mydrive))
    work_dir.mkdir(parents=True, exist_ok=True)
    local_zip = work_dir / "unlock.zip"
    extract_dir = work_dir / "unlock_extract"

    if force and extract_dir.exists():
        shutil.rmtree(extract_dir)
    if not extract_dir.exists():
        if local_zip.exists():
            local_zip.unlink()
        print(f"Copying unlock.zip to local Colab storage ({zip_path.stat().st_size / 1e6:.1f} MB)")
        shutil.copy2(zip_path, local_zip)
        print("Extracting unlock.zip locally")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(local_zip, "r") as zf:
            zf.extractall(extract_dir)
        local_zip.unlink(missing_ok=True)
    else:
        print("Reusing local unlock extraction")

    unlock_root = _find_unlock_root(extract_dir)
    run_dirs = sorted(unlock_root.glob("run_*"))
    if len(run_dirs) != EXPECTED_RUNS:
        raise ValueError(f"Expected {EXPECTED_RUNS} unlock runs, got {len(run_dirs)}")

    rows = []
    for i, run_dir in enumerate(run_dirs, start=1):
        rows.append(_read_run_features(run_dir))
        if i % 20 == 0 or i == len(run_dirs):
            print(f"  {i}/{len(run_dirs)} runs")

    frame = pd.DataFrame(rows).sort_values(["profile_id", "move_index"]).reset_index(drop=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(cache_path, index=False)
    print(f"Saved persistent feature cache: {cache_path}")
    return frame


def controlled_validation(features: pd.DataFrame, result_dir: Path):
    result_dir = Path(result_dir)
    frame = features.copy()
    frame["analysis_included"] = frame["move_index"].isin(VALID_MOVEMENTS)
    valid = frame[frame["analysis_included"]].copy()

    profile_qc = valid.groupby("profile_id", as_index=False).agg(
        n_valid=("run_id", "size"),
        n_unlock=("is_unlock", "sum"),
        min_move=("move_index", "min"),
        max_move=("move_index", "max"),
    )
    if len(profile_qc) != EXPECTED_SCANS:
        raise ValueError(f"Expected {EXPECTED_SCANS} scans, got {len(profile_qc)}")
    if not profile_qc["n_valid"].eq(9).all() or not profile_qc["n_unlock"].eq(1).all():
        raise ValueError("Each unlock scan must contain 8 normal pre-unlock movements and 1 unlock movement.")

    valid["pred_unlock"] = ((valid["rms"] > RMS_THRESHOLD) & (valid["drms"] > DRMS_THRESHOLD)).astype(int)
    valid["correct"] = valid["pred_unlock"].eq(valid["is_unlock"])

    cls_summary = valid.groupby("is_unlock", as_index=False).agg(
        n=("run_id", "size"),
        rms_min=("rms", "min"),
        rms_max=("rms", "max"),
        rms_mean=("rms", "mean"),
        drms_min=("drms", "min"),
        drms_max=("drms", "max"),
        drms_mean=("drms", "mean"),
        detected=("pred_unlock", "sum"),
        accuracy=("correct", "mean"),
    )
    cls_summary["class"] = cls_summary["is_unlock"].map({0: "Normal pre-unlock", 1: "Physical unlock"})

    scan_rows = []
    for profile, g in valid.groupby("profile_id"):
        g = g.sort_values("move_index")
        positives = g[g["pred_unlock"] == 1]
        unlock_row = g[g["is_unlock"] == 1].iloc[0]
        scan_rows.append({
            "profile_id": profile,
            "n_valid_movements": len(g),
            "trigger_count": len(positives),
            "trigger_move": int(positives.iloc[0]["move_index"]) if len(positives) else np.nan,
            "true_unlock_move": int(unlock_row["move_index"]),
            "scan_success": int(len(positives) == 1 and int(positives.iloc[0]["move_index"]) == int(unlock_row["move_index"])) if len(positives) else 0,
            "unlock_rms": float(unlock_row["rms"]),
            "unlock_drms": float(unlock_row["drms"]),
        })
    scan_results = pd.DataFrame(scan_rows).sort_values("profile_id").reset_index(drop=True)

    tn = int(((valid["is_unlock"] == 0) & (valid["pred_unlock"] == 0)).sum())
    fp = int(((valid["is_unlock"] == 0) & (valid["pred_unlock"] == 1)).sum())
    fn = int(((valid["is_unlock"] == 1) & (valid["pred_unlock"] == 0)).sum())
    tp = int(((valid["is_unlock"] == 1) & (valid["pred_unlock"] == 1)).sum())

    normal = valid[valid["is_unlock"] == 0]
    unlock = valid[valid["is_unlock"] == 1]
    metrics = pd.DataFrame([{
        "n_scans": int(valid["profile_id"].nunique()),
        "n_valid_movements": int(len(valid)),
        "n_normal": int(len(normal)),
        "n_unlock": int(len(unlock)),
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "movement_accuracy": float((tn + tp) / len(valid)),
        "scan_success_rate": float(scan_results["scan_success"].mean()),
        "normal_rms_max": float(normal["rms"].max()),
        "unlock_rms_min": float(unlock["rms"].min()),
        "rms_gap": float(unlock["rms"].min() - normal["rms"].max()),
        "normal_drms_max": float(normal["drms"].max()),
        "unlock_drms_min": float(unlock["drms"].min()),
        "drms_gap": float(unlock["drms"].min() - normal["drms"].max()),
        "rms_threshold": RMS_THRESHOLD,
        "drms_threshold": DRMS_THRESHOLD,
    }])

    valid.to_csv(result_dir / "RQ22_Controlled_Movement_Results.csv", index=False)
    cls_summary.to_csv(result_dir / "RQ22_Class_Summary.csv", index=False)
    scan_results.to_csv(result_dir / "RQ22_Scan_Level_Results.csv", index=False)
    metrics.to_csv(result_dir / "RQ22_Controlled_Metrics.csv", index=False)
    return valid, cls_summary, scan_results, metrics


_TRIGGER_RE = re.compile(r"Possible physical unlock detected at W3=(\d+) \(RMS ([0-9.]+), dRMS ([0-9.]+)\)")
_REJECT_RE = re.compile(r"Operator rejected the unlock trigger at W3=(\d+)")
_CONFIRM_RE = re.compile(r"UNLOCK CONFIRMED by operator\. Detected combination: (\d{4})")
_SESSION_RE = re.compile(r"AUTO_(\d{4})_\d+$")


def parse_operational_logs(recognition_root: Path | None, result_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    result_dir = Path(result_dir)
    rows = []
    if recognition_root is None or not Path(recognition_root).exists():
        triggers = pd.DataFrame(columns=["session", "true_combination", "true_w3", "trigger_w3", "rms", "drms", "outcome", "confirmed_combination", "trigger_matches_true_w3"])
        summary = pd.DataFrame([{"sessions_scanned": 0, "triggers": 0, "confirmed": 0, "rejected": 0, "unresolved": 0, "confirmation_rate": np.nan}])
        triggers.to_csv(result_dir / "RQ22_Operational_Triggers.csv", index=False)
        summary.to_csv(result_dir / "RQ22_Operational_Summary.csv", index=False)
        return triggers, summary

    folders = sorted([p for p in Path(recognition_root).glob("AUTO_*") if p.is_dir()])
    sessions_scanned = 0
    for folder in folders:
        log_path = folder / "AUTO_console_log.txt"
        if not log_path.exists():
            continue
        m_session = _SESSION_RE.fullmatch(folder.name)
        if not m_session:
            continue
        sessions_scanned += 1
        true_combination = m_session.group(1)
        true_w3 = int(true_combination[2])
        pending = None
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines:
            m = _TRIGGER_RE.search(line)
            if m:
                if pending is not None:
                    pending["outcome"] = "unresolved"
                    rows.append(pending)
                pending = {
                    "session": folder.name,
                    "true_combination": true_combination,
                    "true_w3": true_w3,
                    "trigger_w3": int(m.group(1)),
                    "rms": float(m.group(2)),
                    "drms": float(m.group(3)),
                    "outcome": "pending",
                    "confirmed_combination": "",
                }
                continue
            m = _REJECT_RE.search(line)
            if m and pending is not None:
                pending["outcome"] = "rejected"
                rows.append(pending)
                pending = None
                continue
            m = _CONFIRM_RE.search(line)
            if m and pending is not None:
                pending["outcome"] = "confirmed"
                pending["confirmed_combination"] = m.group(1)
                rows.append(pending)
                pending = None
        if pending is not None:
            pending["outcome"] = "unresolved"
            rows.append(pending)

    triggers = pd.DataFrame(rows)
    if len(triggers):
        triggers["trigger_matches_true_w3"] = triggers["trigger_w3"].eq(triggers["true_w3"])
    else:
        triggers = pd.DataFrame(columns=["session", "true_combination", "true_w3", "trigger_w3", "rms", "drms", "outcome", "confirmed_combination", "trigger_matches_true_w3"])

    confirmed = int((triggers["outcome"] == "confirmed").sum()) if len(triggers) else 0
    rejected = int((triggers["outcome"] == "rejected").sum()) if len(triggers) else 0
    unresolved = int((triggers["outcome"] == "unresolved").sum()) if len(triggers) else 0
    denom = confirmed + rejected
    summary = pd.DataFrame([{
        "sessions_scanned": sessions_scanned,
        "triggers": int(len(triggers)),
        "confirmed": confirmed,
        "rejected": rejected,
        "unresolved": unresolved,
        "confirmation_rate": float(confirmed / denom) if denom else np.nan,
        "confirmed_true_w3_match_rate": float(triggers.loc[triggers["outcome"].eq("confirmed"), "trigger_matches_true_w3"].mean()) if confirmed else np.nan,
    }])
    triggers.to_csv(result_dir / "RQ22_Operational_Triggers.csv", index=False)
    summary.to_csv(result_dir / "RQ22_Operational_Summary.csv", index=False)
    return triggers, summary


def save_figures(metrics: pd.DataFrame, result_dir: Path):
    result_dir = Path(result_dir)
    row = metrics.iloc[0]

    plt.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 300,
        "font.size": 10,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    def _bar(values, labels, ylabel, stem):
        fig, ax = plt.subplots(figsize=(6.8, 4.2))
        x = np.arange(len(values))
        bars = ax.bar(x, values, width=0.55, color=[LIGHT_BLUE, MID_BLUE, DARK_BLUE], edgecolor="none", zorder=3)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.035,
                    f"{value:.4f}", ha="center", va="bottom", fontsize=9, color=DARK_GREY)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel(ylabel)
        ax.set_ylim(0, max(values) * 1.22)
        ax.grid(axis="y", alpha=0.12, zorder=0)
        fig.tight_layout()
        fig.savefig(result_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(result_dir / f"{stem}.pdf", bbox_inches="tight")
        plt.show()

    _bar(
        [float(row["normal_rms_max"]), float(row["rms_threshold"]), float(row["unlock_rms_min"])],
        ["Normal max", "Frozen threshold", "Unlock min"],
        "RMS in SCAN_END window",
        "RQ22_Fig1_RMS_Separation",
    )
    _bar(
        [float(row["normal_drms_max"]), float(row["drms_threshold"]), float(row["unlock_drms_min"])],
        ["Normal max", "Frozen threshold", "Unlock min"],
        "Derivative RMS in SCAN_END window",
        "RQ22_Fig2_dRMS_Separation",
    )


def write_report(metrics: pd.DataFrame, class_summary: pd.DataFrame, operational_summary: pd.DataFrame, result_dir: Path):
    result_dir = Path(result_dir)
    m = metrics.iloc[0]
    op = operational_summary.iloc[0]
    normal = class_summary[class_summary["is_unlock"].eq(0)].iloc[0]
    unlock = class_summary[class_summary["is_unlock"].eq(1)].iloc[0]

    lines = [
        "# RQ22 — W3 Physical Unlock Detector",
        "",
        "## Research question",
        "",
        "Under the controlled W3 protocol, can the physical unlock/release event be separated from ordinary pre-unlock digit movements, and how should detector triggers be interpreted operationally?",
        "",
        "## Controlled dataset",
        "",
        "The dedicated `unlock` collection contains 16 independently reseated CCW W3 scans for password 6800. Each scan contains ten one-digit movements. Movements 1–8 are normal pre-unlock movements, movement 9 is the physical unlock/release event, and movement 10 occurs after unlocking and is excluded from detector evaluation.",
        "",
        "Only the contact microphone (`audio.wav`) is used. RMS and derivative RMS are measured in a fixed 150 ms window from 30 ms before to 120 ms after `SCAN_END`.",
        "",
        "The historical frozen Physical Unlock Detector v1 rule is evaluated without retuning: RMS > 0.09 AND derivative RMS > 0.03.",
        "",
        "## Controlled results",
        "",
        f"- Valid evaluation movements: {int(m['n_valid_movements'])} ({int(m['n_normal'])} normal + {int(m['n_unlock'])} unlock).",
        f"- Movement-level accuracy: {100*m['movement_accuracy']:.1f}% ({int(m['tn']+m['tp'])}/{int(m['n_valid_movements'])}).",
        f"- Scan-level success: {100*m['scan_success_rate']:.1f}% ({int(round(m['scan_success_rate']*m['n_scans']))}/{int(m['n_scans'])} scans triggered exactly once at the true unlock movement).",
        f"- Normal RMS range: {normal['rms_min']:.4f}–{normal['rms_max']:.4f}; unlock RMS range: {unlock['rms_min']:.4f}–{unlock['rms_max']:.4f}.",
        f"- Normal dRMS range: {normal['drms_min']:.4f}–{normal['drms_max']:.4f}; unlock dRMS range: {unlock['drms_min']:.4f}–{unlock['drms_max']:.4f}.",
        f"- RMS class gap: {m['rms_gap']:.4f}; dRMS class gap: {m['drms_gap']:.4f}.",
        "",
        "## Operational evidence",
        "",
    ]
    if int(op["sessions_scanned"]) > 0:
        lines += [
            f"The archived `recognition_results/AUTO_####_##` logs contain {int(op['triggers'])} Physical Unlock Detector v1 trigger(s) across {int(op['sessions_scanned'])} named-password sessions.",
            f"Of resolved triggers, {int(op['confirmed'])} were confirmed by the operator and {int(op['rejected'])} were rejected; {int(op['unresolved'])} remained unresolved in the parsed logs.",
            "This operational evidence is descriptive rather than a sensitivity estimate, because the logs contain trigger outcomes rather than exhaustive physical ground truth for every untriggered movement.",
        ]
    else:
        lines += ["Operational recognition logs were not available in the mounted dataset during this run."]

    lines += [
        "",
        "## Interpretation",
        "",
        "The controlled data show that the physical unlock event is acoustically much stronger than ordinary pre-unlock W3 movements and is separable using a deterministic two-feature rule. A complex classifier is not required for this controlled task.",
        "",
        "However, the detector should remain a separate physical confirmation layer rather than a digit-ranking model. Operational logs can contain release-like triggers that the operator rejects, so a threshold crossing alone should not be treated as definitive proof of successful opening.",
        "",
        "## Limitations",
        "",
        "The dedicated controlled collection uses one password (6800), one direction (CCW), one lock and one hardware configuration. The frozen thresholds were derived during development and the 6800 collection is therefore best interpreted as controlled validation/characterisation, not as a new prospective threshold-selection test. Movement 10 is deliberately excluded because it occurs after the shackle has opened.",
        "",
        "## Decision",
        "",
        "Retain Physical Unlock Detector v1 as a lightweight W3 stop/confirmation cue with operator confirmation. Do not use it as a replacement for True-Gate ranking, and do not treat an unconfirmed trigger as an unlock success.",
    ]
    (result_dir / "RQ22_Report.md").write_text("\n".join(lines), encoding="utf-8")

    conclusion = {
        "research_question": "Under the controlled W3 protocol, can the physical unlock/release event be separated from ordinary pre-unlock digit movements, and how should detector triggers be interpreted operationally?",
        "controlled_dataset": "unlock / password 6800 / 16 CCW scans",
        "window": "SCAN_END -30 ms to +120 ms on contact microphone",
        "frozen_rule": {"rms_gt": RMS_THRESHOLD, "drms_gt": DRMS_THRESHOLD},
        "controlled_movement_accuracy": float(m["movement_accuracy"]),
        "controlled_scan_success_rate": float(m["scan_success_rate"]),
        "rms_gap": float(m["rms_gap"]),
        "drms_gap": float(m["drms_gap"]),
        "operational_sessions_scanned": int(op["sessions_scanned"]),
        "operational_triggers": int(op["triggers"]),
        "operator_confirmed_triggers": int(op["confirmed"]),
        "operator_rejected_triggers": int(op["rejected"]),
        "decision": "retain as separate physical stop/confirmation cue with operator confirmation",
        "next_step": "RQ23 tests closed-loop recovery after a failed physical attempt, using physical unlock confirmation as the final success criterion",
    }
    (result_dir / "RQ22_conclusion.json").write_text(json.dumps(conclusion, indent=2), encoding="utf-8")


def run_all(mydrive: Path, result_dir: Path, work_dir: Path, force_cache: bool = False):
    features = prepare_unlock_feature_cache(mydrive, result_dir, work_dir, force=force_cache)
    valid, class_summary, scan_results, metrics = controlled_validation(features, result_dir)
    recognition_root = locate_recognition_results(Path(mydrive))
    triggers, operational_summary = parse_operational_logs(recognition_root, result_dir)
    save_figures(metrics, result_dir)
    write_report(metrics, class_summary, operational_summary, result_dir)
    return {
        "features": features,
        "controlled": valid,
        "class_summary": class_summary,
        "scan_results": scan_results,
        "metrics": metrics,
        "operational_triggers": triggers,
        "operational_summary": operational_summary,
    }
