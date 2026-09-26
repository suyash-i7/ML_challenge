# Amazon ML Challenge 2026 — Business Entity Resolution

## 1. Overview

This project implements a scalable **Business Entity Resolution** pipeline for the Amazon ML Challenge 2026.

The task is to identify all matching records in **Source 2 (S2)** and **Source 3 (S3)** corresponding to each entity in **Source 1 (S1)**.

The pipeline is designed for large datasets and uses **DuckDB, Parquet, selective blocking, and candidate generation** to avoid infeasible brute-force comparisons.

### Current Progress

* Dataset exploration and EDA — Complete
* Ground-truth analysis — Complete
* Normalization and DuckDB preparation — Complete
* Blocking experiments — Complete
* High-recall blocking ensemble — Complete
* Training candidate generation — Complete
* Feature engineering / final matching model — In progress

The current blocking strategy achieved approximately **88.82% recall on the training ground truth** during blocking experiments.

---

# 2. Project Structure

```text
ML_challenge/
│
├── README.md
├── Documentation_template.md
├── requirements.txt
├── .gitignore
│
├── member1_candidate_generation.py
├── member1_generate_candidates_safe.py
│
├── phase4_prepare.py
├── phase5_blocking_recall.py
├── phase5_safe_recall.py
│
├── phase6_experiment1.py
├── phase6_experiment2.py
├── phase6_experiment3.py
├── phase6_address_diagnostic.py
├── phase6_address_volume.py
├── phase6_debug.py
│
├── dataset/                         # Not committed to Git
│   ├── train/
│   └── test/
│
├── work/                            # Generated files; not committed
│   ├── entity_resolution.duckdb
│   ├── train_candidate_pairs.parquet
│   └── ...
│
├── output/
│   └── candidate_pairs.tsv
│
├── utils/
│   └── validate_submission.py
│
└── code/
    └── business_entity_resolution/
        └── src/
```

---

# 3. Dataset

The challenge dataset is **not included in this repository** because of its large size.

The following files must be provided separately:

```text
dataset/
├── train/
│   ├── train_source1.tsv
│   ├── train_source2.tsv
│   ├── train_source3.tsv
│   └── train_ground_truth.tsv
│
└── test/
    ├── test_source1.tsv
    ├── test_source2.tsv
    └── test_source3.tsv
```

Do not commit the `dataset/` directory to Git.

---

# 4. Environment Setup

## Requirements

Recommended:

* Python 3.10+
* DuckDB
* Git
* Windows PowerShell / Linux / macOS terminal

Create a virtual environment:

```powershell
python -m venv .venv
```

For PowerShell, if script execution is restricted:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Activate the environment:

```powershell
.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
pip install -r requirements.txt
```

---

# 5. Prepare the Working Database

After placing the challenge dataset in the required `dataset/` directory, run:

```powershell
python phase4_prepare.py
```

This prepares the normalized Parquet datasets and creates:

```text
work/entity_resolution.duckdb
```

The `work/` directory contains generated files and does not need to be committed or transferred between team members.

---

# 6. Data Normalization

The preparation pipeline creates normalized fields used by the blocking system.

The normalization includes:

* Lowercasing
* Replacing `&` with `and`
* Removing/replacing punctuation
* Collapsing whitespace
* Trimming values
* Normalizing country values

Blocking keys include:

```text
block_name_exact
block_address_exact
block_name_prefix5
block_address_prefix8
block_postal
```

Additional keys are generated during candidate generation.

---

# 7. Blocking Research

Several blocking strategies were evaluated against the training ground truth.

The important blocking signals include:

```text
Exact Name
Exact Address
Name Prefix
Address Prefix
Address Number
Postal Code
Address Number + Name Prefix
Address Number + Word
Cross-Word Address Matching
Postal + Address Number
Postal + Name Prefix
```

The final selective ensemble combines multiple blocking rules to improve recall while avoiding the enormous candidate volume produced by unrestricted address-number matching.

The final blocking research achieved approximately:

```text
6,784,544 / 7,638,365
≈ 88.82% blocking recall
```

This is a **candidate-generation recall**, not the final competition F0.5 score.

---

# 8. Training Candidate Generation

The current Member 1 candidate-generation script is:

```powershell
python member1_candidate_generation.py
```

It creates enriched blocking keys for:

```text
train_s1
train_s2
train_s3
```

and generates candidate pairs for:

```text
S1 → S2
S1 → S3
```

Each candidate pair contains blocking evidence such as:

```text
match_exact_name
match_exact_addr
match_addr_name5
match_cross_word
match_addr_w2
match_post_addr
match_post_name4
```

These signals are intended to be used by the next stage for feature engineering and candidate scoring.

---

# 9. Training Outputs

After running:

```powershell
python member1_candidate_generation.py
```

the following files are generated:

```text
work/
├── train_candidate_pairs.parquet
└── train_candidates.tsv
```

### `train_candidate_pairs.parquet`

Contains pair-level candidate information for feature engineering.

Conceptually:

```text
S1 entity
    ↓
candidate S2/S3 entity
    ↓
blocking evidence
    ↓
candidate pair
```

### `train_candidates.tsv`

Contains one row per S1 entity:

```text
source1_entity_id
candidate_entity_ids
```

---

# 10. Test Candidate Generation

The safe candidate-generation pipeline also supports generation of the official test candidate file:

```powershell
python member1_generate_candidates_safe.py
```

The official test candidate output is:

```text
output/candidate_pairs.tsv
```

The test pairwise Parquet is:

```text
work/test_candidate_pairs.parquet
```

The test candidate set must be generated before final matching predictions are produced.

---

# 11. Candidate Generation Architecture

The overall architecture is:

```text
                    Source 1
                       │
          ┌────────────┴────────────┐
          │                         │
          ▼                         ▼
        Source 2                  Source 3
          │                         │
          └────────────┬────────────┘
                       ▼
                Blocking Layer
                       │
                       ▼
              Candidate Generation
                       │
                       ▼
             Candidate Pair Dataset
                       │
                       ▼
              Feature Engineering
                       │
                       ▼
                Match Scoring
                       │
                       ▼
             Final Entity Resolution
```

---

# 12. Validation

The official validation script is:

```powershell
python utils/validate_submission.py `
    --matching output/matching_results.tsv `
    --candidate output/candidate_pairs.tsv `
    --test-dir dataset/test
```

The validation checks the required submission structure and candidate constraints.

---

# 13. Expected Final Outputs

The final submission must contain:

```text
output/
├── matching_results.tsv
└── candidate_pairs.tsv
```

### `matching_results.tsv`

Exactly one row for every test S1 entity.

Expected format:

```text
source1_entity_id    matched_entity_ids
```

`matched_entity_ids` contains the matching S2/S3 entity IDs separated according to the challenge specification.

If no match exists, the field should be empty.

### `candidate_pairs.tsv`

Exactly one row for every test S1 entity.

Expected format:

```text
source1_entity_id    candidate_entity_ids
```

The final predicted matches must be a subset of the generated candidate IDs.

---

# 14. Important Git Rules

The following directories contain large datasets or generated files and should not be committed:

```text
dataset/
work/
```

The repository should contain:

* Source code
* Configuration
* Documentation
* Requirements
* Validation utilities
* Reproducible pipeline scripts

A new team member should recreate `work/` locally by running the preparation pipeline.

---

# 15. Team Handoff

A new team member can reproduce the environment using:

```powershell
git clone <REPOSITORY_URL>
cd ML_challenge

python -m venv .venv

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Then place the challenge dataset in:

```text
dataset/
```

Prepare the database:

```powershell
python phase4_prepare.py
```

Generate training candidates:

```powershell
python member1_candidate_generation.py
```

The resulting training candidate dataset is:

```text
work/train_candidate_pairs.parquet
```

This file is the handoff point to the next stage of the project.

---

# 16. Current Team Responsibility

## Member 1 — Blocking / Candidate Generation

Completed:

* Dataset preparation
* Normalization
* Blocking research
* Blocking recall evaluation
* Selective blocking ensemble
* Training candidate generation

Current handoff:

```text
train_candidate_pairs.parquet
```

## Member 2 — Feature Engineering / Matching

Next tasks:

* Load candidate pairs
* Join S1/S2/S3 normalized records
* Calculate name similarity
* Calculate address similarity
* Use blocking-rule indicators
* Create positive/negative training examples
* Train and validate a matching model
* Produce final match predictions

## Final Integration

The final pipeline should produce:

```text
output/candidate_pairs.tsv
output/matching_results.tsv
```

and pass:

```powershell
python utils/validate_submission.py `
    --matching output/matching_results.tsv `
    --candidate output/candidate_pairs.tsv `
    --test-dir dataset/test
```

---

# 17. Important Notes

* Do not brute-force S1 × S2/S3 comparisons.
* Do not commit the challenge dataset.
* Do not commit the generated DuckDB/Parquet working files.
* Candidate generation and final matching are separate stages.
* Blocking recall is not the same as final competition score.
* The final model must only predict from generated candidate pairs.
* External identity databases, APIs, geocoding services, or prohibited external data must not be used.

---

# 18. Development Status

```text
Phase 1 — Dataset / EDA                 ✅
Phase 2 — Ground Truth Analysis        ✅
Phase 3 — Normalization / Preparation  ✅
Phase 4 — Blocking Preparation         ✅
Phase 5 — Blocking Recall              ✅
Phase 6 — Blocking Experiments         ✅
Member 1 — Candidate Generation        ✅
Phase 7 — Feature Engineering          🔄
Phase 8 — Matching Model               ⏳
Phase 9 — Test Prediction              ⏳
Phase 10 — Submission Validation       ⏳
```

The current handoff point is:

```text
Blocking
   ↓
Candidate Generation
   ↓
work/train_candidate_pairs.parquet
   ↓
Feature Engineering / Matching
```
