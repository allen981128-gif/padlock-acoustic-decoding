# Dissertation analysis archive

This directory preserves the formal analysis code associated with the dissertation.

## `rq/`

`rq/` contains the original Colab notebook for every research question, RQ1 through RQ23. The `00_RQ1-4_QC_support/` directory preserves the compact QC manifest/checks used by the early feasibility notebooks; it contains no separate Colab notebook. The notebooks are retained as archival analysis artifacts rather than rewritten into a new synthetic pipeline. Where the formal RQ package also used a standalone Python implementation, that script is stored next to the corresponding notebook.

Historical notebook filenames and internal comments are preserved for auditability; some therefore retain earlier project terminology such as `password` where the dissertation now uses `combination`.

The notebooks may contain references to the original Colab/Google Drive directory layout (for example `/content/drive/MyDrive/...`). Those paths identify the environment in which the archived analysis was executed and must be adapted when rerunning on another machine. The raw WAV datasets, feature caches, large prediction tables and generated figures are maintained in the separate project archive and are not duplicated here.

See `RQ_INDEX.md` for the notebook inventory.

## `final_model_training/`

Controlled model-family comparison on the engineered acoustic representation. The notebook and associated report/config/summary are preserved together. This analysis artifact is distinct from the deployed MAIN v8 runtime under `host_app/model_assets/`.
