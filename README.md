# Acoustic Recognition and Closed-Loop Automated Decoding of a Mechanical Combination Padlock

This repository is the version-controlled software and reproducibility snapshot associated with an MSc individual research project on controlled contact-acoustic recognition and closed-loop mechanical operation of a four-wheel combination padlock.

The repository is intended for **authorised laboratory research and dissertation examination**. It contains the final host application source, embedded-control firmware, CAD-generation scripts, the complete RQ1--RQ23 Colab notebook set, selected companion analysis scripts, and frozen runtime model assets used by the deployed research system.

## Repository status

- Repository: `padlock-acoustic-decoding`
- Submission snapshot: `dissertation-v1.0`
- Visibility at submission: **Private**
- Public release: review with the project supervisor before changing visibility.

## Contents

- `host_app/` — final Python/PySide6 acquisition, signal-review and supervised recognition application.
- `firmware/` — PlatformIO/Arduino firmware for the Adafruit Feather ESP32-S3, wheel drive, rail positioning, servo engagement, homing and acquisition timing.
- `cad/fusion_scripts/` — parameterised Autodesk Fusion 360 scripts and print-layout utilities.
- `cad/Mechanical_system_geometry.f3d` — archived Fusion 360 assembly/design file.
- `analysis/rq/` — archived Colab notebooks for RQ1--RQ23; later RQs also include the companion Python implementations where these were part of the formal analysis.
- `analysis/final_model_training/` — controlled model-family comparison on the engineered acoustic representation.
- `model_assets/` — manifest describing the deployed frozen runtime assets stored under `host_app/model_assets/`.
- `docs/` — hardware configuration, dataset structure, reproducibility notes and artifact hashes.
- `data/` — data-availability note only. Raw WAV datasets are not stored in Git.

## Deployed recognition system

The host application contains the frozen `MAIN v8` runtime used for W1, W2 and W4 acoustic ranking and the deterministic W3 physical-unlock detector. `MAIN v7` runtime assets are retained for the frozen prospective B07 evaluation and compatibility with earlier evidence.

The application is a supervised research prototype. Final physical opening is confirmed by the operator. The dissertation separates model-level ranking accuracy from end-to-end physical-unlock outcomes.

## Quick start

### Host application

1. Install Python 3.
2. Create a virtual environment.
3. Install dependencies with:
   `pip install -r host_app/requirements.txt`
4. Copy `host_app/settings.example.json` to `host_app/settings.json`.
5. Set the serial port, audio device and local dataset path for the current machine.
6. Connect the ESP32 controller and Focusrite audio interface.
7. Run `python host_app/app.py`.

The original Windows helper scripts under `host_app/` may also be used.

### Firmware

Open `firmware/` as a PlatformIO project. The target is `adafruit_feather_esp32s3`, with Arduino framework and an ESP32Servo dependency. Build and upload through PlatformIO.

### Fusion 360

The scripts under `cad/fusion_scripts/` are numbered to preserve the geometric dependency order used by the project. Start with `00_Lock_Parameters` and proceed through the required components. The archived `.f3d` file provides the realised integrated geometry.

## Research-question analysis

The formal Colab notebook used for each dissertation research question is preserved under `analysis/rq/`, from RQ1 through RQ23. These are archived research snapshots rather than a single turnkey pipeline: some notebooks reference the original Google Drive/Colab directory layout and therefore require path adaptation if rerun elsewhere. Generated bulk CSV predictions, cached features and raw WAV datasets are not duplicated in Git. See `analysis/README.md` and `analysis/RQ_INDEX.md`.

## Data

The raw acoustic datasets are archived separately because they are large and include many WAV files. Dataset v1 contains seven fixed-combination batches and is organised by batch, wheel, starting-position profile, direction, A/B repeat, ten-candidate decision and candidate run. See `docs/dataset_structure.md`.

## Reproducibility boundary

The repository preserves the configuration that can be verified from the final source and frozen runtime manifests. It does not retrospectively invent unrecovered analogue or driver settings. In particular, the exact TMC2209 microstepping/current-limit/Vref settings and absolute Focusrite gain-knob position were not reliably preserved in the final project record.

## Citation

See `CITATION.cff`. Replace the temporary author placeholder with the official dissertation author name before making the repository public.

## Licence and release

No public reuse licence is granted in this private dissertation snapshot. A public licence should be selected only if the repository is later approved for public release.

## Responsible use

This project concerns physical-security research. Use the hardware and software only on locks and equipment that you own or are explicitly authorised to test. The repository is provided for academic reproducibility and examination, not for unauthorised access.
