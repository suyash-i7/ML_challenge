import duckdb
import time

DB = "work/entity_resolution.duckdb"

con = duckdb.connect(DB)

con.execute("SET threads=1")
con.execute("SET memory_limit='3GB'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET temp_directory='work/duckdb_tmp'")

print("=" * 70)
print("PHASE 6 — EXPERIMENT 2")
print("TOKEN-BASED NAME BLOCKING")
print("=" * 70)

# ------------------------------------------------------------
# Ground truth
# ------------------------------------------------------------

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_links AS
SELECT
    source1_entity_id AS s1_id,
    TRIM(match_id) AS candidate_id
FROM (
    SELECT
        source1_entity_id,
        UNNEST(string_split(matched_entity_ids, ',')) AS match_id
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
SELECT COUNT(*) FROM gt_links
""").fetchone()[0]

print(f"\nGround-truth links: {total_gt:,}")


# ------------------------------------------------------------
# Create token tables
# Ignore very short tokens.
# Ignore common legal suffixes.
# ------------------------------------------------------------

print("\nPreparing name tokens...")

con.execute("""
CREATE OR REPLACE TEMP TABLE s1_tokens AS
SELECT DISTINCT
    entity_id AS s1_id,
    UNNEST(string_split(name_norm, ' ')) AS token
FROM train_s1
WHERE name_norm IS NOT NULL
  AND name_norm <> ''
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s2_tokens AS
SELECT DISTINCT
    entity_id AS candidate_id,
    UNNEST(string_split(name_norm, ' ')) AS token
FROM train_s2
WHERE name_norm IS NOT NULL
  AND name_norm <> ''
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s3_tokens AS
SELECT DISTINCT
    entity_id AS candidate_id,
    UNNEST(string_split(name_norm, ' ')) AS token
FROM train_s3
WHERE name_norm IS NOT NULL
  AND name_norm <> ''
""")


# ------------------------------------------------------------
# Evaluate TRUE pairs only
#
# A pair is recovered if they share at least one
# significant name token.
# ------------------------------------------------------------

def evaluate(name, source_table):

    print("\n" + "-" * 70)
    print(name)
    print("-" * 70)

    start = time.time()

    recovered = con.execute(f"""
        SELECT COUNT(*)

        FROM gt_links gt

        JOIN train_s1 s1
          ON gt.s1_id = s1.entity_id

        JOIN {source_table} s
          ON gt.candidate_id = s.entity_id

        WHERE EXISTS (
            SELECT 1
            FROM UNNEST(string_split(s1.name_norm, ' ')) a(token1)
            JOIN UNNEST(string_split(s.name_norm, ' ')) b(token2)
              ON a.token1 = b.token2
            WHERE LENGTH(a.token1) >= 4
              AND a.token1 NOT IN (
                  'private',
                  'limited',
                  'ltd',
                  'pvt',
                  'llc',
                  'inc',
                  'corp',
                  'corporation',
                  'company',
                  'co',
                  'llp'
              )
        )
    """).fetchone()[0]

    recall = recovered / total_gt

    print(f"Recovered : {recovered:,}")
    print(f"Missed    : {total_gt - recovered:,}")
    print(f"Recall    : {recall:.4%}")
    print(f"Time      : {time.time() - start:.2f}s")

    return recovered


evaluate("TOKEN NAME — S2", "train_s2")
evaluate("TOKEN NAME — S3", "train_s3")


# ------------------------------------------------------------
# Combined:
# baseline + address prefix8 + token name
# ------------------------------------------------------------

print("\n" + "-" * 70)
print("BASELINE + ADDRESS PREFIX 8 + TOKEN NAME")
print("-" * 70)

start = time.time()

recovered = con.execute("""
SELECT COUNT(*)

FROM gt_links gt

JOIN train_s1 s1
  ON gt.s1_id = s1.entity_id

LEFT JOIN train_s2 s2
  ON gt.candidate_id = s2.entity_id

LEFT JOIN train_s3 s3
  ON gt.candidate_id = s3.entity_id

WHERE

(
    s2.entity_id IS NOT NULL
    AND (
        s1.block_name_exact = s2.block_name_exact
        OR s1.block_address_exact = s2.block_address_exact
        OR s1.block_name_prefix5 = s2.block_name_prefix5
        OR s1.block_address_prefix8 = s2.block_address_prefix8

        OR EXISTS (
            SELECT 1
            FROM UNNEST(string_split(s1.name_norm, ' ')) a(token1)
            JOIN UNNEST(string_split(s2.name_norm, ' ')) b(token2)
              ON a.token1 = b.token2
            WHERE LENGTH(a.token1) >= 4
              AND a.token1 NOT IN (
                  'private','limited','ltd','pvt','llc',
                  'inc','corp','corporation','company','co','llp'
              )
        )
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

        OR EXISTS (
            SELECT 1
            FROM UNNEST(string_split(s1.name_norm, ' ')) a(token1)
            JOIN UNNEST(string_split(s3.name_norm, ' ')) b(token2)
              ON a.token1 = b.token2
            WHERE LENGTH(a.token1) >= 4
              AND a.token1 NOT IN (
                  'private','limited','ltd','pvt','llc',
                  'inc','corp','corporation','company','co','llp'
              )
        )
    )
)
""").fetchone()[0]

recall = recovered / total_gt

print(f"Recovered : {recovered:,}")
print(f"Missed    : {total_gt - recovered:,}")
print(f"Recall    : {recall:.4%}")
print(f"Time      : {time.time() - start:.2f}s")

print("\n" + "=" * 70)
print("PHASE 6 EXPERIMENT 2 COMPLETE")
print("=" * 70)

con.close()