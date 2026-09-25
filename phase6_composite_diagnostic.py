import duckdb
import time
import os

print("=" * 80)
print("PHASE 6 DIAGNOSTIC: COUNTRY + ADDRESS_NUMBER + NAME_PREFIX5")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)

con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

start_time = time.time()

# ---------------------------------------------------------------------
# 1. Ground Truth Links Table
# ---------------------------------------------------------------------
print("\n[1/5] Preparing Ground Truth links...")
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
print(f"Total Ground-Truth links: {total_gt:,}")

# Break down GT into S2 and S3 links
con.execute("""
CREATE OR REPLACE TEMP TABLE gt_split AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    CASE 
        WHEN s2.entity_id IS NOT NULL THEN 'S2'
        WHEN s3.entity_id IS NOT NULL THEN 'S3'
        ELSE 'UNKNOWN'
    END AS target_source
FROM gt_links gt
LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
""")

gt_s2_count = con.execute("SELECT COUNT(*) FROM gt_split WHERE target_source = 'S2'").fetchone()[0]
gt_s3_count = con.execute("SELECT COUNT(*) FROM gt_split WHERE target_source = 'S3'").fetchone()[0]
print(f"Ground-Truth S2 links: {gt_s2_count:,} ({gt_s2_count/total_gt:.2%})")
print(f"Ground-Truth S3 links: {gt_s3_count:,} ({gt_s3_count/total_gt:.2%})")

# ---------------------------------------------------------------------
# 2. Define and Extract Blocking Keys
# ---------------------------------------------------------------------
print("\n[2/5] Creating blocking key tables with COUNTRY + ADDRESS_NUMBER + NAME_PREFIX5...")

# Check definition:
# addr_num: first continuous digits in address_norm
# name_prefix5: first 5 characters of name_norm (if length >= 5)
# key: country_norm || '|' || addr_num || '|' || substr(name_norm, 1, 5)

for table, temp_tbl in [("train_s1", "s1_keys"), ("train_s2", "s2_keys"), ("train_s3", "s3_keys")]:
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE {temp_tbl} AS
    SELECT
        entity_id,
        country_norm,
        name_norm,
        address_norm,
        block_name_exact,
        block_address_exact,
        block_name_prefix5,
        block_address_prefix8,
        regexp_extract(address_norm, '[0-9]+', 0) AS addr_num,
        CASE
            WHEN length(name_norm) >= 5 
                 AND regexp_extract(address_norm, '[0-9]+', 0) <> ''
            THEN country_norm || '|' || regexp_extract(address_norm, '[0-9]+', 0) || '|' || substr(name_norm, 1, 5)
            ELSE NULL
        END AS block_country_addrnum_name5
    FROM {table}
    """)
    cnt = con.execute(f"SELECT COUNT(*), COUNT(block_country_addrnum_name5), COUNT(DISTINCT block_country_addrnum_name5) FROM {temp_tbl}").fetchone()
    print(f"  {table}: total={cnt[0]:,}, valid_keys={cnt[1]:,} ({cnt[1]/cnt[0]:.2%}), distinct_keys={cnt[2]:,}")

# ---------------------------------------------------------------------
# 3. Ground-Truth Recall Measurement
# ---------------------------------------------------------------------
print("\n[3/5] Measuring Ground-Truth Recall of COUNTRY + ADDRESS_NUMBER + NAME_PREFIX5...")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_eval AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    gt.target_source,
    s1.block_country_addrnum_name5 AS s1_key,
    COALESCE(s2.block_country_addrnum_name5, s3.block_country_addrnum_name5) AS cand_key,
    s1.block_name_prefix5 AS s1_name5,
    COALESCE(s2.block_name_prefix5, s3.block_name_prefix5) AS cand_name5,
    -- Baseline match flag
    (
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
    ) AS baseline_match
FROM gt_split gt
JOIN s1_keys s1 ON gt.s1_id = s1.entity_id
LEFT JOIN s2_keys s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN s3_keys s3 ON gt.candidate_id = s3.entity_id
""")

recall_stats = con.execute("""
SELECT
    target_source,
    COUNT(*) AS total_links,
    COUNT(CASE WHEN s1_key IS NOT NULL AND s1_key = cand_key THEN 1 END) AS key_recovered,
    COUNT(CASE WHEN baseline_match THEN 1 END) AS baseline_recovered,
    COUNT(CASE WHEN baseline_match OR (s1_key IS NOT NULL AND s1_key = cand_key) THEN 1 END) AS union_recovered
FROM gt_eval
GROUP BY target_source
UNION ALL
SELECT
    'TOTAL' AS target_source,
    COUNT(*) AS total_links,
    COUNT(CASE WHEN s1_key IS NOT NULL AND s1_key = cand_key THEN 1 END) AS key_recovered,
    COUNT(CASE WHEN baseline_match THEN 1 END) AS baseline_recovered,
    COUNT(CASE WHEN baseline_match OR (s1_key IS NOT NULL AND s1_key = cand_key) THEN 1 END) AS union_recovered
FROM gt_eval
""").fetchall()

print(f"{'Source':<10} | {'Total Links':<12} | {'Key Recovered':<14} | {'Key Recall':<12} | {'Baseline Recall':<16} | {'Union Recall':<14}")
print("-" * 88)
for row in recall_stats:
    src, total, key_rec, base_rec, union_rec = row
    print(f"{src:<10} | {total:>12,} | {key_rec:>14,} | {key_rec/total:>11.4%} | {base_rec/total:>15.4%} | {union_rec/total:>13.4%}")

# ---------------------------------------------------------------------
# 4. Candidate Volume and Distribution Diagnostics
# ---------------------------------------------------------------------
print("\n[4/5] Measuring Candidate Volume & Distributions per S1...")

# Pre-aggregate candidate counts per key for S2 and S3
con.execute("""
CREATE OR REPLACE TEMP TABLE s2_key_counts AS
SELECT block_country_addrnum_name5 AS block_key, COUNT(*) AS s2_cnt
FROM s2_keys
WHERE block_country_addrnum_name5 IS NOT NULL
GROUP BY block_country_addrnum_name5
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s3_key_counts AS
SELECT block_country_addrnum_name5 AS block_key, COUNT(*) AS s3_cnt
FROM s3_keys
WHERE block_country_addrnum_name5 IS NOT NULL
GROUP BY block_country_addrnum_name5
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE s1_candidate_counts AS
SELECT
    s1.entity_id,
    COALESCE(s2.s2_cnt, 0) AS s2_cands,
    COALESCE(s3.s3_cnt, 0) AS s3_cands,
    COALESCE(s2.s2_cnt, 0) + COALESCE(s3.s3_cnt, 0) AS total_cands
FROM s1_keys s1
LEFT JOIN s2_key_counts s2 ON s1.block_country_addrnum_name5 = s2.block_key
LEFT JOIN s3_key_counts s3 ON s1.block_country_addrnum_name5 = s3.block_key
""")

def compute_dist(col_name, label):
    query = f"""
    SELECT
        COUNT(*) AS s1_total,
        SUM({col_name}) AS total_candidates,
        AVG({col_name}) AS avg_cands,
        median({col_name}) AS median_cands,
        quantile_cont({col_name}, 0.90) AS p90,
        quantile_cont({col_name}, 0.95) AS p95,
        quantile_cont({col_name}, 0.99) AS p99,
        MAX({col_name}) AS max_cands,
        SUM(CASE WHEN {col_name} = 0 THEN 1 ELSE 0 END) AS zero_cands,
        SUM(CASE WHEN {col_name} > 100 THEN 1 ELSE 0 END) AS gt_100,
        SUM(CASE WHEN {col_name} > 1000 THEN 1 ELSE 0 END) AS gt_1000,
        SUM(CASE WHEN {col_name} > 10000 THEN 1 ELSE 0 END) AS gt_10000,
        SUM(CASE WHEN {col_name} > 100000 THEN 1 ELSE 0 END) AS gt_100000
    FROM s1_candidate_counts
    """
    row = con.execute(query).fetchone()
    print(f"\n--- Distribution for {label} ---")
    print(f"  S1 Entities           : {row[0]:,}")
    print(f"  Total Candidate Pairs : {row[1]:,}")
    print(f"  Average Candidates/S1 : {row[2]:.2f}")
    print(f"  Median Candidates/S1  : {row[3]:.1f}")
    print(f"  P90 Candidates/S1     : {row[4]:.1f}")
    print(f"  P95 Candidates/S1     : {row[5]:.1f}")
    print(f"  P99 Candidates/S1     : {row[6]:.1f}")
    print(f"  Max Candidates/S1     : {row[7]:,}")
    print(f"  S1 with 0 Candidates  : {row[8]:,} ({row[8]/row[0]:.2%})")
    print(f"  S1 with >100 Cands    : {row[9]:,} ({row[9]/row[0]:.2%})")
    print(f"  S1 with >1,000 Cands  : {row[10]:,} ({row[10]/row[0]:.4%})")
    print(f"  S1 with >10,000 Cands : {row[11]:,} ({row[11]/row[0]:.4%})")
    print(f"  S1 with >100k Cands   : {row[12]:,} ({row[12]/row[0]:.4%})")

compute_dist("s2_cands", "S1 -> S2 (Country + Address_Number + Name_Prefix5)")
compute_dist("s3_cands", "S1 -> S3 (Country + Address_Number + Name_Prefix5)")
compute_dist("total_cands", "S1 -> COMBINED S2+S3 (Country + Address_Number + Name_Prefix5)")

# ---------------------------------------------------------------------
# 5. Diagnostic on Address Number behavior
# ---------------------------------------------------------------------
print("\n[5/5] Diagnostic on Why Address Number had 100% recall earlier...")
con.execute("""
CREATE OR REPLACE TEMP TABLE addr_num_investigation AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    s1.addr_num AS s1_addr_num,
    COALESCE(s2.addr_num, s3.addr_num) AS cand_addr_num,
    (s1.addr_num = COALESCE(s2.addr_num, s3.addr_num)) AS raw_equal,
    (s1.addr_num <> '' AND s1.addr_num = COALESCE(s2.addr_num, s3.addr_num)) AS non_empty_equal
FROM gt_split gt
JOIN s1_keys s1 ON gt.s1_id = s1.entity_id
LEFT JOIN s2_keys s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN s3_keys s3 ON gt.candidate_id = s3.entity_id
""")

inv = con.execute("""
SELECT
    COUNT(*) AS total_gt,
    COUNT(CASE WHEN s1_addr_num = '' AND cand_addr_num = '' THEN 1 END) AS both_empty,
    COUNT(CASE WHEN raw_equal THEN 1 END) AS raw_equal_count,
    COUNT(CASE WHEN non_empty_equal THEN 1 END) AS true_matching_numbers,
    COUNT(CASE WHEN s1_addr_num <> '' AND cand_addr_num <> '' AND s1_addr_num <> cand_addr_num THEN 1 END) AS mismatching_numbers,
    COUNT(CASE WHEN (s1_addr_num = '' AND cand_addr_num <> '') OR (s1_addr_num <> '' AND cand_addr_num = '') THEN 1 END) AS one_empty_one_has_num
FROM addr_num_investigation
""").fetchone()

print(f"  Total GT Links                       : {inv[0]:,}")
print(f"  Raw string equality ('' = '')        : {inv[2]:,} ({inv[2]/inv[0]:.4%})")
print(f"  Both have NO number ('' == '')       : {inv[1]:,} ({inv[1]/inv[0]:.4%})")
print(f"  True matching non-empty number       : {inv[3]:,} ({inv[3]/inv[0]:.4%})")
print(f"  Both have numbers, but MISMATCH      : {inv[4]:,} ({inv[4]/inv[0]:.4%})")
print(f"  One has number, other has none       : {inv[5]:,} ({inv[5]/inv[0]:.4%})")

elapsed = time.time() - start_time
print(f"\nCompleted in {elapsed:.2f} seconds.")
con.close()
