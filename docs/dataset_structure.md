# Dataset structure

Dataset v1 is the core controlled True-Gate dataset used by the dissertation.

## Inventory

| Batch | Combination | Profiles | 10-way decisions | Candidate records |
|---|---:|---:|---:|---:|
| B01 | 2085 | 30 | 120 | 1200 |
| B02 | 4369 | 30 | 120 | 1200 |
| B03 | 5720 | 30 | 120 | 1200 |
| B04 | 6893 | 30 | 120 | 1200 |
| B05 | 7246 | 30 | 120 | 1200 |
| B06 | 8451 | 30 | 120 | 1200 |
| B07 | 9638 | 30 | 120 | 1200 |
| **Total** | **7** | **210** | **840** | **8400** |

The three acoustic-ranking wheels are W1, W2 and W4. Each wheel has ten starting-position profiles. Each profile contains CCW-A, CCW-B, CW-A and CW-B complete Digit Scans, and each scan contains ten one-digit candidate movements.

## Naming hierarchy

Example:

```text
B01_2085
B01_W1_P01
B01_W1_P01_DSV1_MP2085_CCW
B01_W1_P01_DSV1_MP2085_CCW_A
run_000001
```

Candidate WAVs are not treated as independent experimental units. The complete ten-candidate decision is the atomic ranking unit.

## Raw run layout

A typical run directory contains:

```text
run_000001/
  audio.wav
  motor_reference.wav
  audio_dual.wav
  events.csv
  serial_log.csv
  metadata.json
  quality.json
```

Raw datasets are excluded from this Git repository. They remain in the separately archived project dataset.
