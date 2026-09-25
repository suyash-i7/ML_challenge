import duckdb
import time

DB = "work/entity_resolution.duckdb"

con = duckdb.connect(DB)

con.execute("SET threads=1")
con.execute("SET memory_limit='3GB'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET temp_directory='work/duckdb_tmp'")

print("=" * 70)
print("PHASE 6 — EXPERIMENT 1 — MEMORY SAFE")
print("BASELINE + ADDRESS PREFIX 8")
print("=" * 70)

# ------------------------------------------------------------
# Create ground-truth link table inside DuckDB
# ------------------------------------------------------------

print("\nPreparing ground truth...")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_links AS

SELECT
    source1_entity_id AS s1_id,
    TRIM(match_id) AS candidate_id

FROM (
    SELECT
        source1_entity_id,
        UNNEST(
            string_split(matched_entity_ids, ',')
        ) AS match_id

    FROM read_csv_auto(
        'dataset/train/train_ground_truth.tsv',
        delim='\\t',
        header=true
    )

    WHERE matched_entity_ids IS NOT NULL
      AND matched_entity_ids <> ''
)

WHERE TRIM(match_id) <> ''
""")

total_gt = con.execute("""
SELECT COUNT(*)
FROM gt_links
""").fetchone()[0]

print(f"Ground-truth links: {total_gt:,}")


# ------------------------------------------------------------
# Function: evaluate whether each TRUE link is recovered
#
# IMPORTANT:
# We evaluate only ground-truth pairs.
# We do NOT generate the complete candidate universe.
# ------------------------------------------------------------

def evaluate(name, condition):

    print("\n" + "-" * 70)
    print(name)
    print("-" * 70)

    start = time.time()

    recovered = con.execute(f"""
        SELECT COUNT(*)

        FROM gt_links gt

        JOIN train_s1 s1
          ON gt.s1_id = s1.entity_id

        LEFT JOIN train_s2 s2
          ON gt.candidate_id = s2.entity_id

        LEFT JOIN train_s3 s3
          ON gt.candidate_id = s3.entity_id

        WHERE {condition}
    """).fetchone()[0]

    recall = recovered / total_gt

    elapsed = time.time() - start

    missed = total_gt - recovered

    print(f"Recovered : {recovered:,}")
    print(f"Missed    : {missed:,}")
    print(f"Recall    : {recall:.4%}")
    print(f"Time      : {elapsed:.2f}s")

    return recovered, recall


# ------------------------------------------------------------
# Baseline
# ------------------------------------------------------------

baseline = """
(
    (
        s2.entity_id IS NOT NULL
        AND (
            s1.block_name_exact = s2.block_name_exact
            OR s1.block_address_exact = s2.block_address_exact
            OR s1.block_name_prefix5 = s2.block_name_prefix5
        )
    )

    OR

    (
        s3.entity_id IS NOT NULL
        AND (
            s1.block_name_exact = s3.block_name_exact
            OR s1.block_address_exact = s3.block_address_exact
            OR s1.block_name_prefix5 = s3.block_name_prefix5
        )
    )
)
"""

evaluate(
    "BASELINE",
    baseline
)


# ------------------------------------------------------------
# Baseline + address prefix 8
# ------------------------------------------------------------

expanded = """
(
    (
        s2.entity_id IS NOT NULL
        AND (
            s1.block_name_exact = s2.block_name_exact
            OR s1.block_address_exact = s2.block_address_exact
            OR s1.block_name_prefix5 = s2.block_name_prefix5
            OR s1.block_address_prefix8 = s2.block_address_prefix8
        )
    )

    OR

    (
        s3.entity_id IS NOT NULL
        AND (
            s1.block_name_exact = s3.block_name_exact
            OR s1.block_address_exact = s3.block_address_exact
            OR s1.block_name_prefix5 = s3.block_name_prefix5
            OR s1.block_address_prefix8 = s3.block_address_prefix8
        )
    )
)
"""

evaluate(
    "BASELINE + ADDRESS PREFIX 8",
    expanded
)


print("\n" + "=" * 70)
print("PHASE 6 EXPERIMENT 1 COMPLETE")
print("=" * 70)

con.close()