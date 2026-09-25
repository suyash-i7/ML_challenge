from pathlib import Path
import duckdb
import time

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"

DB_PATH = WORK / "entity_resolution.duckdb"

con = duckdb.connect(str(DB_PATH))
con.execute("PRAGMA threads=4")

print("=" * 70)
print("PHASE 5 — ACTUAL BLOCKING RECALL")
print("=" * 70)


# ============================================================
# 1. LOAD GROUND TRUTH
# ============================================================

GT = ROOT / "dataset" / "train" / "train_ground_truth.tsv"

con.execute(f"""
CREATE OR REPLACE VIEW ground_truth AS
SELECT
    source1_entity_id,
    matched_entity_ids
FROM read_csv_auto(
    '{GT.as_posix()}',
    delim='\\t',
    header=true
)
""")


# ============================================================
# 2. EXPLODE GROUND TRUTH
# ============================================================

print("\nParsing ground truth...")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_links AS

SELECT
    source1_entity_id,
    trim(match_id) AS matched_id

FROM ground_truth,
UNNEST(
    string_split(
        COALESCE(matched_entity_ids, ''),
        ','
    )
) AS t(match_id)

WHERE trim(match_id) <> ''
""")

gt_count = con.execute("""
SELECT COUNT(*)
FROM gt_links
""").fetchone()[0]

print(f"Ground-truth links: {gt_count:,}")


# ============================================================
# 3. CREATE S1 -> S2/S3 ID TABLES
# ============================================================

print("\nPreparing source IDs...")

con.execute("""
CREATE OR REPLACE TEMP TABLE s1_ids AS
SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal
FROM train_s1
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s2_ids AS
SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal
FROM train_s2
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s3_ids AS
SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal
FROM train_s3
""")


# ============================================================
# 4. COMBINE S2 + S3
# ============================================================

con.execute("""
CREATE OR REPLACE TEMP TABLE all_candidates_source AS

SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal,
    'S2' AS source
FROM s2_ids

UNION ALL

SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal,
    'S3' AS source
FROM s3_ids
""")


# ============================================================
# 5. FUNCTION TO EVALUATE A BLOCKING RULE
# ============================================================

def evaluate_rule(rule_name, s1_key, candidate_key):

    print("\n" + "-" * 70)
    print(f"RULE: {rule_name}")
    print("-" * 70)

    start = time.time()

    query = f"""
    SELECT
        COUNT(*) AS retrieved_true_links
    FROM gt_links gt

    JOIN s1_ids s1
        ON s1.entity_id = gt.source1_entity_id

    JOIN all_candidates_source c
        ON c.entity_id = gt.matched_id

    WHERE
        s1.{s1_key} IS NOT NULL
        AND c.{candidate_key} IS NOT NULL
        AND s1.{s1_key} = c.{candidate_key}
    """

    retrieved = con.execute(query).fetchone()[0]

    recall = retrieved / gt_count if gt_count else 0

    elapsed = time.time() - start

    print(f"True links retrieved : {retrieved:,}")
    print(f"Recall               : {recall:.4%}")
    print(f"Time                 : {elapsed:.2f}s")

    return retrieved, recall


# ============================================================
# 6. EVALUATE INDIVIDUAL RULES
# ============================================================

results = []

rules = [
    (
        "EXACT NAME",
        "block_name_exact",
        "block_name_exact"
    ),
    (
        "EXACT ADDRESS",
        "block_address_exact",
        "block_address_exact"
    ),
    (
        "NAME PREFIX 5",
        "block_name_prefix5",
        "block_name_prefix5"
    ),
    (
        "ADDRESS PREFIX 8",
        "block_address_prefix8",
        "block_address_prefix8"
    ),
    (
        "POSTAL",
        "block_postal",
        "block_postal"
    )
]


for name, s1_key, candidate_key in rules:

    retrieved, recall = evaluate_rule(
        name,
        s1_key,
        candidate_key
    )

    results.append(
        (name, retrieved, recall)
    )


# ============================================================
# 7. EVALUATE COMBINED BLOCKING
# ============================================================

print("\n" + "=" * 70)
print("COMBINED BLOCKING")
print("=" * 70)

start = time.time()

combined_query = """
SELECT
    COUNT(*) AS retrieved_true_links
FROM gt_links gt

JOIN s1_ids s1
    ON s1.entity_id = gt.source1_entity_id

JOIN all_candidates_source c
    ON c.entity_id = gt.matched_id

WHERE

    (
        (
            s1.block_name_exact IS NOT NULL
            AND c.block_name_exact IS NOT NULL
            AND s1.block_name_exact = c.block_name_exact
        )

        OR

        (
            s1.block_address_exact IS NOT NULL
            AND c.block_address_exact IS NOT NULL
            AND s1.block_address_exact = c.block_address_exact
        )

        OR

        (
            s1.block_address_prefix8 IS NOT NULL
            AND c.block_address_prefix8 IS NOT NULL
            AND s1.block_address_prefix8 = c.block_address_prefix8
        )

        OR

        (
            s1.block_postal IS NOT NULL
            AND c.block_postal IS NOT NULL
            AND s1.block_postal = c.block_postal
        )
    )
"""

combined_retrieved = con.execute(
    combined_query
).fetchone()[0]

combined_recall = combined_retrieved / gt_count

elapsed = time.time() - start

print(f"\nTrue links retrieved : {combined_retrieved:,}")
print(f"Total true links     : {gt_count:,}")
print(f"Combined recall      : {combined_recall:.4%}")
print(f"Time                 : {elapsed:.2f}s")


# ============================================================
# 8. FINAL SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("BLOCKING RECALL SUMMARY")
print("=" * 70)

for name, retrieved, recall in results:
    print(
        f"{name:25} "
        f"{retrieved:>12,} "
        f"{recall:>10.4%}"
    )

print(
    f"{'COMBINED':25} "
    f"{combined_retrieved:>12,} "
    f"{combined_recall:>10.4%}"
)

print("\n" + "=" * 70)
print("PHASE 5 RECALL EVALUATION COMPLETE")
print("=" * 70)

con.close()