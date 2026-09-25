import duckdb

con = duckdb.connect("work/entity_resolution.duckdb")

con.execute("SET threads=1")
con.execute("SET memory_limit='3GB'")
con.execute("SET preserve_insertion_order=false")
con.execute("SET temp_directory='work/duckdb_tmp'")

print("=" * 70)
print("PHASE 6 — ADDRESS DIAGNOSTIC")
print("=" * 70)

queries = {

"ADDRESS NUMBER": """
SELECT COUNT(*)
FROM gt_links gt
JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
WHERE
(
 s2.entity_id IS NOT NULL
 AND regexp_extract(s1.address_norm, '\\\\d+', 0)
     =
     regexp_extract(s2.address_norm, '\\\\d+', 0)
)
OR
(
 s3.entity_id IS NOT NULL
 AND regexp_extract(s1.address_norm, '\\\\d+', 0)
     =
     regexp_extract(s3.address_norm, '\\\\d+', 0)
)
""",

"POSTAL": """
SELECT COUNT(*)
FROM gt_links gt
JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
WHERE
(
 s2.entity_id IS NOT NULL
 AND s1.block_postal = s2.block_postal
 AND s1.block_postal IS NOT NULL
 AND s1.block_postal <> ''
)
OR
(
 s3.entity_id IS NOT NULL
 AND s1.block_postal = s3.block_postal
 AND s1.block_postal IS NOT NULL
 AND s1.block_postal <> ''
)
"""
}

# Recreate ground truth
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

total = con.execute("SELECT COUNT(*) FROM gt_links").fetchone()[0]

print(f"\nGround-truth links: {total:,}")

for name, sql in queries.items():
    result = con.execute(sql).fetchone()[0]
    print("\n" + "-" * 60)
    print(name)
    print(f"Recovered : {result:,}")
    print(f"Recall    : {result / total:.4%}")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)

con.close()