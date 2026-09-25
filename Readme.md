amazon-ml-challenge/
│
├── dataset/
│   │
│   ├── train/
│   │   ├── train_source1.tsv
│   │   ├── train_source2.tsv
│   │   ├── train_source3.tsv
│   │   └── train_ground_truth.tsv
│   │
│   └── test/
│       ├── test_source1.tsv
│       ├── test_source2.tsv
│       └── test_source3.tsv
│
├── output/
│
├── code/
│   └── business_entity_resolution/
│       └── src/
│
├── utils/
│   └── validate_submission.py
│
├── README.md
├── Documentation_template.md
└── eda.py


///instructions
1.
git clone <YOUR_REPO_URL>
cd ML_challenge

2.
python --version

3.
python -m venv .venv

4.
.venv\Scripts\Activate.ps1

5.
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1

6.
pip install -r requirements.txt

7.
ML_challenge/
│
├── dataset/
│   ├── train/
│   │   ├── train_source1.tsv
│   │   ├── train_source2.tsv
│   │   ├── train_source3.tsv
│   │   └── train_ground_truth.tsv
│   │
│   └── test/
│       ├── test_source1.tsv
│       ├── test_source2.tsv
│       └── test_source3.tsv