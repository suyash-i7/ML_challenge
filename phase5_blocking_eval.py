from pathlib import Path
import duckdb
import time

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"

DB_PATH = WORK / "entity_resolution.duckdb"

con = duckdb.connect(str(DB_PATH))
con.execute("PRAGMA threads=4")

print("=" * 70)
print("PHASE 5 — BLOCKING RECALL EVALUATION")
print("=" * 70)

# ------------------------------------------------------------
# Load ground truth
# ------------------------------------------------------------

GT = ROOT / "dataset" / "train" / "train_ground_truth.tsv"

con.execute(f"""
    CREATE OR REPLACE VIEW ground_truth AS
    SELECT *
    FROM read_csv_auto(
        '{GT.as_posix()}',
        delim='\\t',
        header=true
    )
""")

print("\nGround truth loaded.")


# ------------------------------------------------------------
# Check ground truth column names
# ------------------------------------------------------------

print("\nGround truth columns:")

cols = con.execute("""
    DESCRIBE ground_truth
""").fetchall()

for c in cols:
    print(" ", c[0])


# ------------------------------------------------------------
# Create a normalized ground truth link table
# ------------------------------------------------------------

# The ground truth normally contains source information in
# matched_entity_ids. We inspect the structure before parsing.

print("\nSample ground truth:")

sample = con.execute("""
    SELECT *
    FROM ground_truth
    LIMIT 5
""").fetchall()

for row in sample:
    print(row)


print("\n" + "=" * 70)
print("PHASE 5 INITIAL INSPECTION COMPLETE")
print("=" * 70)

print("""
We are intentionally stopping before candidate generation.

Next step will parse the actual ground-truth ID format and
measure recall for:

1. Exact normalized name
2. Exact normalized address
3. Address prefix
4. Postal block
5. Combined blocking rules
""")

con.close()