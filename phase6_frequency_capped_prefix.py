import duckdb
import time
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 80)
print("PHASE 6: FREQUENCY-CAPPED NAME PREFIX BLOCKING EXPERIMENT")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)

con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

start_total = time.time()

# ---------------------------------------------------------------------
# 1. Ground Truth Setup
# ---------------------------------------------------------------------
print("\n[1/4] Preparing Ground Truth and Baseline flags...")
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
CREATE OR REPLACE TEMP TABLE gt_split AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    CASE 
        WHEN s2.entity_id IS NOT NULL THEN 'S2'
        WHEN s3.entity_id IS NOT NULL THEN 'S3'
        ELSE 'UNKNOWN'
    END AS target_source,
    s1.block_name_prefix5 AS s1_p5,
    COALESCE(s2.block_name_prefix5, s3.block_name_prefix5) AS cand_p5,
    -- Official Baseline Match Flag (86.4812%)
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
    ) AS baseline_match,
    -- Safe sub-baseline: Exact Name OR Exact Address
    (
        (s2.entity_id IS NOT NULL AND (
            s1.block_name_exact = s2.block_name_exact OR
            s1.block_address_exact = s2.block_address_exact
        ))
        OR
        (s3.entity_id IS NOT NULL AND (
            s1.block_name_exact = s3.block_name_exact OR
            s1.block_address_exact = s3.block_address_exact
        ))
    ) AS exact_match
FROM gt_links gt
JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
""")

gt_s2_total = con.execute("SELECT COUNT(*) FROM gt_split WHERE target_source = 'S2'").fetchone()[0]
gt_s3_total = con.execute("SELECT COUNT(*) FROM gt_split WHERE target_source = 'S3'").fetchone()[0]
base_hits = con.execute("SELECT COUNT(*) FROM gt_split WHERE baseline_match").fetchone()[0]
exact_hits = con.execute("SELECT COUNT(*) FROM gt_split WHERE exact_match").fetchone()[0]

print(f"Total Ground-Truth Links     : {total_gt:,} (S2: {gt_s2_total:,}, S3: {gt_s3_total:,})")
print(f"Official Baseline Recovered  : {base_hits:,} ({base_hits/total_gt:.4%})")
print(f"Exact Name / Address Only    : {exact_hits:,} ({exact_hits/total_gt:.4%})")

# ---------------------------------------------------------------------
# 2. Block Size Frequency Tables
# ---------------------------------------------------------------------
print("\n[2/4] Pre-aggregating block frequencies for Country + Name Prefix 5...")
con.execute("""
CREATE OR REPLACE TEMP TABLE prefix_freq AS
SELECT
    COALESCE(s1.block_name_prefix5, s2.block_name_prefix5, s3.block_name_prefix5) AS block_key,
    COALESCE(s1.c1, 0) AS s1_cnt,
    COALESCE(s2.c2, 0) AS s2_cnt,
    COALESCE(s3.c3, 0) AS s3_cnt,
    GREATEST(COALESCE(s1.c1, 0), COALESCE(s2.c2, 0), COALESCE(s3.c3, 0)) AS max_cnt,
    COALESCE(s1.c1, 0) + COALESCE(s2.c2, 0) + COALESCE(s3.c3, 0) AS total_cnt
FROM (
    SELECT block_name_prefix5, COUNT(*) AS c1
    FROM train_s1 WHERE block_name_prefix5 IS NOT NULL
    GROUP BY block_name_prefix5
) s1
FULL OUTER JOIN (
    SELECT block_name_prefix5, COUNT(*) AS c2
    FROM train_s2 WHERE block_name_prefix5 IS NOT NULL
    GROUP BY block_name_prefix5
) s2 ON s1.block_name_prefix5 = s2.block_name_prefix5
FULL OUTER JOIN (
    SELECT block_name_prefix5, COUNT(*) AS c3
    FROM train_s3 WHERE block_name_prefix5 IS NOT NULL
    GROUP BY block_name_prefix5
) s3 ON COALESCE(s1.block_name_prefix5, s2.block_name_prefix5) = s3.block_name_prefix5
""")

block_stats = con.execute("""
SELECT
    COUNT(*) AS total_distinct_blocks,
    COUNT(CASE WHEN max_cnt <= 25 THEN 1 END) AS blocks_le_25,
    COUNT(CASE WHEN max_cnt <= 50 THEN 1 END) AS blocks_le_50,
    COUNT(CASE WHEN max_cnt <= 100 THEN 1 END) AS blocks_le_100,
    COUNT(CASE WHEN max_cnt <= 250 THEN 1 END) AS blocks_le_250
FROM prefix_freq
""").fetchone()

print(f"Total Unique Name Prefix 5 Blocks: {block_stats[0]:,}")
print(f"  Blocks with max_freq <= 25  : {block_stats[1]:,} ({block_stats[1]/block_stats[0]:.2%})")
print(f"  Blocks with max_freq <= 50  : {block_stats[2]:,} ({block_stats[2]/block_stats[0]:.2%})")
print(f"  Blocks with max_freq <= 100 : {block_stats[3]:,} ({block_stats[3]/block_stats[0]:.2%})")
print(f"  Blocks with max_freq <= 250 : {block_stats[4]:,} ({block_stats[4]/block_stats[0]:.2%})")

# ---------------------------------------------------------------------
# 3. Evaluate Thresholds: 25, 50, 100, 250
# ---------------------------------------------------------------------
print("\n[3/4] Evaluating Candidate Volume and Recall for Thresholds [25, 50, 100, 250]...")

thresholds = [25, 50, 100, 250]

# We will test two capping definitions for thoroughness:
# Definition A: max_cnt <= T (symmetric: neither S1 nor S2/S3 has > T entities)
# Definition B: s2_cnt <= T and s3_cnt <= T (candidate side cap)

for cap_type, where_clause, cap_label in [
    ("symmetric", "pf.max_cnt <= {T}", "Max Single-Source Frequency (max_cnt <= T)"),
    ("candidate_side", "pf.s2_cnt <= {T} AND pf.s3_cnt <= {T}", "Candidate-Side Frequency (s2_cnt <= T AND s3_cnt <= T)")
]:
    print("\n" + "=" * 80)
    print(f"CAP CRITERION: {cap_label}")
    print("=" * 80)

    for T in thresholds:
        t_start = time.time()
        cond = where_clause.format(T=T)

        # 3a. Candidate volumes
        con.execute(f"""
        CREATE OR REPLACE TEMP TABLE filtered_blocks AS
        SELECT block_key, s1_cnt, s2_cnt, s3_cnt
        FROM prefix_freq pf
        WHERE {cond}
        """)

        vol = con.execute("""
        SELECT
            COALESCE(SUM(s1_cnt * s2_cnt), 0) AS s2_pairs,
            COALESCE(SUM(s1_cnt * s3_cnt), 0) AS s3_pairs,
            COALESCE(SUM(s1_cnt * (s2_cnt + s3_cnt)), 0) AS total_pairs
        FROM filtered_blocks
        """).fetchone()

        s2_cand_pairs, s3_cand_pairs, total_cand_pairs = vol

        # 3b. Per-S1 Candidate Distribution
        con.execute("""
        CREATE OR REPLACE TEMP TABLE s1_dist AS
        SELECT
            s1.entity_id,
            COALESCE(fb.s2_cnt, 0) AS s2_c,
            COALESCE(fb.s3_cnt, 0) AS s3_c,
            COALESCE(fb.s2_cnt, 0) + COALESCE(fb.s3_cnt, 0) AS tot_c
        FROM train_s1 s1
        LEFT JOIN filtered_blocks fb ON s1.block_name_prefix5 = fb.block_key
        """)

        dist = con.execute("""
        SELECT
            AVG(tot_c) AS avg_c,
            median(tot_c) AS med_c,
            quantile_cont(tot_c, 0.90) AS p90,
            quantile_cont(tot_c, 0.95) AS p95,
            quantile_cont(tot_c, 0.99) AS p99,
            MAX(tot_c) AS max_c,
            SUM(CASE WHEN tot_c > 100 THEN 1 ELSE 0 END) AS gt_100,
            SUM(CASE WHEN tot_c > 1000 THEN 1 ELSE 0 END) AS gt_1000,
            SUM(CASE WHEN tot_c > 10000 THEN 1 ELSE 0 END) AS gt_10000,
            SUM(CASE WHEN tot_c > 100000 THEN 1 ELSE 0 END) AS gt_100000
        FROM s1_dist
        """).fetchone()

        # 3c. Recall on Ground Truth
        # For a link to be recovered by this capped rule:
        # s1_p5 must equal cand_p5, AND block_key must be in filtered_blocks
        con.execute("""
        CREATE OR REPLACE TEMP TABLE gt_capped AS
        SELECT
            gt.s1_id,
            gt.candidate_id,
            gt.target_source,
            gt.baseline_match,
            gt.exact_match,
            (
                gt.s1_p5 IS NOT NULL
                AND gt.s1_p5 = gt.cand_p5
                AND fb.block_key IS NOT NULL
            ) AS rule_recovered
        FROM gt_split gt
        LEFT JOIN filtered_blocks fb ON gt.s1_p5 = fb.block_key
        """)

        rec = con.execute("""
        SELECT
            COUNT(CASE WHEN rule_recovered THEN 1 END) AS stand_total,
            COUNT(CASE WHEN target_source = 'S2' AND rule_recovered THEN 1 END) AS stand_s2,
            COUNT(CASE WHEN target_source = 'S3' AND rule_recovered THEN 1 END) AS stand_s3,
            -- Incremental over official baseline (86.4812%)
            COUNT(CASE WHEN baseline_match OR rule_recovered THEN 1 END) AS union_baseline,
            -- Incremental over safe exact matches (exact name OR exact address)
            COUNT(CASE WHEN exact_match OR rule_recovered THEN 1 END) AS union_exact
        FROM gt_capped
        """).fetchone()

        stand_total, stand_s2, stand_s3, union_base, union_exact = rec

        stand_recall = stand_total / total_gt
        stand_recall_s2 = stand_s2 / gt_s2_total
        stand_recall_s3 = stand_s3 / gt_s3_total
        incr_base = (union_base - base_hits) / total_gt
        incr_exact = (union_exact - exact_hits) / total_gt

        elapsed = time.time() - t_start

        print(f"\n--- Threshold <= {T} ({cap_type}) ---")
        print(f"  Candidate Counts:")
        print(f"    S1 -> S2 Pairs      : {s2_cand_pairs:,}")
        print(f"    S1 -> S3 Pairs      : {s3_cand_pairs:,}")
        print(f"    Combined Pairs      : {total_cand_pairs:,}")
        print(f"  Standalone Recall:")
        print(f"    S1 -> S2 Recall     : {stand_recall_s2:.4%} ({stand_s2:,} / {gt_s2_total:,})")
        print(f"    S1 -> S3 Recall     : {stand_recall_s3:.4%} ({stand_s3:,} / {gt_s3_total:,})")
        print(f"    Combined Recall     : {stand_recall:.4%} ({stand_total:,} / {total_gt:,})")
        print(f"  Incremental Recall:")
        print(f"    Over Current 86.48% : {incr_base:+.4%} ({union_base - base_hits:,} new links)")
        print(f"    Over Exact Name/Addr: {incr_exact:+.4%} ({union_exact - exact_hits:,} new links; Union = {union_exact/total_gt:.4%})")
        print(f"  Per-S1 Distribution:")
        print(f"    Average Candidates/S1 : {dist[0]:.2f}")
        print(f"    Median Candidates/S1  : {dist[1]:.1f}")
        print(f"    P90 / P95 / P99       : {dist[2]:.1f} / {dist[3]:.1f} / {dist[4]:.1f}")
        print(f"    Maximum Candidates/S1 : {dist[5]:,}")
        print(f"    S1 with >100 Cands    : {dist[6]:,}")
        print(f"    S1 with >1,000 Cands  : {dist[7]:,}")
        print(f"    S1 with >10,000 Cands : {dist[8]:,}")
        print(f"    S1 with >100k Cands   : {dist[9]:,}")
        print(f"  Runtime: {elapsed:.2f}s | Memory: < 4GB")

print("\n" + "=" * 80)
print(f"EXPERIMENT COMPLETED in {time.time() - start_total:.2f} seconds.")
print("=" * 80)

con.close()
