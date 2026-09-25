from pathlib import Path
import duckdb
import time

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"

con = duckdb.connect(str(WORK / "entity_resolution.duckdb"))

# Keep DuckDB from consuming all available RAM
con.execute("PRAGMA threads=2")
con.execute("SET memory_limit='4GB'")
con.execute(
    f"SET temp_directory='{(WORK / 'duckdb_tmp').as_posix()}'"
)

print("=" * 70)
print("PHASE 5 — MEMORY-SAFE BLOCKING RECALL")
print("=" * 70)


# ============================================================
# GROUND TRUTH
# ============================================================

GT = ROOT / "dataset" / "train" / "train_ground_truth.tsv"

con.execute(f"""
CREATE OR REPLACE TEMP TABLE gt_links AS

SELECT
    source1_entity_id,
    trim(match_id) AS matched_id

FROM read_csv_auto(
    '{GT.as_posix()}',
    delim='\\t',
    header=true
),
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

print(f"\nGround-truth links: {gt_count:,}")


# ============================================================
# PREPARE S1
# ============================================================

con.execute("""
CREATE OR REPLACE TEMP TABLE s1 AS
SELECT
    entity_id,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal
FROM train_s1
""")


# ============================================================
# PREPARE S2 + S3
# ============================================================

con.execute("""
CREATE OR REPLACE TEMP TABLE candidates AS

SELECT
    entity_id,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal
FROM train_s2

UNION ALL

SELECT
    entity_id,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal
FROM train_s3
""")


# ============================================================
# CREATE GROUND-TRUTH LOOKUP
# ============================================================

con.execute("""
CREATE OR REPLACE TEMP TABLE gt AS
SELECT
    gt.source1_entity_id,
    gt.matched_id,
    s1.block_name_exact,
    s1.block_address_exact,
    s1.block_name_prefix5,
    s1.block_address_prefix8,
    s1.block_postal
FROM gt_links gt
JOIN s1
    ON s1.entity_id = gt.source1_entity_id
""")


# ============================================================
# SAFE RULE EVALUATION
# ============================================================

def evaluate(rule_name, condition):

    print("\n" + "-" * 70)
    print(rule_name)
    print("-" * 70)

    start = time.time()

    query = f"""
    SELECT COUNT(*)
    FROM gt g
    JOIN candidates c
        ON c.entity_id = g.matched_id
    WHERE {condition}
    """

    count = con.execute(query).fetchone()[0]

    recall = count / gt_count

    print(f"Retrieved : {count:,}")
    print(f"Recall    : {recall:.4%}")
    print(f"Time      : {time.time() - start:.2f}s")

    return count


# ============================================================
# INDIVIDUAL RULES
# ============================================================

evaluate(
    "EXACT NAME",
    """
    g.block_name_exact IS NOT NULL
    AND c.block_name_exact = g.block_name_exact
    """
)

evaluate(
    "EXACT ADDRESS",
    """
    g.block_address_exact IS NOT NULL
    AND c.block_address_exact = g.block_address_exact
    """
)

evaluate(
    "NAME PREFIX 5",
    """
    g.block_name_prefix5 IS NOT NULL
    AND c.block_name_prefix5 = g.block_name_prefix5
    """
)


# ============================================================
# COMBINED SAFE RULE
# ============================================================

print("\n" + "=" * 70)
print("COMBINED BLOCKING")
print("=" * 70)

start = time.time()

combined = con.execute("""
SELECT COUNT(*)
FROM gt g
JOIN candidates c
    ON c.entity_id = g.matched_id
WHERE

    (
        g.block_name_exact IS NOT NULL
        AND c.block_name_exact = g.block_name_exact
    )

    OR

    (
        g.block_address_exact IS NOT NULL
        AND c.block_address_exact = g.block_address_exact
    )

    OR

    (
        g.block_name_prefix5 IS NOT NULL
        AND c.block_name_prefix5 = g.block_name_prefix5
    )
""").fetchone()[0]

print(f"Retrieved : {combined:,}")
print(f"Recall    : {combined / gt_count:.4%}")
print(f"Time      : {time.time() - start:.2f}s")


# ============================================================
# SAFE ADDRESS PREFIX EVALUATION
# ============================================================

print("\n" + "=" * 70)
print("ADDRESS PREFIX — SAFE TEST")
print("=" * 70)

start = time.time()

# Instead of joining every address-prefix block,
# only test true GT pairs.

address_prefix_hits = con.execute("""
SELECT COUNT(*)
FROM gt g
JOIN candidates c
    ON c.entity_id = g.matched_id
WHERE
    g.block_address_prefix8 IS NOT NULL
    AND c.block_address_prefix8 IS NOT NULL
    AND g.block_address_prefix8 = c.block_address_prefix8
""").fetchone()[0]

print(f"Retrieved : {address_prefix_hits:,}")
print(f"Recall    : {address_prefix_hits / gt_count:.4%}")
print(f"Time      : {time.time() - start:.2f}s")


# ============================================================
# POSTAL — SAFE TEST
# ============================================================

print("\n" + "=" * 70)
print("POSTAL — SAFE TEST")
print("=" * 70)

start = time.time()

postal_hits = con.execute("""
SELECT COUNT(*)
FROM gt g
JOIN candidates c
    ON c.entity_id = g.matched_id
WHERE
    g.block_postal IS NOT NULL
    AND c.block_postal IS NOT NULL
    AND g.block_postal = c.block_postal
""").fetchone()[0]

print(f"Retrieved : {postal_hits:,}")
print(f"Recall    : {postal_hits / gt_count:.4%}")
print(f"Time      : {time.time() - start:.2f}s")


print("\n" + "=" * 70)
print("PHASE 5 COMPLETE")
print("=" * 70)

con.close()