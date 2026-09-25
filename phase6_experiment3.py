import duckdb
import time

DB = "work/entity_resolution.duckdb"

con = duckdb.connect(DB)

con.execute("SET threads=1")
con.execute("SET memory_limit='3GB'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET temp_directory='work/duckdb_tmp'")

print("=" * 70)
print("PHASE 6 — EXPERIMENT 3")
print("RARE TOKEN NAME BLOCKING")
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
# Build token frequency across S2 + S3
# ------------------------------------------------------------

print("\nBuilding token frequencies...")

con.execute("""
CREATE OR REPLACE TEMP TABLE token_frequency AS

SELECT
    token,
    COUNT(DISTINCT candidate_id) AS frequency

FROM (

    SELECT
        entity_id AS candidate_id,
        UNNEST(string_split(name_norm, ' ')) AS token
    FROM train_s2
    WHERE name_norm IS NOT NULL
      AND name_norm <> ''

    UNION

    SELECT
        entity_id AS candidate_id,
        UNNEST(string_split(name_norm, ' ')) AS token
    FROM train_s3
    WHERE name_norm IS NOT NULL
      AND name_norm <> ''
)

WHERE LENGTH(token) >= 4

GROUP BY token
""")

print("\nToken frequency table created.")


# ------------------------------------------------------------
# Show frequency distribution
# ------------------------------------------------------------

print("\nToken frequency examples:")

rows = con.execute("""
SELECT token, frequency
FROM token_frequency
ORDER BY frequency ASC
LIMIT 20
""").fetchall()

for token, freq in rows:
    print(f"{token:30s} {freq:,}")


# ------------------------------------------------------------
# Evaluate different rarity thresholds
# ------------------------------------------------------------

def evaluate(threshold):

    print("\n" + "-" * 70)
    print(f"RARE TOKEN THRESHOLD <= {threshold:,}")
    print("-" * 70)

    start = time.time()

    recovered = con.execute(f"""
        SELECT COUNT(*)

        FROM gt_links gt

        JOIN train_s1 s1
          ON gt.s1_id = s1.entity_id

        JOIN (
            SELECT entity_id, name_norm
            FROM train_s2

            UNION ALL

            SELECT entity_id, name_norm
            FROM train_s3
        ) s
          ON gt.candidate_id = s.entity_id

        WHERE EXISTS (

            SELECT 1

            FROM UNNEST(string_split(s1.name_norm, ' ')) a(token)

            JOIN token_frequency tf
              ON tf.token = a.token

            JOIN UNNEST(string_split(s.name_norm, ' ')) b(token2)
              ON a.token = b.token2

            WHERE LENGTH(a.token) >= 4
              AND tf.frequency <= {threshold}

              AND a.token NOT IN (
                  'private',
                  'limited',
                  'ltd',
                  'pvt',
                  'llc',
                  'inc',
                  'corp',
                  'corporation',
                  'company',
                  'store',
                  'market',
                  'restaurant',
                  'hotel',
                  'medical',
                  'hospital'
              )
        )
    """).fetchone()[0]

    recall = recovered / total_gt

    print(f"Recovered : {recovered:,}")
    print(f"Missed    : {total_gt - recovered:,}")
    print(f"Recall    : {recall:.4%}")
    print(f"Time      : {time.time() - start:.2f}s")

    return recovered


# ------------------------------------------------------------
# Test rarity levels
# ------------------------------------------------------------

for threshold in [10, 50, 100, 500, 1000]:

    evaluate(threshold)


print("\n" + "=" * 70)
print("PHASE 6 EXPERIMENT 3 COMPLETE")
print("=" * 70)

con.close()