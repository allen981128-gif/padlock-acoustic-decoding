# Padlock Collector App

Research-control application for the automated four-wheel padlock apparatus. The current application combines raw dual-channel acoustic data collection, manual hardware control, signal review, frozen True-Gate inference and supervised physical-unlock verification.

## Current recognition workflow

Automatic Recognition uses the frozen **TRUE-GATE MAIN v8 ACCURACY** runtime for W1, W2 and W4. Each wheel is evaluated using the Dataset-v1-compatible Digit Scan protocol: ten one-digit candidates are recorded for each CCW/CW and A/B component, and MAIN v8 fuses the resulting candidate evidence. The operator confirms the physical movement between sequential wheel decisions.

After the W1/W2/W4 Top-1 prefix is applied, W3 is searched by a continuous one-digit CCW sweep. **Physical Unlock Detector v1** evaluates each saved movement from the contact microphone using the frozen post-SCAN_END RMS/dRMS rule; a detector trigger pauses the workflow and the operator confirms whether the lock is physically open.

If a complete W3 sweep produces no confirmed opening and the minimum W1/W2/W4 MAIN-v8 margin is below the fixed pilot threshold of 0.20, the App permits one fresh randomized recognition pass. The maximum number of full recognition passes is two. Evidence-ranked Top-2 prefix fallback remains available after this bounded retry logic.

## Main application areas

- **Collection** — raw Digit Scan / Binding Scan compatible data collection with run-level metadata, event alignment and QC.
- **Manual Control** — wheel, rail and servo verification and positioning.
- **Signal Review** — inspection of completed runs without modifying raw recordings.
- **Recognition** — supervised automatic recognition plus offline scoring of MAIN-v8-compatible sessions.

## Data policy

Raw recordings are preserved. A run may contain `audio.wav`, `audio_dual.wav`, `motor_reference.wav`, `events.csv`, `metadata.json`, `quality.json` and serial logs. Normalisation, filtering, template cancellation or other experimental preprocessing should be written as derived data rather than overwriting the raw acquisition.

For Dataset-v1-compatible decisions, the grouping hierarchy is important: candidate WAVs belong to a ten-candidate decision; direction/repeat decisions belong to a profile; profiles belong to a password batch. Random WAV-level train/test splitting is not an appropriate evaluation protocol for the research models.

## Frozen model assets

`model_assets/` contains the deployed MAIN v7 and MAIN v8 runtime assets. Automatic Recognition uses MAIN v8. MAIN v7 assets are retained for historical evaluation and compatibility with earlier experiments.

Some acquisition metadata still contains the legacy internal identifier `auto_recognition_main_v7`. It is intentionally retained at this cleanup stage so existing datasets and parsers remain compatible; it does **not** indicate that current automatic scoring uses MAIN v7.

## Setup and run (Windows)

1. Install Python.
2. Run `setup_app.bat` to create `.venv` and install `requirements.txt`.
3. Connect the ESP32 and Focusrite interface.
4. Review `settings.json` for the serial port, audio device and dataset location.
5. Run `run_app.bat`.

`build_app.bat` creates a PyInstaller one-directory build under `dist/PadlockCollector/`. Build outputs are deliberately excluded from the clean source package.

## Entry points

- `app.py` — PySide6 GUI entry point.
- `main.py` — command-line collection entry point.
- `true_gate_inference.py` — frozen MAIN v8 inference implementation.
- `auto_recognition.py` — automatic-recognition state/persistence and fallback policy helpers.
- `unlock_detector_v1.py` — deterministic W3 physical-unlock detector.

## Research status

This repository is a research prototype for controlled, authorised laboratory evaluation. Model-development notebooks and historical experimental scripts are maintained separately from the final runtime source so the deployed code is not confused with the experiment archive.

## Source layout

The desktop application is intentionally split by responsibility:

- `app_window.py` — main application state and workflow coordination.
- `app_ui.py` — static page construction, navigation layout and presentation-only widget builders.
- `app_recognition_validation.py` — offline MAIN-v8 validation controls and result presentation.
- `app_theme.py` — application and modal-dialog Qt style sheets.
- `app_dialogs.py` — reusable themed dialogs and small presentation widgets.
- `app_backend.py` — hardware-facing orchestration used by the UI.
- `auto_recognition.py` — recognition-session bookkeeping, ranking and retry policy.
- `true_gate_inference.py` — frozen MAIN v8 feature extraction and inference runtime.
- `unlock_detector_v1.py` — frozen W3 physical-unlock detector.
- `decision_batch.py` — Dataset-v1 / Binding Scan plan and decision handling.

Research-model code and frozen runtime assets are kept separate from presentation-only UI code. The automatic-recognition and collection state machines remain in `app_window.py`; the extracted UI modules do not implement model or hardware decisions.
