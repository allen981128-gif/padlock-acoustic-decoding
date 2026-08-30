from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BINDING_SESSION = "Binding_B03_0528"
EXPECTED_PASSWORD = "0528"
EXPECTED_DECISIONS = 120
EXPECTED_RUNS = 1200
DARK_BLUE = "#315B7D"
MID_BLUE = "#6F8FA8"
LIGHT_BLUE = "#AFC5D5"
MID_GREY = "#9EA5AA"
DARK_GREY = "#596168"


def locate_repro_root(mydrive: Path) -> Path:
    candidates = [
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1",
        mydrive / "Padlock_Reproduction_v1",
    ]
    for root in candidates:
        if (root / "src" / "true_gate_inference.py").exists() and (root / "model_assets").exists():
            return root
    raise FileNotFoundError("Could not locate Padlock_Reproduction_v1 source/model_assets.")


def locate_results_root(mydrive: Path) -> Path:
    candidates = [
        mydrive / "Padlock_Reproduction_v1" / "results",
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1" / "results",
    ]
    for root in candidates:
        if root.exists():
            return root
    raise FileNotFoundError("Could not locate the active results folder.")


def locate_binding_zip(mydrive: Path) -> Path:
    candidates = [
        mydrive / "dataset" / "raw" / f"{BINDING_SESSION}.zip",
        mydrive / "dataset" / "dataset" / "raw" / f"{BINDING_SESSION}.zip",
        mydrive / "Padlock_Reproduction_v1" / "dataset" / "raw" / f"{BINDING_SESSION}.zip",
        mydrive / "Padlock_Reproduction_v1" / "Padlock_Reproduction_v1" / "dataset" / "raw" / f"{BINDING_SESSION}.zip",
    ]
    for path in candidates:
        if path.exists() and path.stat().st_size > 50_000_000:
            return path

    search_roots = [
        mydrive / "dataset",
        mydrive / "Padlock_Reproduction_v1",
    ]
    matches = []
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob(f"{BINDING_SESSION}.zip"):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 50_000_000:
                matches.append(path)
    if not matches:
        raise FileNotFoundError(
            f"Could not locate the full raw {BINDING_SESSION}.zip archive (>50 MB)."
        )
    matches.sort(key=lambda p: p.stat().st_size, reverse=True)
    return matches[0]


def locate_binding_decision_dir(mydrive: Path) -> Path:
    candidates = [
        mydrive / "dataset" / "binding_scans" / "_progress" / BINDING_SESSION,
        mydrive / "dataset" / "dataset" / "binding_scans" / "_progress" / BINDING_SESSION,
    ]
    for path in candidates:
        if path.is_dir():
            files = list(path.glob("B03_S*_MP0528_A.json"))
            if len(files) == EXPECTED_DECISIONS:
                return path

    search_root = mydrive / "dataset"
    if search_root.exists():
        matches = []
        for path in search_root.rglob(BINDING_SESSION):
            if not path.is_dir():
                continue
            files = list(path.glob("B03_S*_MP0528_A.json"))
            if len(files) == EXPECTED_DECISIONS:
                matches.append(path)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            preferred = [p for p in matches if p.parent.name == "_progress" and p.parent.parent.name == "binding_scans"]
            if len(preferred) == 1:
                return preferred[0]
            raise RuntimeError(f"Multiple complete Binding B03 decision folders found: {matches}")

    raise FileNotFoundError(
        "Could not locate the 120 Binding B03 decision JSON files under "
        "dataset/binding_scans/_progress/Binding_B03_0528."
    )


def prepare_local_binding_data(
    binding_zip: Path,
    decision_source: Path,
    work_dir: Path,
    force: bool = False,
) -> tuple[Path, Path]:
    work_dir = Path(work_dir)
    extract_dir = work_dir / BINDING_SESSION
    local_zip = work_dir / f"{BINDING_SESSION}.zip"
    marker = extract_dir / ".rq20_extract_complete"

    if force and extract_dir.exists():
        shutil.rmtree(extract_dir)

    if not marker.exists():
        work_dir.mkdir(parents=True, exist_ok=True)
        if local_zip.exists():
            local_zip.unlink()
        print(f"Copying {binding_zip.name} to local Colab storage ({binding_zip.stat().st_size / 1e6:.1f} MB)")
        shutil.copy2(binding_zip, local_zip)
        print("Extracting Binding B03 locally")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(local_zip, "r") as zf:
            zf.extractall(extract_dir)
        marker.write_text("complete\n", encoding="utf-8")
        local_zip.unlink(missing_ok=True)
    else:
        print("Reusing local Binding B03 extraction")

    dataset_root = find_dataset_root(extract_dir)

    decision_source = Path(decision_source)
    source_files = sorted(decision_source.glob("B03_S*_MP0528_A.json"))
    if len(source_files) != EXPECTED_DECISIONS:
        raise FileNotFoundError(
            f"Expected {EXPECTED_DECISIONS} Binding B03 decision JSON files in {decision_source}, "
            f"found {len(source_files)}."
        )

    local_decision_root = work_dir / "decision_results" / BINDING_SESSION
    local_files = list(local_decision_root.glob("B03_S*_MP0528_A.json")) if local_decision_root.exists() else []
    if force or len(local_files) != EXPECTED_DECISIONS:
        if local_decision_root.exists():
            shutil.rmtree(local_decision_root)
        local_decision_root.mkdir(parents=True, exist_ok=True)
        print(f"Copying {EXPECTED_DECISIONS} Binding B03 decision JSON files to local Colab storage")
        for src in source_files:
            shutil.copy2(src, local_decision_root / src.name)
    else:
        print("Reusing local Binding B03 decision JSON files")

    return dataset_root, local_decision_root


def find_dataset_root(extract_dir: Path) -> Path:
    extract_dir = Path(extract_dir)

    def inspect_session(path: Path) -> tuple[bool, int]:
        if not path.is_dir():
            return False, 0
        try:
            run_dirs = [p for p in path.iterdir() if p.is_dir() and p.name.startswith("run_")]
        except OSError:
            return False, 0
        if not run_dirs:
            return False, 0
        sample = run_dirs[0]
        looks_raw = (sample / "audio_dual.wav").exists() and (sample / "events.csv").exists()
        return looks_raw, len(run_dirs)

    exact_candidates = [
        extract_dir / "raw" / BINDING_SESSION,
        extract_dir / BINDING_SESSION,
    ]
    for path in exact_candidates:
        valid, n_runs = inspect_session(path)
        if valid and n_runs == EXPECTED_RUNS:
            raw_session = path
            break
    else:
        raw_session = None

    if raw_session is None:
        named_candidates = []
        for path in extract_dir.rglob(BINDING_SESSION):
            valid, n_runs = inspect_session(path)
            if valid:
                named_candidates.append((n_runs, path))
        if named_candidates:
            named_candidates.sort(key=lambda item: item[0], reverse=True)
            raw_session = named_candidates[0][1]

    if raw_session is None:
        parent_counts = {}
        for run_dir in extract_dir.rglob("run_*"):
            if not run_dir.is_dir():
                continue
            if not (run_dir / "audio_dual.wav").exists() or not (run_dir / "events.csv").exists():
                continue
            parent_counts[run_dir.parent] = parent_counts.get(run_dir.parent, 0) + 1
        if parent_counts:
            raw_session = max(parent_counts, key=parent_counts.get)

    if raw_session is None:
        raise FileNotFoundError(
            "Could not locate the Binding B03 raw run directory after extraction."
        )

    valid, n_runs = inspect_session(raw_session)
    if not valid or n_runs != EXPECTED_RUNS:
        raise FileNotFoundError(
            f"Located candidate raw directory {raw_session}, but found {n_runs} valid run folders; "
            f"expected {EXPECTED_RUNS}."
        )

    if raw_session.parent.name.lower() == "raw":
        dataset_root = raw_session.parent.parent
        print(f"Binding B03 raw session: {raw_session} ({n_runs} runs)")
        return dataset_root

    shim_root = extract_dir / "_rq20_dataset_root"
    shim_raw = shim_root / "raw"
    shim_raw.mkdir(parents=True, exist_ok=True)
    shim_session = shim_raw / BINDING_SESSION

    if shim_session.exists() or shim_session.is_symlink():
        if shim_session.is_symlink() and shim_session.resolve() == raw_session.resolve():
            print(f"Binding B03 raw session: {raw_session} ({n_runs} runs)")
            print(f"Using existing local dataset shim: {shim_session}")
            return shim_root
        if shim_session.is_dir() and not shim_session.is_symlink():
            shutil.rmtree(shim_session)
        else:
            shim_session.unlink()

    shim_session.symlink_to(raw_session.resolve(), target_is_directory=True)
    print(f"Binding B03 raw session: {raw_session} ({n_runs} runs)")
    print(f"Created local dataset shim: {shim_session} -> {raw_session}")
    return shim_root


def _candidate_list(raw: dict) -> list[dict]:
    candidates = raw.get("candidates")
    if isinstance(candidates, list):
        rows = [row for row in candidates if isinstance(row, dict)]
    elif isinstance(candidates, dict):
        def key_fn(item):
            key, value = item
            try:
                return int(key)
            except (TypeError, ValueError):
                try:
                    return int(value.get("candidate_index", 0))
                except Exception:
                    return 0
        rows = [value for _, value in sorted(candidates.items(), key=key_fn) if isinstance(value, dict)]
    else:
        raise ValueError("Decision JSON has no valid candidates collection.")
    if len(rows) != 10:
        raise ValueError(f"Expected 10 candidates, found {len(rows)}")
    return rows


def _replicate_id(raw: dict, path: Path) -> int:
    for value in [raw.get("group_id"), raw.get("profile_id"), path.stem]:
        text = str(value or "")
        parts = text.split("_")
        for part in parts:
            if len(part) >= 2 and part[0] == "R" and part[1:].isdigit():
                return int(part[1:])
    raise ValueError(f"Could not parse replicate from {path.name}")


def _probe_wheel(raw: dict) -> int:
    for key in ["probe_wheel", "expected_binding_wheel", "binding_wheel"]:
        try:
            value = int(raw.get(key))
        except (TypeError, ValueError):
            continue
        if value in (1, 2, 4):
            return value
    active = raw.get("active_wheels")
    if isinstance(active, list) and len(active) == 1:
        value = int(active[0])
        if value in (1, 2, 4):
            return value
    raise ValueError("Could not determine probe wheel.")


def _upstream_digit(raw: dict, stage: int) -> int:
    code = str(raw.get("start_code") or "").strip()
    if len(code) != 4 or not code.isdigit():
        raise ValueError(f"Invalid start_code: {code}")
    index = 0 if stage == 1 else 1
    return int(code[index])


def build_control_manifest(decision_root: Path) -> pd.DataFrame:
    files = sorted(Path(decision_root).glob("B03_S*_MP0528_A.json"))
    if len(files) != EXPECTED_DECISIONS:
        raise AssertionError(f"Expected {EXPECTED_DECISIONS} Binding B03 decisions, found {len(files)}")

    rows = []
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if str(raw.get("task_type")) != "binding_scan":
            continue
        stage = int(raw.get("prefix_stage"))
        if stage not in (1, 2):
            continue
        direction = str(raw.get("direction") or "").upper()
        probe_wheel = _probe_wheel(raw)
        true_digits = raw.get("true_digits")
        if not isinstance(true_digits, list) or len(true_digits) < probe_wheel:
            raise ValueError(f"Missing true_digits in {path.name}")
        true_digit = int(true_digits[probe_wheel - 1])
        upstream_digit = _upstream_digit(raw, stage)
        upstream_true_digit = int(true_digits[0 if stage == 1 else 1])
        prefix_correct = int(upstream_digit == upstream_true_digit)
        prefix_valid = int(raw.get("prefix_valid"))
        if prefix_correct != prefix_valid:
            raise AssertionError(
                f"prefix_valid mismatch in {path.name}: derived={prefix_correct}, stored={prefix_valid}"
            )
        candidates = _candidate_list(raw)
        rows.append(
            {
                "decision_file": str(path),
                "decision_key": str(raw.get("decision_key") or path.stem),
                "session_id": str(raw.get("session_id") or BINDING_SESSION),
                "stage": stage,
                "replicate": _replicate_id(raw, path),
                "direction": direction,
                "probe_wheel": probe_wheel,
                "upstream_digit": upstream_digit,
                "upstream_true_digit": upstream_true_digit,
                "prefix_correct": prefix_correct,
                "true_digit": true_digit,
                "start_code": str(raw.get("start_code")),
                "n_candidates": len(candidates),
            }
        )

    manifest = pd.DataFrame(rows).sort_values(
        ["stage", "replicate", "upstream_digit", "direction"]
    ).reset_index(drop=True)

    assert len(manifest) == EXPECTED_DECISIONS
    assert set(manifest["direction"]) == {"CCW", "CW"}
    assert set(manifest["stage"]) == {1, 2}
    assert manifest.groupby("stage").size().eq(60).all()
    assert manifest.groupby(["stage", "replicate", "upstream_digit"]).size().eq(2).all()
    assert manifest.groupby("stage")["prefix_correct"].sum().eq(6).all()
    assert manifest["n_candidates"].eq(10).all()
    return manifest


def _load_binding_decision(path: Path) -> tuple[dict, SimpleNamespace]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    candidates = tuple(_candidate_list(raw))
    wheel = _probe_wheel(raw)
    decision = SimpleNamespace(
        path=path,
        raw=raw,
        profile_id=str(raw.get("profile_id") or path.stem),
        decision_key=str(raw.get("decision_key") or path.stem),
        session_id=str(raw.get("session_id") or BINDING_SESSION),
        direction=str(raw.get("direction") or "").upper(),
        repeat_id=str(raw.get("repeat_id") or "A").upper(),
        wheel=wheel,
        candidates=candidates,
    )
    return raw, decision


def score_manifest_with_main_v8(
    manifest: pd.DataFrame,
    dataset_root: Path,
    engine,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    if cache_path is not None and Path(cache_path).exists():
        cached = pd.read_csv(cache_path)
        expected = set(manifest["decision_key"])
        if len(cached) == len(manifest) and set(cached["decision_key"]) == expected:
            print("Reusing cached MAIN v8 direction scores")
            return cached

    rows = []
    total = len(manifest)
    for i, row in manifest.iterrows():
        path = Path(row["decision_file"])
        raw, decision = _load_binding_decision(path)
        scores = engine._score_decision(Path(dataset_root), decision)
        order = sorted(scores, key=scores.get, reverse=True)
        true_digit = int(row["true_digit"])
        true_rank = order.index(true_digit) + 1
        out = row.to_dict()
        out.update(
            {
                "pred_digit": int(order[0]),
                "true_rank": int(true_rank),
                "top1": int(true_rank <= 1),
                "top2": int(true_rank <= 2),
                "top3": int(true_rank <= 3),
                "margin": float(scores[order[0]] - scores[order[1]]),
                "true_score": float(scores[true_digit]),
            }
        )
        for digit in range(10):
            out[f"score_{digit}"] = float(scores[digit])
        rows.append(out)
        if (len(rows) % 10 == 0) or len(rows) == total:
            print(f"Scored {len(rows)}/{total} Binding B03 decisions")

    scores_df = pd.DataFrame(rows)
    if cache_path is not None:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        scores_df.to_csv(cache_path, index=False)
    return scores_df


def build_direction_paired_scores(direction_scores: pd.DataFrame) -> pd.DataFrame:
    score_cols = [f"score_{digit}" for digit in range(10)]
    group_cols = [
        "stage",
        "replicate",
        "probe_wheel",
        "upstream_digit",
        "upstream_true_digit",
        "prefix_correct",
        "true_digit",
    ]

    rows = []
    for keys, group in direction_scores.groupby(group_cols, sort=True):
        if set(group["direction"]) != {"CCW", "CW"} or len(group) != 2:
            raise AssertionError(f"Expected one CCW and one CW decision, got {group['direction'].tolist()}")
        scores = group[score_cols].mean(axis=0).to_numpy(dtype=float)
        order = np.argsort(-scores)
        true_digit = int(keys[-1])
        true_rank = int(np.where(order == true_digit)[0][0] + 1)
        best_digit = int(order[0])
        row = {name: value for name, value in zip(group_cols, keys)}
        row.update(
            {
                "pred_digit": best_digit,
                "true_rank": true_rank,
                "top1": int(true_rank <= 1),
                "top2": int(true_rank <= 2),
                "top3": int(true_rank <= 3),
                "margin": float(scores[order[0]] - scores[order[1]]),
                "true_score": float(scores[true_digit]),
            }
        )
        for digit in range(10):
            row[f"score_{digit}"] = float(scores[digit])
        rows.append(row)

    paired = pd.DataFrame(rows).sort_values(
        ["stage", "replicate", "upstream_digit"]
    ).reset_index(drop=True)
    assert len(paired) == 60
    assert paired.groupby("stage").size().eq(30).all()
    assert paired.groupby("stage")["prefix_correct"].sum().eq(3).all()
    return paired


def summarise_prefix_effects(paired: pd.DataFrame, direction_scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics_rows = []
    for view_name, df in [("direction-paired", paired), ("direction-specific", direction_scores)]:
        for (stage, prefix_correct), group in df.groupby(["stage", "prefix_correct"], sort=True):
            metrics_rows.append(
                {
                    "view": view_name,
                    "stage": int(stage),
                    "probe_wheel": int(group["probe_wheel"].iloc[0]),
                    "prefix_correct": int(prefix_correct),
                    "n": int(len(group)),
                    "top1": float(group["top1"].mean()),
                    "top2": float(group["top2"].mean()),
                    "top3": float(group["top3"].mean()),
                    "mean_true_rank": float(group["true_rank"].mean()),
                    "median_true_rank": float(group["true_rank"].median()),
                    "mean_margin": float(group["margin"].mean()),
                }
            )
    metrics = pd.DataFrame(metrics_rows)

    repeat_rows = []
    for (stage, replicate), group in paired.groupby(["stage", "replicate"], sort=True):
        correct = group[group["prefix_correct"] == 1]
        wrong = group[group["prefix_correct"] == 0]
        if len(correct) != 1 or len(wrong) != 9:
            raise AssertionError("Each repeat must contain one correct and nine wrong upstream candidates.")
        correct_rank = float(correct["true_rank"].iloc[0])
        wrong_mean = float(wrong["true_rank"].mean())
        wrong_median = float(wrong["true_rank"].median())
        repeat_rows.append(
            {
                "stage": int(stage),
                "replicate": int(replicate),
                "probe_wheel": int(group["probe_wheel"].iloc[0]),
                "correct_upstream_digit": int(correct["upstream_digit"].iloc[0]),
                "correct_true_rank": correct_rank,
                "wrong_mean_true_rank": wrong_mean,
                "wrong_median_true_rank": wrong_median,
                "wrong_minus_correct_mean_rank": wrong_mean - correct_rank,
                "correct_better_than_wrong_mean": int(correct_rank < wrong_mean),
                "correct_top1": int(correct["top1"].iloc[0]),
                "wrong_top1_rate": float(wrong["top1"].mean()),
            }
        )
    repeat_effects = pd.DataFrame(repeat_rows)

    candidate_rows = []
    for (stage, upstream_digit), group in paired.groupby(["stage", "upstream_digit"], sort=True):
        candidate_rows.append(
            {
                "stage": int(stage),
                "probe_wheel": int(group["probe_wheel"].iloc[0]),
                "upstream_digit": int(upstream_digit),
                "prefix_correct": int(group["prefix_correct"].iloc[0]),
                "n_repeats": int(len(group)),
                "mean_true_rank": float(group["true_rank"].mean()),
                "sd_true_rank": float(group["true_rank"].std(ddof=1)),
                "top1": float(group["top1"].mean()),
                "top2": float(group["top2"].mean()),
                "top3": float(group["top3"].mean()),
            }
        )
    candidate_summary = pd.DataFrame(candidate_rows)

    direction_rows = []
    for (stage, direction, prefix_correct), group in direction_scores.groupby(
        ["stage", "direction", "prefix_correct"], sort=True
    ):
        direction_rows.append(
            {
                "stage": int(stage),
                "probe_wheel": int(group["probe_wheel"].iloc[0]),
                "direction": direction,
                "prefix_correct": int(prefix_correct),
                "n": int(len(group)),
                "top1": float(group["top1"].mean()),
                "top2": float(group["top2"].mean()),
                "top3": float(group["top3"].mean()),
                "mean_true_rank": float(group["true_rank"].mean()),
            }
        )
    direction_summary = pd.DataFrame(direction_rows)

    return metrics, repeat_effects, candidate_summary, direction_summary


def _style_axes(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.13, zorder=0)


def save_figures(
    paired: pd.DataFrame,
    metrics: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    result_dir: Path,
):
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "font.size": 10,
            "axes.labelsize": 10,
            "legend.fontsize": 9,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
        }
    )

    stage_labels = {1: "W2 after W1", 2: "W4 after W1+W2"}
    paired_metrics = metrics[metrics["view"] == "direction-paired"].copy()

    rows = []
    for stage in [1, 2]:
        correct = paired_metrics[
            (paired_metrics["stage"] == stage)
            & (paired_metrics["prefix_correct"] == 1)
        ].iloc[0]
        wrong = paired_metrics[
            (paired_metrics["stage"] == stage)
            & (paired_metrics["prefix_correct"] == 0)
        ].iloc[0]

        rows.append(
            {
                "label": stage_labels[stage],
                "correct_top1": 100.0 * float(correct["top1"]),
                "wrong_top1": 100.0 * float(wrong["top1"]),
                "correct_rank": float(correct["mean_true_rank"]),
                "wrong_rank": float(wrong["mean_true_rank"]),
            }
        )

    x = np.arange(len(rows))
    width = 0.28

    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    correct_values = [row["correct_top1"] for row in rows]
    wrong_values = [row["wrong_top1"] for row in rows]

    correct_bars = ax.bar(
        x - width / 2,
        correct_values,
        width,
        color=DARK_BLUE,
        edgecolor="none",
        label="Correct prefix",
        zorder=3,
    )
    wrong_bars = ax.bar(
        x + width / 2,
        wrong_values,
        width,
        color=LIGHT_BLUE,
        edgecolor="none",
        label="Wrong prefix",
        zorder=3,
    )

    for bars in (correct_bars, wrong_bars):
        for bar in bars:
            ax.annotate(
                f"{bar.get_height():.1f}%",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
                color=DARK_GREY,
            )

    ax.set_ylabel("Top-1 accuracy")
    ax.set_xticks(x)
    ax.set_xticklabels([row["label"] for row in rows])
    ax.set_ylim(0, 110)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda y, pos: f"{y:.0f}%")
    )
    _style_axes(ax)
    ax.legend(
        frameon=False,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
    )
    fig.tight_layout()
    fig.savefig(
        result_dir / "RQ20_Fig1_Prefix_Top1.png",
        bbox_inches="tight",
    )
    fig.savefig(
        result_dir / "RQ20_Fig1_Prefix_Top1.pdf",
        bbox_inches="tight",
    )
    plt.show()

    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    correct_values = [row["correct_rank"] for row in rows]
    wrong_values = [row["wrong_rank"] for row in rows]

    correct_bars = ax.bar(
        x - width / 2,
        correct_values,
        width,
        color=DARK_BLUE,
        edgecolor="none",
        label="Correct prefix",
        zorder=3,
    )
    wrong_bars = ax.bar(
        x + width / 2,
        wrong_values,
        width,
        color=LIGHT_BLUE,
        edgecolor="none",
        label="Wrong prefix",
        zorder=3,
    )

    for bars in (correct_bars, wrong_bars):
        for bar in bars:
            ax.annotate(
                f"{bar.get_height():.2f}",
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
                color=DARK_GREY,
            )

    ax.set_ylabel("Mean true rank (lower is better)")
    ax.set_xticks(x)
    ax.set_xticklabels([row["label"] for row in rows])
    ax.set_ylim(
        0,
        max(max(correct_values), max(wrong_values)) + 0.6,
    )
    _style_axes(ax)
    ax.legend(
        frameon=False,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
    )
    fig.tight_layout()
    fig.savefig(
        result_dir / "RQ20_Fig2_Prefix_TrueRank.png",
        bbox_inches="tight",
    )
    fig.savefig(
        result_dir / "RQ20_Fig2_Prefix_TrueRank.pdf",
        bbox_inches="tight",
    )
    plt.show()


def write_report(
    metrics: pd.DataFrame,
    repeat_effects: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    direction_summary: pd.DataFrame,
    result_dir: Path,
):
    paired = metrics[metrics["view"] == "direction-paired"].copy()

    def row(stage: int, correct: int):
        return paired[(paired["stage"] == stage) & (paired["prefix_correct"] == correct)].iloc[0]

    s1c, s1w = row(1, 1), row(1, 0)
    s2c, s2w = row(2, 1), row(2, 0)
    repeat_counts = repeat_effects.groupby("stage")["correct_better_than_wrong_mean"].sum().to_dict()

    report = f"""# RQ20 — Sequential Upstream-Prefix Dependency

## Research question

Does downstream-wheel True-Gate ranking depend on whether the already selected upstream prefix is physically correct?

## Controlled dataset

Binding B03 (password 0528) is reused as a mechanistic perturbation experiment rather than as Binding-model training data.

- Stage 1: sweep W1 through all ten candidate digits and probe W2. The correct W1 digit is 0.
- Stage 2: hold W1 correct at 0, sweep W2 through all ten candidate digits and probe W4. The correct W2 digit is 5.
- Each upstream candidate is repeated in R1-R3 and recorded independently in CW and CCW after full release/reseat.
- MAIN v8 was trained only on the True-Gate B01-B07 development set and was not trained on Binding B03 / password 0528.
- Because Binding B03 contains only one A recording per direction, this RQ uses a direction-paired diagnostic average (CW + CCW), not the standard deployed A/B fusion protocol.

## Direction-paired results

| Stage | Prefix | n contexts | Top-1 | Top-2 | Top-3 | Mean true rank | Median true rank |
|---|---|---:|---:|---:|---:|---:|---:|
| W2 after W1 | Correct | {int(s1c['n'])} | {100*s1c['top1']:.1f}% | {100*s1c['top2']:.1f}% | {100*s1c['top3']:.1f}% | {s1c['mean_true_rank']:.2f} | {s1c['median_true_rank']:.1f} |
| W2 after W1 | Wrong | {int(s1w['n'])} | {100*s1w['top1']:.1f}% | {100*s1w['top2']:.1f}% | {100*s1w['top3']:.1f}% | {s1w['mean_true_rank']:.2f} | {s1w['median_true_rank']:.1f} |
| W4 after W1+W2 | Correct | {int(s2c['n'])} | {100*s2c['top1']:.1f}% | {100*s2c['top2']:.1f}% | {100*s2c['top3']:.1f}% | {s2c['mean_true_rank']:.2f} | {s2c['median_true_rank']:.1f} |
| W4 after W1+W2 | Wrong | {int(s2w['n'])} | {100*s2w['top1']:.1f}% | {100*s2w['top2']:.1f}% | {100*s2w['top3']:.1f}% | {s2w['mean_true_rank']:.2f} | {s2w['median_true_rank']:.1f} |

## Repeat consistency

For each of the three repeats, the correct-prefix true rank is compared with the mean true rank across the nine deliberately wrong upstream candidates.

- Stage 1: correct prefix performed better than the wrong-prefix mean in {int(repeat_counts.get(1, 0))}/3 repeats.
- Stage 2: correct prefix performed better than the wrong-prefix mean in {int(repeat_counts.get(2, 0))}/3 repeats.

## Interpretation

This experiment tests a system-state dependency, not a new model family. A lower true rank under the correct prefix indicates that the acoustic state presented to the downstream wheel is conditional on the upstream mechanical configuration. The two stages must be interpreted separately because W2 and W4 occupy different positions in the lock's sequential binding process.

## Limitations

Only one physical password (0528) and three repeated candidate sweeps are available. The correct-prefix group therefore contains only three direction-paired contexts per stage, while the wrong-prefix group contains 27. The experiment is strong as a controlled within-lock mechanistic perturbation, but it is not a population-level estimate of prefix effects across passwords. No causal p-value is reported because upstream digit identity was swept deterministically rather than randomly assigned.

## Relationship to RQ21

RQ20 asks whether prefix correctness changes downstream True-Gate ranking behaviour. RQ21 uses the same physical state concept for a different task: whether the scan itself can detect a binding-like/non-binding state strongly enough to act as a safety veto.
"""
    Path(result_dir, "RQ20_Report.md").write_text(report, encoding="utf-8")

    conclusion = {
        "research_question": "Does downstream-wheel True-Gate ranking depend on upstream prefix correctness?",
        "dataset": BINDING_SESSION,
        "password": EXPECTED_PASSWORD,
        "model": "MAIN v8 frozen runtime",
        "analysis_role": "controlled mechanistic perturbation; not model training",
        "standard_deployment_fusion_used": False,
        "diagnostic_fusion": "mean of independently reseated CW and CCW scores; one A recording per direction",
        "stage1": {
            "probe_wheel": 2,
            "correct_prefix_digit": 0,
            "correct_top1": float(s1c["top1"]),
            "wrong_top1": float(s1w["top1"]),
            "correct_mean_true_rank": float(s1c["mean_true_rank"]),
            "wrong_mean_true_rank": float(s1w["mean_true_rank"]),
            "repeat_consistency": int(repeat_counts.get(1, 0)),
        },
        "stage2": {
            "probe_wheel": 4,
            "correct_prefix_digit": 5,
            "correct_top1": float(s2c["top1"]),
            "wrong_top1": float(s2w["top1"]),
            "correct_mean_true_rank": float(s2c["mean_true_rank"]),
            "wrong_mean_true_rank": float(s2w["mean_true_rank"]),
            "repeat_consistency": int(repeat_counts.get(2, 0)),
        },
        "limitations": "One password and three repeats; correct-prefix n=3 direction-paired contexts per stage. No causal p-value is reported.",
        "next_step": "RQ21 tests whether the altered state can be detected directly as a Binding safety-veto signal.",
    }
    Path(result_dir, "RQ20_conclusion.json").write_text(
        json.dumps(conclusion, indent=2), encoding="utf-8"
    )


def save_tables(
    manifest: pd.DataFrame,
    direction_scores: pd.DataFrame,
    paired: pd.DataFrame,
    metrics: pd.DataFrame,
    repeat_effects: pd.DataFrame,
    candidate_summary: pd.DataFrame,
    direction_summary: pd.DataFrame,
    result_dir: Path,
):
    result_dir = Path(result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(result_dir / "RQ20_Control_Manifest.csv", index=False)
    direction_scores.to_csv(result_dir / "RQ20_MAINv8_Direction_Scores.csv", index=False)
    paired.to_csv(result_dir / "RQ20_MAINv8_Direction_Paired.csv", index=False)
    metrics.to_csv(result_dir / "RQ20_Prefix_Metrics.csv", index=False)
    repeat_effects.to_csv(result_dir / "RQ20_Repeat_Effects.csv", index=False)
    candidate_summary.to_csv(result_dir / "RQ20_Candidate_Summary.csv", index=False)
    direction_summary.to_csv(result_dir / "RQ20_Direction_Summary.csv", index=False)
