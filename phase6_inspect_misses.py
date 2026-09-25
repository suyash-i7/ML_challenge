import duckdb
import sys

sys.stdout.reconfigure(encoding='utf-8')

con = duckdb.connect("work/entity_resolution.duckdb")
con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='4GB'")

print("=" * 80)
print("INSPECTING MISSED GROUND-TRUTH PAIRS")
print("=" * 80)

# Extract 20 missed pairs
missed = con.execute("""
WITH gt_links AS (
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
),
tagged AS (
    SELECT
        gt.s1_id,
        gt.candidate_id,
        s1.name_norm AS s1_name,
        COALESCE(s2.name_norm, s3.name_norm) AS cand_name,
        s1.address_norm AS s1_addr,
        COALESCE(s2.address_norm, s3.address_norm) AS cand_addr,
        s1.country_norm AS country,
        -- flags
        (s1.block_name_exact = COALESCE(s2.block_name_exact, s3.block_name_exact)) AS exact_name_match,
        (s1.block_address_exact = COALESCE(s2.block_address_exact, s3.block_address_exact)) AS exact_addr_match,
        (
            s1.country_norm = COALESCE(s2.country_norm, s3.country_norm)
            AND regexp_extract(s1.address_norm, '[0-9]+', 0) <> ''
            AND regexp_extract(s1.address_norm, '[0-9]+', 0) = regexp_extract(COALESCE(s2.address_norm, s3.address_norm), '[0-9]+', 0)
            AND length(s1.name_norm) >= 5
            AND substr(s1.name_norm, 1, 5) = substr(COALESCE(s2.name_norm, s3.name_norm), 1, 5)
        ) AS addrnum_name5_match,
        (s1.block_name_prefix5 = COALESCE(s2.block_name_prefix5, s3.block_name_prefix5)) AS name5_match,
        (s1.block_address_prefix8 = COALESCE(s2.block_address_prefix8, s3.block_address_prefix8)) AS addr8_match
    FROM gt_links gt
    JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
    LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
    LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
)
SELECT
    s1_id,
    candidate_id,
    country,
    s1_name,
    cand_name,
    s1_addr,
    cand_addr,
    name5_match,
    addr8_match
FROM tagged
WHERE NOT exact_name_match
  AND NOT exact_addr_match
  AND NOT addrnum_name5_match
LIMIT 20
""").fetchall()

for i, row in enumerate(missed, 1):
    s1_id, cand_id, country, s1_name, cand_name, s1_addr, cand_addr, name5, addr8 = row
    print(f"\n[{i}] S1: {s1_id} -> Cand: {cand_id} ({country})")
    print(f"  S1 Name  : {s1_name}")
    print(f"  Cand Name: {cand_name}")
    print(f"  S1 Addr  : {s1_addr}")
    print(f"  Cand Addr: {cand_addr}")
    print(f"  Name5 match? {name5} | Addr8 match? {addr8}")

con.close()
