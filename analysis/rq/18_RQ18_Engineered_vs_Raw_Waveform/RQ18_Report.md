# RQ18 — Engineered Acoustic Representation vs End-to-End Waveform Learning

## Research question

Does end-to-end learning directly from the dual-channel raw waveform improve password-level generalisation compared with the engineered 695-dimensional acoustic representation?

## Controlled comparison

| Condition | Top-1 | Top-2 | Top-3 | MRR | Password SD | Worst password |
|---|---:|---:|---:|---:|---:|---:|
| 695-D + Logistic Regression | 86.0% | 95.5% | 97.9% | 0.920 | 7.6 pp | 76.7% |
| 695-D + CNN | 80.5% | 93.6% | 96.9% | 0.888 | 9.8 pp | 65.0% |
| Raw waveform + 1D CNN | 24.3% | 36.3% | 46.9% | 0.426 | 5.1 pp | 16.1% |

## Password-paired comparison

The raw-waveform CNN was lower on all seven held-out passwords than both engineered-feature conditions. Relative to 695-D + Logistic Regression, the mean password-level Top-1 difference was -61.7 percentage points (two-sided Wilcoxon p=0.0156). Relative to 695-D + CNN, the mean difference was -56.2 percentage points (p=0.0156). The 695-D CNN was 5.5 points below Logistic Regression on average; this difference was not statistically significant across the seven passwords (p=0.125).

## Raw-CNN stability and direction sensitivity

Mean Top-1 across the three independently evaluated raw-CNN seeds was 24.3%, with a seed-to-seed Top-1 SD of 1.04 percentage points. The poor performance is therefore not attributable to a single unlucky random initialisation.

A strong direction asymmetry was present: raw-CNN Top-1 was 37.9% in CCW but only 10.6% in CW. The two engineered-feature conditions were approximately direction-balanced. This indicates that direct waveform learning in this compact architecture was substantially more sensitive to the physical direction domain.

## Interpretation

Under the fixed seven-password LOPO protocol, the tested compact end-to-end 1D CNN substantially underperformed the engineered 695-D acoustic representation. The result supports retaining the engineered representation for the controlled dissertation model. It does not establish that every possible end-to-end waveform architecture would be inferior; it establishes that direct raw-waveform learning did not provide a generalisation advantage under the pre-specified compact CNN and matched evaluation protocol.

## Scope

This is a dissertation research ablation. MAIN v8 remains the deployed True-Gate model used by the operational system. RQ19 provides separate prospective evidence for historically frozen MAIN v7; its B07 result must not be reported as unseen performance of the dissertation Logistic Regression model selected here.
