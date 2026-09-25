import duckdb
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 80)
print("PHASE 6: MEASURING PRACTICAL SELECTIVE BLOCKING ENSEMBLE")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)

con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

start = time.time()

# 1. Ground truth
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

total_gt = con.execute("SELECT COUNT(*) FROM gt_links").fetchone()[0]

con.execute("""
CREATE OR REPLACE TEMP TABLE cand_all AS
SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal,
    regexp_extract(address_norm, '[0-9]+', 0) AS addr_num,
    split_part(name_norm, ' ', 1) AS w1,
    split_part(name_norm, ' ', 2) AS w2
FROM train_s2
UNION ALL
SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal,
    regexp_extract(address_norm, '[0-9]+', 0) AS addr_num,
    split_part(name_norm, ' ', 1) AS w1,
    split_part(name_norm, ' ', 2) AS w2
FROM train_s3
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s1_all AS
SELECT
    entity_id,
    country_norm,
    name_norm,
    address_norm,
    block_name_exact,
    block_address_exact,
    block_name_prefix5,
    block_address_prefix8,
    block_postal,
    regexp_extract(address_norm, '[0-9]+', 0) AS addr_num,
    split_part(name_norm, ' ', 1) AS w1,
    split_part(name_norm, ' ', 2) AS w2
FROM train_s1
""")

print("Evaluating recall of practical rules on Ground Truth...")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_ensemble_eval AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    -- Official Baseline:
    (
        s1.block_name_exact = c.block_name_exact OR
        s1.block_address_exact = c.block_address_exact OR
        s1.block_name_prefix5 = c.block_name_prefix5 OR
        s1.block_address_prefix8 = c.block_address_prefix8
    ) AS base_match,

    -- Safe Rule 1: Exact Name
    (s1.block_name_exact IS NOT NULL AND s1.block_name_exact = c.block_name_exact) AS r1_exact_name,

    -- Safe Rule 2: Exact Address
    (s1.block_address_exact IS NOT NULL AND s1.block_address_exact = c.block_address_exact) AS r2_exact_addr,

    -- Safe Rule 3: Country + AddrNum + NamePrefix5
    (
        s1.country_norm = c.country_norm
        AND s1.addr_num <> '' AND s1.addr_num = c.addr_num
        AND length(s1.name_norm) >= 5
        AND substr(s1.name_norm, 1, 5) = substr(c.name_norm, 1, 5)
    ) AS r3_addrnum_name5,

    -- Safe Rule 4: Cross-Word (AddrNum + w1=w2 or w2=w1)
    (
        s1.country_norm = c.country_norm
        AND s1.addr_num <> '' AND s1.addr_num = c.addr_num
        AND (
            (length(s1.w1) >= 4 AND s1.w1 = c.w2) OR
            (length(s1.w2) >= 4 AND s1.w2 = c.w1)
        )
    ) AS r4_crossword,

    -- Safe Rule 5: Postal + AddrNum
    (
        s1.block_postal IS NOT NULL AND s1.block_postal = c.block_postal
        AND s1.addr_num <> '' AND s1.addr_num = c.addr_num
    ) AS r5_postal_num,

    -- Safe Rule 6: Postal + NamePrefix4
    (
        s1.block_postal IS NOT NULL AND s1.block_postal = c.block_postal
        AND length(s1.name_norm) >= 4
        AND substr(s1.name_norm, 1, 4) = substr(c.name_norm, 1, 4)
    ) AS r6_postal_name4,

    -- Safe Rule 7: AddrNum + 2nd Word of Name
    (
        s1.country_norm = c.country_norm
        AND s1.addr_num <> '' AND s1.addr_num = c.addr_num
        AND length(s1.w2) >= 4 AND s1.w2 = c.w2
    ) AS r7_addrnum_w2

FROM gt_links gt
JOIN s1_all s1 ON gt.s1_id = s1.entity_id
LEFT JOIN cand_all c ON gt.candidate_id = c.entity_id
""")

stats = con.execute("""
SELECT
    COUNT(*) AS total_gt,
    COUNT(CASE WHEN base_match THEN 1 END) AS base_hits,
    COUNT(CASE WHEN r1_exact_name THEN 1 END) AS r1,
    COUNT(CASE WHEN r2_exact_addr THEN 1 END) AS r2,
    COUNT(CASE WHEN r3_addrnum_name5 THEN 1 END) AS r3,
    COUNT(CASE WHEN r4_crossword THEN 1 END) AS r4,
    COUNT(CASE WHEN r5_postal_num THEN 1 END) AS r5,
    COUNT(CASE WHEN r6_postal_name4 THEN 1 END) AS r6,
    COUNT(CASE WHEN r7_addrnum_w2 THEN 1 END) AS r7,

    -- Incremental additions over current baseline:
    COUNT(CASE WHEN base_match OR r4_crossword THEN 1 END) AS base_plus_r4,
    COUNT(CASE WHEN base_match OR r4_crossword OR r5_postal_num THEN 1 END) AS base_plus_r4_r5,
    COUNT(CASE WHEN base_match OR r4_crossword OR r5_postal_num OR r6_postal_name4 OR r7_addrnum_w2 THEN 1 END) AS base_plus_all,

    -- Practical Ensemble Union (without 12.8B prefix5 explosion):
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 THEN 1 END) AS union_123,
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 OR r4_crossword THEN 1 END) AS union_1234,
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 OR r4_crossword OR r5_postal_num THEN 1 END) AS union_12345,
    COUNT(CASE WHEN r1_exact_name OR r2_exact_addr OR r3_addrnum_name5 OR r4_crossword OR r5_postal_num OR r6_postal_name4 OR r7_addrnum_w2 THEN 1 END) AS practical_union
FROM gt_ensemble_eval
""").fetchone()

print(f"\n================================================================================")
print(f"PRACTICAL SELECTIVE BLOCKING RECALL SUMMARY")
print(f"================================================================================")
print(f"Total Ground Truth Links: {stats[0]:,}\n")
print(f"Official Baseline Recall (Unconstrained) : {stats[1]:,} ({stats[1]/stats[0]:.4%})")
print(f"  + R4 (Cross-word)                      : {stats[9]:,} ({stats[9]/stats[0]:.4%}) [+{stats[9]-stats[1]:,} links, +{(stats[9]-stats[1])/stats[0]:.4%}]")
print(f"  + R4 + R5 (Postal+Num)                 : {stats[10]:,} ({stats[10]/stats[0]:.4%}) [+{stats[10]-stats[1]:,} links, +{(stats[10]-stats[1])/stats[0]:.4%}]")
print(f"  + R4 + R5 + R6 + R7                    : {stats[11]:,} ({stats[11]/stats[0]:.4%}) [+{stats[11]-stats[1]:,} links, +{(stats[11]-stats[1])/stats[0]:.4%}]")
print("-" * 80)
print(f"Individual Safe Rule Recall:")
print(f"  R1 (Exact Name)                        : {stats[2]:,} ({stats[2]/stats[0]:.4%})")
print(f"  R2 (Exact Address)                     : {stats[3]:,} ({stats[3]/stats[0]:.4%})")
print(f"  R3 (AddrNum + NamePrefix5)             : {stats[4]:,} ({stats[4]/stats[0]:.4%})")
print(f"  R4 (Cross-Word)                        : {stats[5]:,} ({stats[5]/stats[0]:.4%})")
print(f"  R5 (Postal + AddrNum)                  : {stats[6]:,} ({stats[6]/stats[0]:.4%})")
print(f"  R6 (Postal + NamePrefix4)              : {stats[7]:,} ({stats[7]/stats[0]:.4%})")
print(f"  R7 (AddrNum + Word2)                   : {stats[8]:,} ({stats[8]/stats[0]:.4%})")
print("-" * 80)
print(f"Practical Ensemble Cumulative Union:")
print(f"  R1 + R2 + R3                           : {stats[12]:,} ({stats[12]/stats[0]:.4%})")
print(f"  R1 + R2 + R3 + R4                      : {stats[13]:,} ({stats[13]/stats[0]:.4%})")
print(f"  R1 + R2 + R3 + R4 + R5                 : {stats[14]:,} ({stats[14]/stats[0]:.4%})")
print(f"  R1 + R2 + R3 + R4 + R5 + R6 + R7       : {stats[15]:,} ({stats[15]/stats[0]:.4%})")
print(f"================================================================================")
print(f"Calculation time: {time.time() - start:.2f}s")

con.close()
