import duckdb
import time

print("=" * 80)
print("TESTING LONGER PREFIXES: NAME & ADDRESS")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_links AS
SELECT
    source1_entity_id AS s1_id,
    TRIM(match_id) AS candidate_id
FROM (
    SELECT
        source1_entity_id,
        UNNEST(string_split(COALESCE(matched_entity_ids, ''), ',')) AS match_id
    FROM ground_truth
    WHERE matched_entity_ids IS NOT NULL AND matched_entity_ids <> ''
)
WHERE TRIM(match_id) <> ''
""")

# Compare Name Prefix lengths: 6, 7, 8
for n in [6, 7, 8]:
    start = time.time()
    # Candidate volume
    vol = con.execute(f"""
        WITH s1_c AS (
            SELECT country_norm || '|' || substr(name_norm, 1, {n}) AS k, COUNT(*) AS c
            FROM train_s1
            WHERE length(name_norm) >= {n}
            GROUP BY k
        ),
        s2_c AS (
            SELECT country_norm || '|' || substr(name_norm, 1, {n}) AS k, COUNT(*) AS c
            FROM train_s2
            WHERE length(name_norm) >= {n}
            GROUP BY k
        ),
        s3_c AS (
            SELECT country_norm || '|' || substr(name_norm, 1, {n}) AS k, COUNT(*) AS c
            FROM train_s3
            WHERE length(name_norm) >= {n}
            GROUP BY k
        )
        SELECT
            COALESCE(SUM(s1_c.c * s2_c.c), 0) AS s2_pairs,
            COALESCE(SUM(s1_c.c * s3_c.c), 0) AS s3_pairs,
            COALESCE(SUM(s1_c.c * (s2_c.c + s3_c.c)), 0) AS tot_pairs
        FROM s1_c
        LEFT JOIN s2_c ON s1_c.k = s2_c.k
        LEFT JOIN s3_c ON s1_c.k = s3_c.k
    """).fetchone()

    # Recall on ground truth
    rec = con.execute(f"""
        SELECT COUNT(*)
        FROM gt_links gt
        JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
        LEFT JOIN (
            SELECT entity_id, country_norm, name_norm FROM train_s2
            UNION ALL
            SELECT entity_id, country_norm, name_norm FROM train_s3
        ) c ON gt.candidate_id = c.entity_id
        WHERE s1.country_norm = c.country_norm
          AND length(s1.name_norm) >= {n}
          AND substr(s1.name_norm, 1, {n}) = substr(c.name_norm, 1, {n})
    """).fetchone()[0]

    print(f"Country + Name Prefix {n}:")
    print(f"  Candidate Pairs : {vol[2]:,} (S2: {vol[0]:,}, S3: {vol[1]:,})")
    print(f"  GT Recall       : {rec:,} / 7,638,365 ({rec / 7638365:.4%})")
    print(f"  Time            : {time.time() - start:.2f}s\n")

# Compare Address Prefix lengths: 10, 12, 14
for a in [10, 12, 14]:
    start = time.time()
    vol = con.execute(f"""
        WITH s1_c AS (
            SELECT country_norm || '|' || substr(address_norm, 1, {a}) AS k, COUNT(*) AS c
            FROM train_s1
            WHERE length(address_norm) >= {a}
            GROUP BY k
        ),
        s2_c AS (
            SELECT country_norm || '|' || substr(address_norm, 1, {a}) AS k, COUNT(*) AS c
            FROM train_s2
            WHERE length(address_norm) >= {a}
            GROUP BY k
        ),
        s3_c AS (
            SELECT country_norm || '|' || substr(address_norm, 1, {a}) AS k, COUNT(*) AS c
            FROM train_s3
            WHERE length(address_norm) >= {a}
            GROUP BY k
        )
        SELECT
            COALESCE(SUM(s1_c.c * s2_c.c), 0) AS s2_pairs,
            COALESCE(SUM(s1_c.c * s3_c.c), 0) AS s3_pairs,
            COALESCE(SUM(s1_c.c * (s2_c.c + s3_c.c)), 0) AS tot_pairs
        FROM s1_c
        LEFT JOIN s2_c ON s1_c.k = s2_c.k
        LEFT JOIN s3_c ON s1_c.k = s3_c.k
    """).fetchone()

    rec = con.execute(f"""
        SELECT COUNT(*)
        FROM gt_links gt
        JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
        LEFT JOIN (
            SELECT entity_id, country_norm, address_norm FROM train_s2
            UNION ALL
            SELECT entity_id, country_norm, address_norm FROM train_s3
        ) c ON gt.candidate_id = c.entity_id
        WHERE s1.country_norm = c.country_norm
          AND length(s1.address_norm) >= {a}
          AND substr(s1.address_norm, 1, {a}) = substr(c.address_norm, 1, {a})
    """).fetchone()[0]

    print(f"Country + Address Prefix {a}:")
    print(f"  Candidate Pairs : {vol[2]:,} (S2: {vol[0]:,}, S3: {vol[1]:,})")
    print(f"  GT Recall       : {rec:,} / 7,638,365 ({rec / 7638365:.4%})")
    print(f"  Time            : {time.time() - start:.2f}s\n")

con.close()
