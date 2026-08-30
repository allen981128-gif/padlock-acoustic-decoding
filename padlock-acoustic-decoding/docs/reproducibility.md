# Reproducibility notes

## Source snapshot

This Git repository is a cleaned dissertation snapshot assembled from the final source archives supplied for the project. Build products, local editor files, Python caches and machine-specific runtime settings are excluded.

The original uploaded source-archive SHA-256 values are recorded in `artifact_hashes.md`.

## Host application

The application source is under `host_app/`. The machine-specific `settings.json` is deliberately excluded. Copy `settings.example.json` to `settings.json` before running.

Frozen True-Gate runtime files are under `host_app/model_assets/`.

## Firmware

The PlatformIO source is under `firmware/`. The original `.pio/` build directory was removed from the repository because it contained generated binaries and machine-local PlatformIO paths. The source-level GPIO and calibration constants are preserved.

## CAD

The Fusion 360 script tree is under `cad/fusion_scripts/`. Editor metadata and Python bytecode caches are removed. The archived integrated Fusion file is stored at `cad/Mechanical_system_geometry.f3d`.

## Analysis

The complete set of formal RQ1--RQ23 Colab notebooks is included under `analysis/rq/`. Companion Python implementations are retained for RQ18 and RQ20--RQ23 where they were part of the formal analysis package. `analysis/final_model_training/` contains the controlled model-family comparison used as a separate dissertation analysis artifact.

The notebooks are preserved as executed research snapshots, so some contain the original Colab/Google Drive paths. These paths must be adapted for a different environment. Bulk derived outputs, feature caches, the full chronological experiment archive and raw acoustic datasets are maintained separately and are not duplicated into this source repository.

## Evaluation boundaries

The deployed engineering model is MAIN v8. MAIN v7 is retained because its B01-B06 freeze and prospective B07 evaluation form an important evidence boundary. The controlled final-model comparison notebook is a dissertation analysis artifact and should not be confused with the deployed runtime model.
