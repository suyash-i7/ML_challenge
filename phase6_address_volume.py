import duckdb
import os

DB = "work/entity_resolution.duckdb"

con = duckdb.connect(DB)

con.execute("PRAGMA threads=2")
con.execute("PRAGMA memory_limit='4GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

print("=" * 70)
print("ADDRESS NUMBER BLOCKING - CANDIDATE VOLUME")
print("=" * 70)

# ---------------------------------------------------------
# Build address-number blocking tables
# Key = country + first numeric component of address
# ---------------------------------------------------------

con.execute("""
CREATE OR REPLACE TEMP TABLE s1_addr AS
SELECT
    entity_id,
    country,
    regexp_extract(address_norm, '\\\\d+', 0) AS addr_num
FROM train_s1
WHERE address_norm IS NOT NULL
  AND regexp_extract(address_norm, '\\\\d+', 0) <> ''
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s2_addr AS
SELECT
    entity_id,
    country,
    regexp_extract(address_norm, '\\\\d+', 0) AS addr_num
FROM train_s2
WHERE address_norm IS NOT NULL
  AND regexp_extract(address_norm, '\\\\d+', 0) <> ''
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s3_addr AS
SELECT
    entity_id,
    country,
    regexp_extract(address_norm, '\\\\d+', 0) AS addr_num
FROM train_s3
WHERE address_norm IS NOT NULL
  AND regexp_extract(address_norm, '\\\\d+', 0) <> ''
""")

print("Address keys created.")

# ---------------------------------------------------------
# Candidate counts for each S1
# ---------------------------------------------------------

con.execute("""
CREATE OR REPLACE TEMP TABLE candidate_counts AS

SELECT
    s1.entity_id,
    COUNT(*) AS candidate_count
FROM s1_addr s1
JOIN s2_addr s2
    ON s1.country = s2.country
   AND s1.addr_num = s2.addr_num
GROUP BY s1.entity_id

UNION ALL

SELECT
    s1.entity_id,
    COUNT(*) AS candidate_count
FROM s1_addr s1
JOIN s3_addr s3
    ON s1.country = s3.country
   AND s1.addr_num = s3.addr_num
GROUP BY s1.entity_id
""")

# Combine S2 + S3 counts per S1
con.execute("""
CREATE OR REPLACE TEMP TABLE total_counts AS
SELECT
    s1.entity_id,
    COALESCE(SUM(c.candidate_count), 0) AS candidate_count
FROM train_s1 s1
LEFT JOIN candidate_counts c
    ON s1.entity_id = c.entity_id
GROUP BY s1.entity_id
""")

# ---------------------------------------------------------
# Overall statistics
# ---------------------------------------------------------

stats = con.execute("""
SELECT
    COUNT(*) AS s1_entities,

    SUM(candidate_count) AS total_candidate_pairs,

    AVG(candidate_count) AS avg_candidates,

    median(candidate_count) AS median_candidates,

    quantile_cont(candidate_count, 0.90) AS p90,

    quantile_cont(candidate_count, 0.95) AS p95,

    quantile_cont(candidate_count, 0.99) AS p99,

    MAX(candidate_count) AS max_candidates,

    SUM(CASE WHEN candidate_count = 0 THEN 1 ELSE 0 END) AS zero_candidates,

    SUM(CASE WHEN candidate_count > 100 THEN 1 ELSE 0 END) AS gt_100,

    SUM(CASE WHEN candidate_count > 1000 THEN 1 ELSE 0 END) AS gt_1000,

    SUM(CASE WHEN candidate_count > 10000 THEN 1 ELSE 0 END) AS gt_10000,

    SUM(CASE WHEN candidate_count > 100000 THEN 1 ELSE 0 END) AS gt_100000

FROM total_counts
""").fetchone()

columns = [
    "S1 entities",
    "Total candidate pairs",
    "Average candidates/S1",
    "Median candidates/S1",
    "P90",
    "P95",
    "P99",
    "Maximum candidates/S1",
    "S1 with zero candidates",
    "S1 with >100 candidates",
    "S1 with >1,000 candidates",
    "S1 with >10,000 candidates",
    "S1 with >100,000 candidates",
]

print("\nRESULTS")
print("-" * 70)

for name, value in zip(columns, stats):
    print(f"{name:35} : {value}")

# ---------------------------------------------------------
# Largest blocks
# ---------------------------------------------------------

print("\nTOP 20 LARGEST S1 CANDIDATE SETS")
print("-" * 70)

rows = con.execute("""
SELECT
    entity_id,
    candidate_count
FROM total_counts
ORDER BY candidate_count DESC
LIMIT 20
""").fetchall()

for entity_id, count in rows:
    print(f"{entity_id:20} {count:,}")

# ---------------------------------------------------------
# Block-size distribution
# ---------------------------------------------------------

print("\nDISTRIBUTION")
print("-" * 70)

rows = con.execute("""
SELECT
    CASE
        WHEN candidate_count = 0 THEN '0'
        WHEN candidate_count <= 10 THEN '1-10'
        WHEN candidate_count <= 100 THEN '11-100'
        WHEN candidate_count <= 1000 THEN '101-1K'
        WHEN candidate_count <= 10000 THEN '1K-10K'
        WHEN candidate_count <= 100000 THEN '10K-100K'
        ELSE '>100K'
    END AS bucket,
    COUNT(*) AS s1_count
FROM total_counts
GROUP BY 1
ORDER BY
    CASE bucket
        WHEN '0' THEN 1
        WHEN '1-10' THEN 2
        WHEN '11-100' THEN 3
        WHEN '101-1K' THEN 4
        WHEN '1K-10K' THEN 5
        WHEN '10K-100K' THEN 6
        ELSE 7
    END
""").fetchall()

for bucket, count in rows:
    print(f"{bucket:12} : {count:,}")

print("\nDONE.")