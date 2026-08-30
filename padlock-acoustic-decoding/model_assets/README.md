# Frozen runtime model assets

The deployed runtime assets are stored under `host_app/model_assets/`.

## MAIN v7

- Runtime manifest: `host_app/model_assets/MAIN_v7_FOCUS_RUNTIME.json`
- Runtime array: `host_app/model_assets/MAIN_v7_FOCUS_RUNTIME.npz`
- Source checkpoint SHA-256: `ac2b68afd01eb3c43db7c12d0e581c7f5e605aa6b86968a871a410ae65b59768`
- Training scope: B01-B06 only.
- Role: frozen prospective evaluation on B07 and historical compatibility.

## MAIN v8

- Runtime manifest: `host_app/model_assets/MAIN_v8_ACCURACY_ENSEMBLE_RUNTIME.json`
- Runtime array: `host_app/model_assets/MAIN_v8_ACCURACY_ENSEMBLE_RUNTIME.npz`
- Source checkpoint SHA-256: `bfffd49453315d7cb835a409105e4bf3a29412f6b5a51c75a9ac48d41f007e6a`
- Training scope: B01-B07 Dataset v1.
- Role: deployed W1/W2/W4 automatic-recognition runtime.

## W3 unlock detector

`host_app/unlock_detector_v1.py` implements the deterministic W3 physical-release detector used by the application.
