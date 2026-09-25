import duckdb
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 80)
print("PHASE 6: INVESTIGATING BASELINE MISSES & SELECTIVE INCREMENTAL KEYS")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)

con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

start = time.time()

# ---------------------------------------------------------------------
# 1. Isolate the 1,032,615 Ground-Truth Misses
# ---------------------------------------------------------------------
print("\n[1/3] Isolating true matches missed by the 86.4812% baseline...")

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

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_misses AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    CASE 
        WHEN s2.entity_id IS NOT NULL THEN 'S2'
        WHEN s3.entity_id IS NOT NULL THEN 'S3'
        ELSE 'UNKNOWN'
    END AS target_source,
    s1.country_norm AS country,
    s1.name_norm AS s1_name,
    COALESCE(s2.name_norm, s3.name_norm) AS cand_name,
    s1.address_norm AS s1_addr,
    COALESCE(s2.address_norm, s3.address_norm) AS cand_addr,
    s1.block_postal AS s1_postal,
    COALESCE(s2.block_postal, s3.block_postal) AS cand_postal,
    regexp_extract(s1.address_norm, '[0-9]+', 0) AS s1_num,
    regexp_extract(COALESCE(s2.address_norm, s3.address_norm), '[0-9]+', 0) AS cand_num
FROM gt_links gt
JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
WHERE NOT (
    (s2.entity_id IS NOT NULL AND (
        s1.block_name_exact = s2.block_name_exact OR
        s1.block_address_exact = s2.block_address_exact OR
        s1.block_name_prefix5 = s2.block_name_prefix5 OR
        s1.block_address_prefix8 = s2.block_address_prefix8
    ))
    OR
    (s3.entity_id IS NOT NULL AND (
        s1.block_name_exact = s3.block_name_exact OR
        s1.block_address_exact = s3.block_address_exact OR
        s1.block_name_prefix5 = s3.block_name_prefix5 OR
        s1.block_address_prefix8 = s3.block_address_prefix8
    ))
)
""")

miss_count = con.execute("SELECT COUNT(*) FROM gt_misses").fetchone()[0]
print(f"Total Missed Links: {miss_count:,} ({miss_count / 7638365:.4%})")

# ---------------------------------------------------------------------
# 2. Test Hypotheses on the Missed Links
# ---------------------------------------------------------------------
print("\n[2/3] Testing selective recovery rules on missed links...")

# Helper: extract second word of name
# Helper: extract postal code
# Helper: extract address number

hypotheses = con.execute("""
SELECT
    -- H1: Country + AddrNum + Same 2nd Word of Name (e.g. 'the spicewood', 'shri upasana')
    COUNT(CASE WHEN 
        s1_num <> '' AND s1_num = cand_num
        AND split_part(s1_name, ' ', 2) <> '' 
        AND split_part(s1_name, ' ', 2) = split_part(cand_name, ' ', 2)
        AND length(split_part(s1_name, ' ', 2)) >= 4
    THEN 1 END) AS h1_addrnum_word2,

    -- H2: Country + AddrNum + Same 2nd Word (where one starts with 'the' or 'shri' or 'dr')
    COUNT(CASE WHEN 
        s1_num <> '' AND s1_num = cand_num
        AND (
            split_part(s1_name, ' ', 1) = split_part(cand_name, ' ', 2) OR
            split_part(s1_name, ' ', 2) = split_part(cand_name, ' ', 1)
        )
        AND length(split_part(s1_name, ' ', 1)) >= 4
    THEN 1 END) AS h2_addrnum_cross_word,

    -- H3: Country + Postal + Same Address Number (inside same postal code, same street/door number)
    COUNT(CASE WHEN 
        s1_postal IS NOT NULL AND s1_postal = cand_postal
        AND s1_num <> '' AND s1_num = cand_num
    THEN 1 END) AS h3_postal_addrnum,

    -- H4: Country + Postal + Same 1st Word of Name (min length 4)
    COUNT(CASE WHEN 
        s1_postal IS NOT NULL AND s1_postal = cand_postal
        AND split_part(s1_name, ' ', 1) <> ''
        AND split_part(s1_name, ' ', 1) = split_part(cand_name, ' ', 1)
        AND length(split_part(s1_name, ' ', 1)) >= 4
    THEN 1 END) AS h4_postal_name1,

    -- H5: Country + Postal + Same 2nd Word of Name (min length 4)
    COUNT(CASE WHEN 
        s1_postal IS NOT NULL AND s1_postal = cand_postal
        AND split_part(s1_name, ' ', 2) <> ''
        AND split_part(s1_name, ' ', 2) = split_part(cand_name, ' ', 2)
        AND length(split_part(s1_name, ' ', 2)) >= 4
    THEN 1 END) AS h5_postal_name2,

    -- H6: Union of H1 + H2 + H3 + H4 + H5
    COUNT(CASE WHEN 
        (s1_num <> '' AND s1_num = cand_num AND split_part(s1_name, ' ', 2) <> '' AND split_part(s1_name, ' ', 2) = split_part(cand_name, ' ', 2) AND length(split_part(s1_name, ' ', 2)) >= 4)
        OR
        (s1_num <> '' AND s1_num = cand_num AND (split_part(s1_name, ' ', 1) = split_part(cand_name, ' ', 2) OR split_part(s1_name, ' ', 2) = split_part(cand_name, ' ', 1)) AND length(split_part(s1_name, ' ', 1)) >= 4)
        OR
        (s1_postal IS NOT NULL AND s1_postal = cand_postal AND s1_num <> '' AND s1_num = cand_num)
        OR
        (s1_postal IS NOT NULL AND s1_postal = cand_postal AND split_part(s1_name, ' ', 1) <> '' AND split_part(s1_name, ' ', 1) = split_part(cand_name, ' ', 1) AND length(split_part(s1_name, ' ', 1)) >= 4)
        OR
        (s1_postal IS NOT NULL AND s1_postal = cand_postal AND split_part(s1_name, ' ', 2) <> '' AND split_part(s1_name, ' ', 2) = split_part(cand_name, ' ', 2) AND length(split_part(s1_name, ' ', 2)) >= 4)
    THEN 1 END) AS h_union
FROM gt_misses
""").fetchone()

h1, h2, h3, h4, h5, h_union = hypotheses

print(f"H1: Country + AddrNum + Word2 Equal           : {h1:,} new links ({h1/7638365:+.4%} over baseline)")
print(f"H2: Country + AddrNum + Cross-Word (w1=w2)    : {h2:,} new links ({h2/7638365:+.4%} over baseline)")
print(f"H3: Country + Postal + AddrNum Equal          : {h3:,} new links ({h3/7638365:+.4%} over baseline)")
print(f"H4: Country + Postal + Word1 Equal            : {h4:,} new links ({h4/7638365:+.4%} over baseline)")
print(f"H5: Country + Postal + Word2 Equal            : {h5:,} new links ({h5/7638365:+.4%} over baseline)")
print("-" * 70)
print(f"COMBINED INCREMENTAL RECOVERY (H1..H5)        : {h_union:,} new links ({h_union/7638365:+.4%} over baseline)")
print(f"New Potential Total Recall                    : {(6605750 + h_union)/7638365:.4%}")

con.close()
