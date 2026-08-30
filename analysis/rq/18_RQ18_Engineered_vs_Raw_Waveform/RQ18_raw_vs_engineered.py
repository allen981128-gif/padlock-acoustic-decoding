from pathlib import Path, PurePosixPath
import io
import json
import random
import shutil
import time
import zipfile

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import soundfile as sf

from scipy.stats import wilcoxon
from sklearn.metrics import f1_score

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


BASE_SEED = 20260820
RAW_SEEDS = [20260820, 20260821, 20260822]
TARGET_SAMPLES = 12288
SAMPLE_RATE = 44100

BATCHES = [
    "B01_2085",
    "B02_4369",
    "B03_5720",
    "B04_6893",
    "B05_7246",
    "B06_8451",
    "B07_9638",
]
WHEELS = (1, 2, 4)
DIRECTIONS = ("CCW", "CW")

RAW_CONFIG = {
    "target_samples": TARGET_SAMPLES,
    "sample_rate": SAMPLE_RATE,
    "channels": [32, 64, 128, 128],
    "kernels": [15, 9, 7, 5],
    "strides": [2, 2, 2, 2],
    "temporal_bins": 8,
    "dropout": 0.30,
    "learning_rate": 5e-4,
    "weight_decay": 1e-4,
    "batch_size": 64,
    "max_epochs": 35,
    "patience": 6,
}


def set_seed(seed):
    seed = int(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def locate_results_root(mydrive):
    project_root = mydrive / "Padlock_Reproduction_v1"
    candidates = [
        project_root / "results",
        project_root / "Padlock_Reproduction_v1" / "results",
    ]
    for root in candidates:
        manifest = root / "07_RQ7_Absolute_vs_Relative" / "RQ7_candidate_manifest.csv"
        if manifest.exists():
            return root
    raise FileNotFoundError("Could not locate the active Padlock_Reproduction_v1/results folder.")


def _has_full_batch_archives(root, min_zip_bytes=50_000_000):
    """Return True only for the raw root that contains the real audio batch ZIPs."""
    if not root.exists():
        return False
    for batch in BATCHES:
        path = root / f"{batch}.zip"
        if not path.exists() or path.stat().st_size < int(min_zip_bytes):
            return False
    return True


def locate_raw_root(mydrive):
    """Locate the Dataset v1 raw ZIP root.

    The project contains more than one directory named ``raw`` and some small
    archival ZIPs with similar names.  Previous RQs avoided mounted-Drive
    small-file I/O by using the full 200+ MB batch archives.  We therefore
    identify the source by requiring all seven real batch ZIPs to be present
    and larger than 50 MB.
    """
    project_root = mydrive / "Padlock_Reproduction_v1"
    candidates = [
        mydrive / "dataset" / "raw",
        mydrive / "dataset" / "dataset" / "raw",
        project_root / "dataset" / "raw",
        project_root / "Padlock_Reproduction_v1" / "dataset" / "raw",
    ]

    for root in candidates:
        if _has_full_batch_archives(root):
            return root

    # Last-resort shallow search.  This is metadata/path discovery only; raw
    # WAV files are never read through the mounted Drive tree.
    for pattern in ("*/raw", "*/*/raw", "*/*/*/raw"):
        for root in mydrive.glob(pattern):
            if _has_full_batch_archives(root):
                return root

    raise FileNotFoundError(
        "Could not locate the full Dataset v1 raw batch archives. Expected "
        "B01_2085.zip ... B07_9638.zip (each >50 MB) under one raw directory."
    )


def raw_archive_summary(raw_root):
    rows = []
    for batch in BATCHES:
        path = raw_root / f"{batch}.zip"
        rows.append({
            "batch": batch,
            "zip_exists": path.exists(),
            "zip_mb": (path.stat().st_size / 1e6) if path.exists() else np.nan,
            "path": str(path),
        })
    return pd.DataFrame(rows)


def load_manifest(path):
    manifest = pd.read_csv(path)
    if "row_id" not in manifest.columns:
        manifest["row_id"] = np.arange(len(manifest), dtype=int)

    manifest = manifest.sort_values("row_id").reset_index(drop=True)
    assert np.array_equal(manifest["row_id"].to_numpy(dtype=int), np.arange(len(manifest)))
    assert len(manifest) == 8400
    assert manifest["decision_uid"].nunique() == 840
    assert manifest["profile_id"].nunique() == 210
    assert manifest.groupby("decision_uid").size().eq(10).all()
    assert manifest.groupby("decision_uid")["y"].sum().eq(1).all()

    required = {
        "batch", "password", "profile_id", "wheel", "direction", "repeat_id",
        "decision_uid", "run_id", "to_digit", "true_digit", "y", "row_id",
    }
    missing = sorted(required - set(manifest.columns))
    if missing:
        raise ValueError(f"Manifest is missing columns: {missing}")
    return manifest


def event_bounds(events):
    start_rows = events[events["event"].astype(str) == "SCAN_START"]
    end_rows = events[events["event"].astype(str) == "SCAN_END"]
    if len(start_rows) != 1 or len(end_rows) != 1:
        raise ValueError("Expected exactly one SCAN_START and one SCAN_END")
    start = int(start_rows["aligned_sample_index"].iloc[0])
    end = int(end_rows["aligned_sample_index"].iloc[0])
    if not (0 <= start < end):
        raise ValueError(f"Invalid event bounds: {start}, {end}")
    return start, end


def build_zip_asset_map(zf):
    assets = {}
    for name in zf.namelist():
        path = PurePosixPath(name)
        run_id = next((part for part in path.parts if part.startswith("run_")), None)
        if run_id is None:
            continue
        if path.name in {"audio_dual.wav", "events.csv"}:
            assets.setdefault(run_id, {})[path.name] = name
    return assets


def read_run_folder(run_dir):
    wav_path = run_dir / "audio_dual.wav"
    events_path = run_dir / "events.csv"
    if not wav_path.exists() or not events_path.exists():
        raise FileNotFoundError(run_dir)
    audio, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    events = pd.read_csv(events_path)
    return audio, int(sr), events


def read_run_zip(zf, assets, run_id):
    entry = assets.get(str(run_id), {})
    if "audio_dual.wav" not in entry or "events.csv" not in entry:
        raise KeyError(f"Missing raw assets for {run_id}")
    with zf.open(entry["audio_dual.wav"]) as f:
        audio_bytes = f.read()
    with zf.open(entry["events.csv"]) as f:
        events_bytes = f.read()
    audio, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=True)
    events = pd.read_csv(io.BytesIO(events_bytes))
    return audio, int(sr), events


def write_segment(raw_mm, row_id, audio, sr, events):
    if sr != SAMPLE_RATE:
        raise ValueError(f"Unexpected sample rate {sr}")
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError(f"Expected dual-channel audio, got {audio.shape}")

    start, end = event_bounds(events)
    if end > len(audio):
        raise ValueError(f"SCAN_END {end} exceeds audio length {len(audio)}")

    segment = audio[start:end]
    n = len(segment)
    if n > TARGET_SAMPLES:
        raise ValueError(
            f"Movement length {n} exceeds TARGET_SAMPLES={TARGET_SAMPLES}. "
            "Increase the fixed window rather than cropping."
        )

    raw_mm[row_id, :, :] = 0.0
    raw_mm[row_id, :, :n] = segment.T
    return n, start, end


def prepare_raw_cache(manifest, raw_root, result_dir, work_dir):
    cache_dir = result_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    drive_wave = cache_dir / f"RQ18_raw_segments_{TARGET_SAMPLES}_f32.npy"
    drive_lengths = cache_dir / f"RQ18_raw_lengths_{TARGET_SAMPLES}.npy"
    drive_qc = cache_dir / "RQ18_raw_cache_qc.csv"

    local_wave = work_dir / drive_wave.name
    local_lengths = work_dir / drive_lengths.name

    if drive_wave.exists() and drive_lengths.exists():
        print("Loading persistent raw cache")
        shutil.copy2(drive_wave, local_wave)
        shutil.copy2(drive_lengths, local_lengths)
    else:
        raw_mm = np.lib.format.open_memmap(
            local_wave,
            mode="w+",
            dtype=np.float32,
            shape=(len(manifest), 2, TARGET_SAMPLES),
        )
        lengths = np.zeros(len(manifest), dtype=np.int32)
        qc_rows = []

        for batch in BATCHES:
            batch_frame = manifest[manifest["batch"] == batch].copy()
            assert len(batch_frame) == 1200

            # Match the established workflow used for the earlier RQs:
            # one large batch ZIP is copied from Drive to /content once,
            # extracted locally, all 1,200 runs are read from local disk, and
            # the local source is deleted before moving to the next batch.
            zip_path = raw_root / f"{batch}.zip"
            if not zip_path.exists():
                raise FileNotFoundError(f"Missing full raw archive: {zip_path}")
            if zip_path.stat().st_size < 50_000_000:
                raise RuntimeError(
                    f"Refusing suspiciously small archive {zip_path} "
                    f"({zip_path.stat().st_size / 1e6:.1f} MB)."
                )

            local_zip = work_dir / f"{batch}.zip"
            local_extract = work_dir / f"{batch}_raw"
            if local_extract.exists():
                shutil.rmtree(local_extract)
            local_extract.mkdir(parents=True, exist_ok=True)

            print(
                f"[{batch}] copy raw ZIP to local Colab "
                f"({zip_path.stat().st_size / 1e6:.1f} MB)"
            )
            shutil.copy2(zip_path, local_zip)

            print(f"[{batch}] extract ZIP locally")
            with zipfile.ZipFile(local_zip, "r") as zf:
                zf.extractall(local_extract)
            local_zip.unlink(missing_ok=True)

            run_dirs = {}
            for run_dir in local_extract.rglob("run_*"):
                if (
                    run_dir.is_dir()
                    and (run_dir / "audio_dual.wav").exists()
                    and (run_dir / "events.csv").exists()
                ):
                    run_dirs[run_dir.name] = run_dir

            expected_ids = set(batch_frame["run_id"].astype(str))
            missing_ids = sorted(expected_ids - set(run_dirs))
            if missing_ids:
                raise RuntimeError(
                    f"{batch}: {len(missing_ids)} run folders missing after local extraction; "
                    f"examples: {missing_ids[:10]}"
                )

            print(f"[{batch}] cache 1,200 runs from local disk")
            for j, row in enumerate(batch_frame.itertuples(), start=1):
                audio, sr, events = read_run_folder(run_dirs[str(row.run_id)])
                n, start, end = write_segment(raw_mm, int(row.row_id), audio, sr, events)
                lengths[int(row.row_id)] = n
                qc_rows.append({
                    "batch": batch,
                    "run_id": row.run_id,
                    "row_id": int(row.row_id),
                    "samples": n,
                    "scan_start": start,
                    "scan_end": end,
                    "source": "local_zip_extract",
                })
                if j % 200 == 0 or j == len(batch_frame):
                    print(f"    {j:4d}/1200")

            raw_mm.flush()
            shutil.rmtree(local_extract, ignore_errors=True)
            print(f"[{batch}] complete")

        if np.any(lengths <= 0):
            missing_rows = np.flatnonzero(lengths <= 0)[:20].tolist()
            raise RuntimeError(f"Raw cache has missing rows: {missing_rows}")

        np.save(local_lengths, lengths)
        pd.DataFrame(qc_rows).sort_values("row_id").to_csv(drive_qc, index=False)
        print("Copying persistent waveform cache to Drive")
        shutil.copy2(local_wave, drive_wave)
        shutil.copy2(local_lengths, drive_lengths)

    raw_waveforms = np.load(local_wave, mmap_mode="r")
    raw_lengths = np.load(local_lengths)
    assert raw_waveforms.shape == (8400, 2, TARGET_SAMPLES)
    assert raw_lengths.shape == (8400,)
    assert raw_lengths.min() > 0
    assert raw_lengths.max() <= TARGET_SAMPLES

    print("Raw cache shape:", raw_waveforms.shape)
    print(
        "Movement samples: min / median / max =",
        int(raw_lengths.min()),
        float(np.median(raw_lengths)),
        int(raw_lengths.max()),
    )
    return raw_waveforms, raw_lengths


class RawWaveformDataset(Dataset):
    def __init__(self, raw_waveforms, manifest, indices, channel_mean, channel_std):
        self.raw_waveforms = raw_waveforms
        self.manifest = manifest
        self.indices = np.asarray(indices, dtype=int)
        self.mean = np.asarray(channel_mean, dtype=np.float32).reshape(2, 1)
        self.std = np.asarray(channel_std, dtype=np.float32).reshape(2, 1)

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, item):
        row_id = int(self.indices[item])
        x = np.array(self.raw_waveforms[row_id], dtype=np.float32, copy=True)
        x = (x - self.mean) / self.std
        y = np.float32(self.manifest.loc[row_id, "y"])
        return torch.from_numpy(x), torch.tensor(y, dtype=torch.float32)


class RawWaveformCNN(nn.Module):
    def __init__(self):
        super().__init__()
        blocks = []
        in_channels = 2
        for out_channels, kernel, stride in zip(
            RAW_CONFIG["channels"],
            RAW_CONFIG["kernels"],
            RAW_CONFIG["strides"],
        ):
            blocks.extend([
                nn.Conv1d(
                    in_channels,
                    out_channels,
                    kernel_size=kernel,
                    stride=stride,
                    padding=kernel // 2,
                    bias=False,
                ),
                nn.BatchNorm1d(out_channels),
                nn.GELU(),
            ])
            in_channels = out_channels

        self.encoder = nn.Sequential(*blocks)
        self.pool = nn.AdaptiveAvgPool1d(RAW_CONFIG["temporal_bins"])
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(RAW_CONFIG["dropout"]),
            nn.Linear(in_channels * RAW_CONFIG["temporal_bins"], 128),
            nn.GELU(),
            nn.Dropout(RAW_CONFIG["dropout"]),
            nn.Linear(128, 1),
        )

    def forward(self, x):
        x = self.encoder(x)
        x = self.pool(x)
        return self.head(x).squeeze(1)


def within_decision_z(frame, score_col="score"):
    frame = frame.reset_index(drop=True).copy()
    frame["score_z"] = np.nan
    for _, inds in frame.groupby("decision_uid").groups.items():
        inds = np.array(list(inds), dtype=int)
        values = frame.loc[inds, score_col].to_numpy(dtype=float)
        sd = float(np.std(values))
        scale = sd if sd > 1e-12 else 1.0
        frame.loc[inds, "score_z"] = (values - np.mean(values)) / scale
    return frame


def fuse_ab_and_rank(candidate_frame, label):
    candidate_frame = within_decision_z(candidate_frame, "score")
    fused = (
        candidate_frame.groupby(
            ["batch", "password", "profile_id", "wheel", "direction", "to_digit", "true_digit"],
            as_index=False,
        )
        .agg(
            fused_score=("score_z", "mean"),
            n_repeats=("repeat_id", "nunique"),
            y=("y", "first"),
        )
    )
    assert fused["n_repeats"].eq(2).all()

    rows = []
    for (batch, password, profile_id, wheel, direction), group in fused.groupby(
        ["batch", "password", "profile_id", "wheel", "direction"],
        sort=False,
    ):
        assert len(group) == 10
        ranked = group.sort_values(
            ["fused_score", "to_digit"],
            ascending=[False, True],
            kind="mergesort",
        ).reset_index(drop=True)
        truth = int(ranked["true_digit"].iloc[0])
        digits = ranked["to_digit"].astype(int).tolist()
        true_rank = int(digits.index(truth) + 1)
        rows.append({
            "condition": label,
            "heldout_batch": batch,
            "password": str(password),
            "profile_id": profile_id,
            "wheel": int(wheel),
            "direction": direction,
            "true_digit": truth,
            "pred_digit": int(digits[0]),
            "true_rank": true_rank,
            "top1": int(true_rank <= 1),
            "top2": int(true_rank <= 2),
            "top3": int(true_rank <= 3),
            "reciprocal_rank": 1.0 / true_rank,
        })
    return fused, pd.DataFrame(rows)


def metric_row(frame):
    return {
        "n_decisions": len(frame),
        "top1": float(frame["top1"].mean()),
        "top2": float(frame["top2"].mean()),
        "top3": float(frame["top3"].mean()),
        "mean_true_rank": float(frame["true_rank"].mean()),
        "mrr": float(frame["reciprocal_rank"].mean()),
        "macro_f1": float(
            f1_score(
                frame["true_digit"],
                frame["pred_digit"],
                labels=list(range(10)),
                average="macro",
                zero_division=0,
            )
        ),
        "weighted_f1": float(
            f1_score(
                frame["true_digit"],
                frame["pred_digit"],
                labels=list(range(10)),
                average="weighted",
                zero_division=0,
            )
        ),
    }


def val_fused_top1(meta_frame, scores):
    temp = meta_frame.reset_index(drop=True).copy()
    temp["score"] = np.asarray(scores, dtype=float)
    _, decisions = fuse_ab_and_rank(temp, "validation")
    return float(decisions["top1"].mean())


def deterministic_inner_val_batch(heldout_batch):
    outer_index = BATCHES.index(heldout_batch)
    candidate = BATCHES[(outer_index + 1) % len(BATCHES)]
    if candidate == heldout_batch:
        candidate = BATCHES[(outer_index + 2) % len(BATCHES)]
    return candidate


def compute_channel_stats(raw_waveforms, indices, chunk_size=128):
    indices = np.asarray(indices, dtype=int)
    total_sum = np.zeros(2, dtype=np.float64)
    total_sq = np.zeros(2, dtype=np.float64)
    count = 0
    for start in range(0, len(indices), chunk_size):
        chunk_idx = indices[start:start + chunk_size]
        x = np.asarray(raw_waveforms[chunk_idx], dtype=np.float32)
        total_sum += x.sum(axis=(0, 2), dtype=np.float64)
        total_sq += np.square(x, dtype=np.float32).sum(axis=(0, 2), dtype=np.float64)
        count += x.shape[0] * x.shape[2]
    mean = total_sum / count
    var = np.maximum(total_sq / count - np.square(mean), 1e-12)
    return mean.astype(np.float32), np.sqrt(var).astype(np.float32)


def make_loader(raw_waveforms, manifest, indices, mean, std, shuffle, seed):
    dataset = RawWaveformDataset(raw_waveforms, manifest, indices, mean, std)
    generator = torch.Generator()
    generator.manual_seed(int(seed))
    return DataLoader(
        dataset,
        batch_size=RAW_CONFIG["batch_size"],
        shuffle=shuffle,
        generator=generator,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
        drop_last=False,
    )


def positive_weight(manifest, indices):
    y = manifest.loc[indices, "y"].to_numpy(dtype=int)
    n_pos = float(np.sum(y == 1))
    n_neg = float(np.sum(y == 0))
    return n_neg / max(n_pos, 1.0)


def predict_scores(model, raw_waveforms, manifest, indices, mean, std, device):
    loader = make_loader(raw_waveforms, manifest, indices, mean, std, False, BASE_SEED)
    model.eval()
    out = []
    with torch.no_grad():
        for xb, _ in loader:
            logits = model(xb.to(device, non_blocking=True))
            out.append(logits.detach().cpu().numpy())
    return np.concatenate(out).reshape(-1)


def train_fixed_epochs(raw_waveforms, manifest, train_idx, mean, std, epochs, seed, device):
    set_seed(seed)
    model = RawWaveformCNN().to(device)
    loader = make_loader(raw_waveforms, manifest, train_idx, mean, std, True, seed)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=RAW_CONFIG["learning_rate"],
        weight_decay=RAW_CONFIG["weight_decay"],
    )
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(
            [positive_weight(manifest, train_idx)],
            dtype=torch.float32,
            device=device,
        )
    )
    losses = []
    for _ in range(int(epochs)):
        model.train()
        running = 0.0
        seen = 0
        for xb, yb in loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            running += float(loss.item()) * len(yb)
            seen += len(yb)
        losses.append(running / max(seen, 1))
    return model, losses


def select_epoch(raw_waveforms, manifest, inner_train_idx, val_idx, seed, device):
    mean, std = compute_channel_stats(raw_waveforms, inner_train_idx)
    set_seed(seed)
    model = RawWaveformCNN().to(device)
    loader = make_loader(raw_waveforms, manifest, inner_train_idx, mean, std, True, seed)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=RAW_CONFIG["learning_rate"],
        weight_decay=RAW_CONFIG["weight_decay"],
    )
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor(
            [positive_weight(manifest, inner_train_idx)],
            dtype=torch.float32,
            device=device,
        )
    )

    best_top1 = -np.inf
    best_epoch = 1
    stale = 0
    history = []
    val_meta = manifest.loc[val_idx].reset_index(drop=True).copy()

    for epoch in range(1, RAW_CONFIG["max_epochs"] + 1):
        model.train()
        running = 0.0
        seen = 0
        for xb, yb in loader:
            xb = xb.to(device, non_blocking=True)
            yb = yb.to(device, non_blocking=True)
            optimizer.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            running += float(loss.item()) * len(yb)
            seen += len(yb)

        val_scores = predict_scores(model, raw_waveforms, manifest, val_idx, mean, std, device)
        val_top1 = val_fused_top1(val_meta, val_scores)
        train_loss = running / max(seen, 1)
        history.append({"epoch": epoch, "train_loss": train_loss, "val_top1": val_top1})

        if val_top1 > best_top1 + 1e-12:
            best_top1 = val_top1
            best_epoch = epoch
            stale = 0
        else:
            stale += 1
        if stale >= RAW_CONFIG["patience"]:
            break

    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return int(best_epoch), pd.DataFrame(history)


def checkpoint_path(checkpoint_dir, seed, heldout, wheel, direction):
    return checkpoint_dir / f"rawcnn_seed{seed}_{heldout}_W{wheel}_{direction}.npz"


def run_lopo(raw_waveforms, manifest, result_dir, seeds=None, device=None):
    seeds = RAW_SEEDS if seeds is None else list(seeds)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu") if device is None else device
    checkpoint_dir = result_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    for seed in seeds:
        for heldout in BATCHES:
            inner_val_batch = deterministic_inner_val_batch(heldout)
            for wheel in WHEELS:
                for direction in DIRECTIONS:
                    ckpt = checkpoint_path(checkpoint_dir, seed, heldout, wheel, direction)
                    if ckpt.exists():
                        print("skip", ckpt.name)
                        continue

                    domain = (
                        (manifest["wheel"].astype(int) == wheel)
                        & (manifest["direction"].astype(str) == direction)
                    )
                    outer_train = domain & (manifest["batch"] != heldout)
                    outer_test = domain & (manifest["batch"] == heldout)
                    inner_train = outer_train & (manifest["batch"] != inner_val_batch)
                    val = outer_train & (manifest["batch"] == inner_val_batch)

                    outer_train_idx = manifest.loc[outer_train, "row_id"].to_numpy(dtype=int)
                    outer_test_idx = manifest.loc[outer_test, "row_id"].to_numpy(dtype=int)
                    inner_train_idx = manifest.loc[inner_train, "row_id"].to_numpy(dtype=int)
                    val_idx = manifest.loc[val, "row_id"].to_numpy(dtype=int)

                    assert len(outer_train_idx) == 1200
                    assert len(outer_test_idx) == 200
                    assert len(inner_train_idx) == 1000
                    assert len(val_idx) == 200

                    domain_seed = (
                        int(seed)
                        + 10000 * BATCHES.index(heldout)
                        + 100 * int(wheel)
                        + 10 * DIRECTIONS.index(direction)
                    )
                    print(
                        f"seed={seed} heldout={heldout} W{wheel} {direction} "
                        f"val={inner_val_batch}"
                    )

                    started = time.perf_counter()
                    selected_epoch, history = select_epoch(
                        raw_waveforms,
                        manifest,
                        inner_train_idx,
                        val_idx,
                        domain_seed,
                        device,
                    )
                    outer_mean, outer_std = compute_channel_stats(raw_waveforms, outer_train_idx)
                    model, final_losses = train_fixed_epochs(
                        raw_waveforms,
                        manifest,
                        outer_train_idx,
                        outer_mean,
                        outer_std,
                        selected_epoch,
                        domain_seed + 500000,
                        device,
                    )
                    scores = predict_scores(
                        model,
                        raw_waveforms,
                        manifest,
                        outer_test_idx,
                        outer_mean,
                        outer_std,
                        device,
                    )
                    fit_seconds = time.perf_counter() - started

                    np.savez_compressed(
                        ckpt,
                        row_id=outer_test_idx,
                        score=scores.astype(np.float32),
                        selected_epoch=np.array([selected_epoch], dtype=np.int32),
                        fit_seconds=np.array([fit_seconds], dtype=np.float64),
                        channel_mean=outer_mean,
                        channel_std=outer_std,
                        history_epoch=history["epoch"].to_numpy(dtype=np.int32),
                        history_train_loss=history["train_loss"].to_numpy(dtype=np.float32),
                        history_val_top1=history["val_top1"].to_numpy(dtype=np.float32),
                        final_train_loss=np.asarray(final_losses, dtype=np.float32),
                    )

                    del model
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

    print("Raw CNN LOPO checkpoints complete.")


def assemble_raw_results(manifest, result_dir, seeds=None):
    seeds = RAW_SEEDS if seeds is None else list(seeds)
    checkpoint_dir = result_dir / "checkpoints"
    candidate_parts = []
    fit_rows = []
    history_parts = []

    for seed in seeds:
        for heldout in BATCHES:
            for wheel in WHEELS:
                for direction in DIRECTIONS:
                    ckpt = checkpoint_path(checkpoint_dir, seed, heldout, wheel, direction)
                    if not ckpt.exists():
                        raise FileNotFoundError(ckpt)
                    item = np.load(ckpt, allow_pickle=False)
                    row_ids = item["row_id"].astype(int)
                    part = manifest.loc[row_ids].copy()
                    part["seed"] = seed
                    part["score"] = item["score"].astype(float)
                    candidate_parts.append(part)
                    fit_rows.append({
                        "seed": seed,
                        "heldout_batch": heldout,
                        "inner_val_batch": deterministic_inner_val_batch(heldout),
                        "wheel": wheel,
                        "direction": direction,
                        "selected_epoch": int(item["selected_epoch"][0]),
                        "fit_seconds": float(item["fit_seconds"][0]),
                        "channel_1_mean": float(item["channel_mean"][0]),
                        "channel_2_mean": float(item["channel_mean"][1]),
                        "channel_1_std": float(item["channel_std"][0]),
                        "channel_2_std": float(item["channel_std"][1]),
                    })
                    history_parts.append(pd.DataFrame({
                        "seed": seed,
                        "heldout_batch": heldout,
                        "wheel": wheel,
                        "direction": direction,
                        "epoch": item["history_epoch"].astype(int),
                        "train_loss": item["history_train_loss"].astype(float),
                        "val_top1": item["history_val_top1"].astype(float),
                    }))

    candidate_scores = pd.concat(candidate_parts, ignore_index=True)
    fit_records = pd.DataFrame(fit_rows)
    training_history = pd.concat(history_parts, ignore_index=True)

    fused_parts = []
    decision_parts = []
    for seed in seeds:
        fused, decisions = fuse_ab_and_rank(
            candidate_scores[candidate_scores["seed"] == seed].copy(),
            "Raw waveform + 1D CNN",
        )
        fused["seed"] = seed
        decisions["seed"] = seed
        fused_parts.append(fused)
        decision_parts.append(decisions)

    fused = pd.concat(fused_parts, ignore_index=True)
    decisions = pd.concat(decision_parts, ignore_index=True)
    assert len(decisions) == 420 * len(seeds)
    return candidate_scores, fused, decisions, fit_records, training_history


def build_comparison(baseline_decisions, raw_decisions, seeds=None):
    seeds = RAW_SEEDS if seeds is None else list(seeds)

    def baseline_row(family, label):
        frame = baseline_decisions[baseline_decisions["family"] == family].copy()
        row = {"condition": label, **metric_row(frame)}
        password_top1 = frame.groupby(["heldout_batch", "password"])["top1"].mean()
        row["seed_top1_sd"] = 0.0
        row["password_top1_sd"] = float(password_top1.std(ddof=1))
        row["worst_password_top1"] = float(password_top1.min())
        return row

    raw_seed_summary = pd.DataFrame([
        {"seed": seed, **metric_row(raw_decisions[raw_decisions["seed"] == seed])}
        for seed in seeds
    ])
    raw_password_seed = (
        raw_decisions.groupby(["seed", "heldout_batch", "password"], as_index=False)
        .agg(top1=("top1", "mean"))
    )
    raw_password_mean = (
        raw_password_seed.groupby(["heldout_batch", "password"], as_index=False)
        .agg(top1=("top1", "mean"))
    )

    rows = [
        baseline_row("Logistic Regression", "695-D + Logistic Regression"),
        baseline_row("CNN", "695-D + CNN"),
        {
            "condition": "Raw waveform + 1D CNN",
            "n_decisions": 420,
            "top1": float(raw_seed_summary["top1"].mean()),
            "top2": float(raw_seed_summary["top2"].mean()),
            "top3": float(raw_seed_summary["top3"].mean()),
            "mean_true_rank": float(raw_seed_summary["mean_true_rank"].mean()),
            "mrr": float(raw_seed_summary["mrr"].mean()),
            "macro_f1": float(raw_seed_summary["macro_f1"].mean()),
            "weighted_f1": float(raw_seed_summary["weighted_f1"].mean()),
            "seed_top1_sd": float(raw_seed_summary["top1"].std(ddof=1)),
            "password_top1_sd": float(raw_password_mean["top1"].std(ddof=1)),
            "worst_password_top1": float(raw_password_mean["top1"].min()),
        },
    ]
    representation_summary = pd.DataFrame(rows)

    baseline_password = (
        baseline_decisions.groupby(["family", "heldout_batch", "password"], as_index=False)
        .agg(top1=("top1", "mean"))
    )
    baseline_password["condition"] = baseline_password["family"].map({
        "Logistic Regression": "695-D + Logistic Regression",
        "CNN": "695-D + CNN",
    })
    raw_password = raw_password_mean.copy()
    raw_password["condition"] = "Raw waveform + 1D CNN"
    password_summary = pd.concat([
        baseline_password[["condition", "heldout_batch", "password", "top1"]],
        raw_password[["condition", "heldout_batch", "password", "top1"]],
    ], ignore_index=True)

    wheel_rows = []
    direction_rows = []
    for family, label in [
        ("Logistic Regression", "695-D + Logistic Regression"),
        ("CNN", "695-D + CNN"),
    ]:
        frame = baseline_decisions[baseline_decisions["family"] == family]
        for wheel in WHEELS:
            wheel_rows.append({
                "condition": label,
                "wheel": wheel,
                **metric_row(frame[frame["wheel"] == wheel]),
            })
        for direction in DIRECTIONS:
            direction_rows.append({
                "condition": label,
                "direction": direction,
                **metric_row(frame[frame["direction"] == direction]),
            })

    for wheel in WHEELS:
        seed_metrics = pd.DataFrame([
            metric_row(raw_decisions[(raw_decisions["seed"] == seed) & (raw_decisions["wheel"] == wheel)])
            for seed in seeds
        ])
        wheel_rows.append({
            "condition": "Raw waveform + 1D CNN",
            "wheel": wheel,
            **{col: float(seed_metrics[col].mean()) for col in seed_metrics.columns},
        })

    for direction in DIRECTIONS:
        seed_metrics = pd.DataFrame([
            metric_row(raw_decisions[(raw_decisions["seed"] == seed) & (raw_decisions["direction"] == direction)])
            for seed in seeds
        ])
        direction_rows.append({
            "condition": "Raw waveform + 1D CNN",
            "direction": direction,
            **{col: float(seed_metrics[col].mean()) for col in seed_metrics.columns},
        })

    wheel_summary = pd.DataFrame(wheel_rows)
    direction_summary = pd.DataFrame(direction_rows)

    password_pivot = password_summary.pivot(
        index=["heldout_batch", "password"],
        columns="condition",
        values="top1",
    ).reset_index()

    pair_rows = []
    for left, right in [
        ("Raw waveform + 1D CNN", "695-D + Logistic Regression"),
        ("Raw waveform + 1D CNN", "695-D + CNN"),
        ("695-D + CNN", "695-D + Logistic Regression"),
    ]:
        delta = password_pivot[left] - password_pivot[right]
        test = wilcoxon(
            password_pivot[left],
            password_pivot[right],
            alternative="two-sided",
            method="auto",
        )
        pair_rows.append({
            "comparison": f"{left} vs {right}",
            "mean_delta_pp": float(100 * delta.mean()),
            "median_delta_pp": float(100 * delta.median()),
            "left_better_passwords": int((delta > 0).sum()),
            "equal_passwords": int((delta == 0).sum()),
            "right_better_passwords": int((delta < 0).sum()),
            "p_two_sided": float(test.pvalue),
        })

    paired_tests = pd.DataFrame(pair_rows)
    return {
        "representation_summary": representation_summary,
        "raw_seed_summary": raw_seed_summary,
        "raw_password_seed": raw_password_seed,
        "password_summary": password_summary,
        "wheel_summary": wheel_summary,
        "direction_summary": direction_summary,
        "paired_tests": paired_tests,
    }


def save_figures(tables, result_dir):
    representation_summary = tables["representation_summary"]
    password_summary = tables["password_summary"]
    raw_password_seed = tables["raw_password_seed"]

    plot_frame = representation_summary.set_index("condition")[["top1", "top2", "top3"]] * 100
    ax = plot_frame.plot(kind="bar", figsize=(10, 5))
    ax.set_ylabel("Accuracy (%)")
    ax.set_xlabel("")
    ax.set_ylim(0, 100)
    ax.set_title("RQ18 — Representation comparison under password-level LOPO")
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    plt.savefig(result_dir / "RQ18_Fig1_Overall_TopK.png", dpi=220, bbox_inches="tight")
    plt.savefig(result_dir / "RQ18_Fig1_Overall_TopK.pdf", bbox_inches="tight")
    plt.show()

    password_plot = password_summary.pivot(
        index="password",
        columns="condition",
        values="top1",
    ) * 100
    ax = password_plot.plot(marker="o", figsize=(10, 5))
    ax.set_ylabel("Top-1 accuracy (%)")
    ax.set_xlabel("Held-out password")
    ax.set_ylim(0, 100)
    ax.set_title("RQ18 — Cross-password generalisation")
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(result_dir / "RQ18_Fig2_Password_Top1.png", dpi=220, bbox_inches="tight")
    plt.savefig(result_dir / "RQ18_Fig2_Password_Top1.pdf", bbox_inches="tight")
    plt.show()

    seed_plot = raw_password_seed.pivot(
        index="password",
        columns="seed",
        values="top1",
    ) * 100
    ax = seed_plot.plot(marker="o", figsize=(10, 5))
    ax.set_ylabel("Top-1 accuracy (%)")
    ax.set_xlabel("Held-out password")
    ax.set_ylim(0, 100)
    ax.set_title("RQ18 — Raw 1D CNN seed stability")
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(result_dir / "RQ18_Fig3_RawCNN_Seed_Stability.png", dpi=220, bbox_inches="tight")
    plt.savefig(result_dir / "RQ18_Fig3_RawCNN_Seed_Stability.pdf", bbox_inches="tight")
    plt.show()


def save_results(
    result_dir,
    raw_candidate_scores,
    raw_fused,
    raw_decisions,
    raw_fit_records,
    training_history,
    tables,
):
    result_dir.mkdir(parents=True, exist_ok=True)
    raw_candidate_scores.to_csv(result_dir / "RQ18_RawCNN_Candidate_Scores.csv", index=False)
    raw_fused.to_csv(result_dir / "RQ18_RawCNN_Fused_Candidates.csv", index=False)
    raw_decisions.to_csv(result_dir / "RQ18_RawCNN_Decisions.csv", index=False)
    raw_fit_records.to_csv(result_dir / "RQ18_RawCNN_Fit_Records.csv", index=False)
    training_history.to_csv(result_dir / "RQ18_RawCNN_Training_History.csv", index=False)

    tables["raw_seed_summary"].to_csv(result_dir / "RQ18_RawCNN_Seed_Summary.csv", index=False)
    tables["representation_summary"].to_csv(result_dir / "RQ18_Representation_Summary.csv", index=False)
    tables["password_summary"].to_csv(result_dir / "RQ18_Password_Summary.csv", index=False)
    tables["wheel_summary"].to_csv(result_dir / "RQ18_Wheel_Summary.csv", index=False)
    tables["direction_summary"].to_csv(result_dir / "RQ18_Direction_Summary.csv", index=False)
    tables["paired_tests"].to_csv(result_dir / "RQ18_Password_Paired_Tests.csv", index=False)

    with open(result_dir / "RQ18_RawCNN_Config.json", "w", encoding="utf-8") as f:
        json.dump(RAW_CONFIG, f, indent=2)

    summary = tables["representation_summary"].set_index("condition")
    eng_lr = summary.loc["695-D + Logistic Regression"]
    eng_cnn = summary.loc["695-D + CNN"]
    raw = summary.loc["Raw waveform + 1D CNN"]

    if raw["top1"] > eng_lr["top1"] and raw["password_top1_sd"] <= eng_lr["password_top1_sd"]:
        interpretation = (
            "The raw-waveform CNN achieved higher mean LOPO Top-1 than the strongest engineered-feature baseline "
            "without increasing password-level variability. This supports the end-to-end waveform hypothesis."
        )
    elif raw["top1"] > eng_cnn["top1"] and raw["top1"] <= eng_lr["top1"]:
        interpretation = (
            "Direct waveform learning improved on the CNN using the engineered 695-D representation, but did not exceed "
            "the 695-D Logistic Regression baseline. Representation choice helps the CNN, while the engineered-feature "
            "pipeline remains the stronger controlled research baseline overall."
        )
    elif raw["password_top1_sd"] > eng_lr["password_top1_sd"] and raw["worst_password_top1"] < eng_lr["worst_password_top1"]:
        interpretation = (
            "The raw-waveform CNN showed weaker cross-password stability than the engineered-feature Logistic Regression baseline, "
            "including greater password-level variation and a lower worst-password result. This is consistent with increased "
            "sensitivity to password/session-specific waveform structure."
        )
    else:
        interpretation = (
            "The raw-waveform CNN did not provide a clear generalisation advantage over the engineered 695-D representation under "
            "the fixed password-level LOPO protocol. Model complexity and representation effects should be interpreted separately."
        )

    conclusion = {
        "research_question": (
            "Does end-to-end learning directly from the dual-channel raw waveform improve password-level generalisation "
            "compared with the engineered 695-dimensional acoustic representation?"
        ),
        "analysis_type": "Controlled engineered-representation vs raw-waveform ablation",
        "primary_metric": "Password-level LOPO Top-1",
        "conditions": tables["representation_summary"].to_dict(orient="records"),
        "raw_seeds": RAW_SEEDS,
        "interpretation": interpretation,
        "deployment_note": "This RQ does not replace MAIN v8 in the operational unlocking system.",
        "next_step": "Carry the representation result into RQ19 cross-password generalisation and dissertation discussion.",
    }
    with open(result_dir / "RQ18_conclusion.json", "w", encoding="utf-8") as f:
        json.dump(conclusion, f, indent=2)

    report = [
        "# RQ18 — Engineered Acoustic Representation vs End-to-End Waveform Learning",
        "",
        "## Research question",
        "",
        conclusion["research_question"],
        "",
        "## Controlled comparison",
        "",
        "| Condition | Top-1 | Top-2 | Top-3 | MRR | Password SD | Worst password |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in tables["representation_summary"].itertuples():
        report.append(
            f"| {row.condition} | {100*row.top1:.1f}% | {100*row.top2:.1f}% | {100*row.top3:.1f}% | "
            f"{row.mrr:.3f} | {100*row.password_top1_sd:.1f} pp | {100*row.worst_password_top1:.1f}% |"
        )

    raw_seed_summary = tables["raw_seed_summary"]
    report.extend([
        "",
        "## Raw-CNN seed stability",
        "",
        f"Mean Top-1 across three seeds: {100*raw_seed_summary['top1'].mean():.1f}%",
        f"Seed-to-seed Top-1 SD: {100*raw_seed_summary['top1'].std(ddof=1):.2f} percentage points",
        "",
        "## Interpretation",
        "",
        interpretation,
        "",
        "## Scope",
        "",
        "This is a dissertation research ablation. MAIN v8 remains the deployed True-Gate model used by the operational system.",
    ])
    with open(result_dir / "RQ18_Report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")

    run_info = {
        "notebook": "18_RQ18_Engineered_vs_Raw_Waveform.ipynb",
        "development_batches": BATCHES,
        "outer_evaluation": "7-fold leave-one-password-out",
        "raw_seeds": RAW_SEEDS,
        "target_samples": TARGET_SAMPLES,
        "sample_rate": SAMPLE_RATE,
        "conditions": [
            "695-D + Logistic Regression",
            "695-D + CNN",
            "Raw waveform + 1D CNN",
        ],
        "primary_metric": "A/B-fused password-LOPO Top-1",
        "deployment_model": "MAIN v8 unchanged",
    }
    with open(result_dir / "RQ18_run_info.json", "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=2)

    return interpretation
