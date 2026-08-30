# Final Model Training Report

> **Role:** dissertation-controlled benchmark on the engineered 695-D representation. This report does **not** replace MAIN v8, which remains the deployed True-Gate model used by the App.

## Development protocol

B01-B07 were used for model development and seven-fold password-level model selection.
The selected family was then retrained on all B01-B07 and frozen.
A future password collected after this freeze is required for final unbiased evaluation.

## Compared model families

- Logistic Regression
- RBF-SVM
- HistGradientBoosting
- MLP
- CNN
- CNN + LSTM
- CNN + BiLSTM
- CNN + BiGRU
- CNN + Transformer

## Overall model comparison

| Model | Top-1 | Top-2 | Top-3 | Macro-F1 | Weighted-F1 | Mean rank |
|---|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 86.0% | 95.5% | 97.9% | 0.860 | 0.859 | 1.23 |
| CNN + BiLSTM | 80.7% | 94.3% | 96.7% | 0.815 | 0.808 | 1.31 |
| CNN | 80.5% | 93.6% | 96.9% | 0.809 | 0.804 | 1.31 |
| CNN + BiGRU | 79.8% | 92.6% | 96.2% | 0.799 | 0.797 | 1.35 |
| RBF-SVM | 78.6% | 92.4% | 97.4% | 0.791 | 0.787 | 1.35 |
| CNN + LSTM | 77.1% | 91.9% | 96.7% | 0.774 | 0.771 | 1.37 |
| CNN + Transformer | 75.7% | 90.0% | 94.8% | 0.762 | 0.756 | 1.46 |
| HistGradientBoosting | 72.1% | 87.9% | 94.0% | 0.717 | 0.723 | 1.51 |
| MLP | 67.9% | 83.3% | 91.4% | 0.682 | 0.678 | 1.67 |

## Selected research-comparison model

**Logistic Regression**

Top-1: 86.0%
Top-2: 95.5%
Top-3: 97.9%
Macro-F1: 0.860
Weighted-F1: 0.859
Mean true rank: 1.23

## Analysis package

- classification report for all model families
- confusion matrix for all model families
- per-digit F1
- per-wheel performance
- per-direction performance
- per-password performance
- neural train/validation loss
- neural validation Top-1
- early-stopping epochs
- model training time and serialized size

## Research-artifact freeze status

`Final_TrueGate_Model_FROZEN.zip` is the post-selection full B01-B07 **research benchmark** package. It is not the operational MAIN v8 deployment model.

**Do not report B01-B07 replay as final unseen accuracy after this freeze, and do not present this frozen Logistic Regression artifact as replacing MAIN v8.**

RQ19's prospective B07 result belongs to the historically frozen MAIN v7 operational branch and is not an unseen test of this selected Logistic Regression research artifact.
