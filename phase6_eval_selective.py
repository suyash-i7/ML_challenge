import duckdb
import time

print("=" * 80)
print("EVALUATING SELECTIVE BLOCKING ENSEMBLE")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

start = time.time()

# Ground truth links
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
CREATE OR REPLACE TEMP TABLE cand_all AS
SELECT entity_id, country_norm, name_norm, address_norm, block_name_exact, block_address_exact, block_postal FROM train_s2
UNION ALL
SELECT entity_id, country_norm, name_norm, address_norm, block_name_exact, block_address_exact, block_postal FROM train_s3
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_eval AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    -- Rule 1: Exact Name
    (s1.block_name_exact = cand.block_name_exact AND s1.block_name_exact IS NOT NULL) AS r1_exact_name,
    -- Rule 2: Exact Address
    (s1.block_address_exact = cand.block_address_exact AND s1.block_address_exact IS NOT NULL) AS r2_exact_addr,
    -- Rule 3: Country + Addr_Num + Name_Prefix5
    (
        s1.country_norm = cand.country_norm
        AND regexp_extract(s1.address_norm, '[0-9]+', 0) <> ''
        AND regexp_extract(s1.address_norm, '[0-9]+', 0) = regexp_extract(cand.address_norm, '[0-9]+', 0)
        AND length(s1.name_norm) >= 5
        AND substr(s1.name_norm, 1, 5) = substr(cand.name_norm, 1, 5)
    ) AS r3_addrnum_name5,
    -- Rule 4: Country + Postal + Name_Prefix4
    (
        s1.block_postal IS NOT NULL
        AND s1.block_postal = cand.block_postal
        AND length(s1.name_norm) >= 4
        AND substr(s1.name_norm, 1, 4) = substr(cand.name_norm, 1, 4)
    ) AS r4_postal_name4,
    -- Rule 5: Country + Address_Number + Exact 2nd Word of Name (min length 4)
    (
        s1.country_norm = cand.country_norm
        AND regexp_extract(s1.address_norm, '[0-9]+', 0) <> ''
        AND regexp_extract(s1.address_norm, '[0-9]+', 0) = regexp_extract(cand.address_norm, '[0-9]+', 0)
        AND split_part(s1.name_norm, ' ', 2) <> ''
        AND split_part(s1.name_norm, ' ', 2) = split_part(cand.name_norm, ' ', 2)
        AND length(split_part(s1.name_norm, ' ', 2)) >= 4
    ) AS r5_addrnum_word2
FROM gt_links gt
JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
LEFT JOIN cand_all cand ON gt.candidate_id = cand.entity_id
""")

gt_total = con.execute("SELECT COUNT(*) FROM gt_eval").fetchone()[0]

res = con.execute("""
SELECT
    COUNT(CASE WHEN r1_exact_name THEN 1 END) AS r1,
    COUNT(CASE WHEN r2_exact_addr THEN 1 END) AS r2,
    COUNT(CASE WHEN r3_addrnum_name5 THEN 1 END) AS r3,
    COUNT(CASE WHEN r4_postal_name4 THEN 1 END) AS r4,
    COUNT(CASE WHEN r5_addrnum_word2 THEN 1 END) AS r5,
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 THEN 1 END) AS union_123,
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 OR r4_postal_name4 THEN 1 END) AS union_1234,
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 OR r4_postal_name4 OR r5_addrnum_word2 THEN 1 END) AS union_all
FROM gt_eval
""").fetchone()

print(f"Total Ground-Truth Links: {gt_total:,}\n")
print(f"Rule 1 (Exact Name)                      : {res[0]:,} ({res[0]/gt_total:.4%})")
print(f"Rule 2 (Exact Address)                   : {res[1]:,} ({res[1]/gt_total:.4%})")
print(f"Rule 3 (AddrNum + NamePrefix5)           : {res[2]:,} ({res[2]/gt_total:.4%})")
print(f"Rule 4 (Postal + NamePrefix4)            : {res[3]:,} ({res[3]/gt_total:.4%})")
print(f"Rule 5 (AddrNum + NameWord2)             : {res[4]:,} ({res[4]/gt_total:.4%})")
print("-" * 60)
print(f"Union R1 + R2 + R3                       : {res[5]:,} ({res[5]/gt_total:.4%})")
print(f"Union R1 + R2 + R3 + R4                  : {res[6]:,} ({res[6]/gt_total:.4%})")
print(f"Union R1 + R2 + R3 + R4 + R5             : {res[7]:,} ({res[7]/gt_total:.4%})")
print(f"\nElapsed: {time.time() - start:.2f}s")

con.close()
