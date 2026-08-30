# RQ18 — Engineered Acoustic Representation vs End-to-End Waveform Learning

## Status

COMPLETED.

This is a dissertation research experiment. It does not replace MAIN v8, which remains the deployed True-Gate model used by the operational unlocking system.

Completed result: 695-D + Logistic Regression achieved 86.0% Top-1, 695-D + CNN 80.5%, and the tested raw-waveform 1D CNN 24.3% under matched password-level LOPO.

## Research question

Does end-to-end learning directly from the dual-channel raw waveform improve password-level generalisation compared with the engineered 695-dimensional acoustic representation?

## Scientific purpose

The completed 695-D model-family comparison showed that Logistic Regression gave the strongest controlled password-level result, while higher model complexity did not improve performance. That experiment changed the model family while keeping the engineered representation fixed.

RQ18 changes the representation and asks whether the engineered acoustic representation itself is preferable to direct waveform learning.

## Competing hypotheses

### H1 — Engineered-representation robustness

The 695-D acoustic representation suppresses irrelevant waveform variability while preserving transferable true-gate information, giving stronger and more stable cross-password generalisation.

### H2 — End-to-end waveform advantage

A 1D CNN trained directly on the waveform can learn useful local temporal structure that is lost or compressed by handcrafted feature extraction, giving equal or better cross-password performance.

### H3 — Raw-waveform shortcut risk

The raw waveform contains additional session-, password-, motor- and transmission-correlated information. A higher-capacity CNN may exploit those fingerprints, giving strong pooled accuracy but larger password-to-password variation or a weaker worst-password result.

## Controlled conditions

Three conditions are compared:

| Condition | Representation | Model | Role |
|---|---|---|---|
| A | Engineered 695-D | Logistic Regression | Best engineered-feature baseline |
| B | Engineered 695-D | CNN | Controls model-family effect |
| C | Raw dual-channel waveform | Compact 1D CNN | End-to-end waveform condition |

Conditions A and B are taken from the completed controlled Final Model Training comparison. Condition C must reuse the same outer evaluation structure.

## Fixed protocol

- Dataset: B01–B07
- Atomic task: one complete 10-candidate true-gate ranking decision
- Signal scope: Current movement only
- Channels: contact microphone + motor-reference channel
- Wheel handling: wheel-specific
- Direction handling: CW and CCW remain separate known physical domains
- Repeats: A+B used for training
- Inference: within-scan score standardisation followed by matched A/B score fusion by physical digit
- Outer evaluation: seven-fold leave-one-password-out using exactly the same held-out passwords as the 695-D comparison
- No password ID, batch ID, profile ID, repeat ID, candidate ordinal, physical digit, run ID or equivalent identifier may be supplied to the model

## Raw-waveform condition

- Source: original dual-channel WAVs
- Window: the same physical one-digit movement interval represented by the Current-only 695-D features
- Convert PCM to floating-point waveform values
- Crop/pad to one fixed input length using a deterministic rule
- Any channel scaling/standardisation parameters must be estimated using outer-training passwords only
- The held-out password must not contribute to preprocessing statistics
- Do not apply per-recording amplitude normalisation if it removes absolute acoustic information that may be physically useful
- Do not convert the raw condition to Mel spectrograms; this RQ is specifically a direct-waveform comparison

## Raw 1D-CNN design principle

Use a deliberately compact architecture rather than an extensive architecture search. A suitable baseline is repeated Conv1D -> activation -> down-sampling blocks followed by global pooling and a scalar candidate-score output.

The scientific question is representation choice, not a search for the largest possible deep network.

Because CNN training is stochastic, evaluate the raw-waveform condition with at least three fixed random seeds. Keep outer folds and all data-processing rules identical across seeds.

## Primary metric

Password-level LOPO Top-1 accuracy.

## Secondary metrics

- Top-2
- Top-3
- Mean Reciprocal Rank
- Mean true rank
- Per-password Top-1
- Password-level mean and standard deviation
- Worst-password Top-1
- Per-wheel Top-1
- Per-direction Top-1
- Password-paired differences between conditions
- Across-seed mean and standard deviation for the raw CNN

## Interpretation rule

- If raw CNN exceeds both engineered conditions and remains equally or more stable across held-out passwords, support H2.
- If raw CNN is similar to the 695-D CNN but both remain below 695-D Logistic Regression, model complexity rather than handcrafted feature extraction is the likely limitation.
- If raw CNN has high pooled accuracy but substantially greater password-level variance or a much weaker worst-password result, support H3.
- If 695-D Logistic Regression remains strongest and most stable, retain the engineered representation as the more defensible dissertation research representation.

## Relationship to later RQs

After insertion of this experiment:

- RQ18 = Engineered representation vs raw waveform learning
- RQ19 = Prospective cross-password generalisation audit of historically frozen MAIN v7 (a separate operational evidence branch, not an unseen test of the selected dissertation Logistic Regression model)
- RQ20 = Sequential upstream-prefix dependency
- RQ21 = Binding as scan-level state detector / safety veto
- RQ22 = W3 physical unlock detector
- RQ23 = Closed-loop recovery / Fresh Retry

## Deployment boundary

MAIN v8 remains the engineering/deployment model. Results from RQ18 are used to support the dissertation's representation and generalisation analysis only unless a separate future engineering decision explicitly changes the deployed model.

## Implementation artifacts

- Notebook: `18_RQ18_Engineered_vs_Raw_Waveform.ipynb`
- Experiment module: `RQ18_raw_vs_engineered.py`
- Raw input: `audio_dual.wav`, sliced using `SCAN_START` and `SCAN_END` from each run's `events.csv`
- Fixed raw input length: 12,288 samples per channel; shorter movement windows are zero-padded and any longer window causes the notebook to stop rather than silently crop
- Raw-cache I/O follows the established earlier-RQ workflow: each full B01–B07 raw ZIP (>50 MB; normally about 200–300 MB) is copied once from mounted Drive to `/content`, extracted locally, all 1,200 runs are read from local disk, and the local extracted batch is deleted before the next batch. The implementation deliberately refuses similarly named tiny archives and does not fall back to thousands of mounted-Drive small-file reads.
- Persistent raw cache and per-domain checkpoints are stored inside the RQ18 result folder so interrupted Colab runs can resume without repeating completed work
- Conditions A and B are read from the completed `Final_Model_Training/Final_Model_LOPO_Predictions.csv`; they are not retrained in RQ18
- Condition C is evaluated across three independent fixed seeds; the reported raw-CNN result is the mean of the three seed-level evaluations, not an ensemble
