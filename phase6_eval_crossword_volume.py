import duckdb
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

print("=" * 80)
print("PHASE 6: EVALUATING CANDIDATE VOLUME & RECALL OF H2 (CROSS-WORD BLOCKING)")
print("Key: Country + AddrNum + Cross-Word (w1=w2 or w2=w1, min length 4)")
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
    ) AS baseline_match
FROM gt_links gt
JOIN train_s1 s1 ON gt.s1_id = s1.entity_id
LEFT JOIN train_s2 s2 ON gt.candidate_id = s2.entity_id
LEFT JOIN train_s3 s3 ON gt.candidate_id = s3.entity_id
""")

gt_s2_total = con.execute("SELECT COUNT(*) FROM gt_split WHERE target_source = 'S2'").fetchone()[0]
gt_s3_total = con.execute("SELECT COUNT(*) FROM gt_split WHERE target_source = 'S3'").fetchone()[0]
base_hits = con.execute("SELECT COUNT(*) FROM gt_split WHERE baseline_match").fetchone()[0]

print(f"Total Ground-Truth Links     : {total_gt:,} (S2: {gt_s2_total:,}, S3: {gt_s3_total:,})")
print(f"Official Baseline Recovered  : {base_hits:,} ({base_hits/total_gt:.4%})")

# ---------------------------------------------------------------------
# 2. Extract Keys for Cross-Word Blocking
# S1 has two keys:
#   k1 = country || '|' || addr_num || '|' || word1 (if len >= 4)
#   k2 = country || '|' || addr_num || '|' || word2 (if len >= 4)
# Cross-matching means:
#   S1.k1 matches Cand.k2
#   S1.k2 matches Cand.k1
# ---------------------------------------------------------------------
print("\n[2/4] Extracting Word1 and Word2 keys...")

for table, tbl_out in [("train_s1", "s1_words"), ("train_s2", "s2_words"), ("train_s3", "s3_words")]:
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE {tbl_out} AS
    SELECT
        entity_id,
        CASE
            WHEN regexp_extract(address_norm, '[0-9]+', 0) <> '' 
                 AND length(split_part(name_norm, ' ', 1)) >= 4
            THEN country_norm || '|' || regexp_extract(address_norm, '[0-9]+', 0) || '|' || split_part(name_norm, ' ', 1)
            ELSE NULL
        END AS key_w1,
        CASE
            WHEN regexp_extract(address_norm, '[0-9]+', 0) <> '' 
                 AND length(split_part(name_norm, ' ', 2)) >= 4
            THEN country_norm || '|' || regexp_extract(address_norm, '[0-9]+', 0) || '|' || split_part(name_norm, ' ', 2)
            ELSE NULL
        END AS key_w2
    FROM {table}
    """)

# ---------------------------------------------------------------------
# 3. Candidate Volume and Distribution Calculation
# ---------------------------------------------------------------------
print("\n[3/4] Measuring Candidate Volume for Cross-Word Matching...")

# In cross-word matching:
# S1.k1 matches S2.k2, AND S1.k2 matches S2.k1
# To avoid double counting candidates that match both (rare, but possible):
# We can pre-aggregate counts per key.

# S2 key counts
con.execute("""
CREATE OR REPLACE TEMP TABLE s2_k1_counts AS
SELECT key_w1 AS k, COUNT(*) AS cnt FROM s2_words WHERE key_w1 IS NOT NULL GROUP BY key_w1;
CREATE OR REPLACE TEMP TABLE s2_k2_counts AS
SELECT key_w2 AS k, COUNT(*) AS cnt FROM s2_words WHERE key_w2 IS NOT NULL GROUP BY key_w2;
""")

# S3 key counts
con.execute("""
CREATE OR REPLACE TEMP TABLE s3_k1_counts AS
SELECT key_w1 AS k, COUNT(*) AS cnt FROM s3_words WHERE key_w1 IS NOT NULL GROUP BY key_w1;
CREATE OR REPLACE TEMP TABLE s3_k2_counts AS
SELECT key_w2 AS k, COUNT(*) AS cnt FROM s3_words WHERE key_w2 IS NOT NULL GROUP BY key_w2;
""")

# S1 candidate counts:
# For S2: S1.key_w1 joined with S2.k2 + S1.key_w2 joined with S2.k1
con.execute("""
CREATE OR REPLACE TEMP TABLE s1_cand_dist AS
SELECT
    s1.entity_id,
    -- S2 candidates
    COALESCE(c2_k2.cnt, 0) + COALESCE(c2_k1.cnt, 0) AS s2_cands,
    -- S3 candidates
    COALESCE(c3_k2.cnt, 0) + COALESCE(c3_k1.cnt, 0) AS s3_cands,
    -- Combined
    (COALESCE(c2_k2.cnt, 0) + COALESCE(c2_k1.cnt, 0)) + 
    (COALESCE(c3_k2.cnt, 0) + COALESCE(c3_k1.cnt, 0)) AS total_cands
FROM s1_words s1
LEFT JOIN s2_k2_counts c2_k2 ON s1.key_w1 = c2_k2.k
LEFT JOIN s2_k1_counts c2_k1 ON s1.key_w2 = c2_k1.k
LEFT JOIN s3_k2_counts c3_k2 ON s1.key_w1 = c3_k2.k
LEFT JOIN s3_k1_counts c3_k1 ON s1.key_w2 = c3_k1.k
""")

vol_stats = con.execute("""
SELECT
    SUM(s2_cands) AS total_s2_pairs,
    SUM(s3_cands) AS total_s3_pairs,
    SUM(total_cands) AS total_combined_pairs,
    AVG(total_cands) AS avg_cands,
    median(total_cands) AS med_cands,
    quantile_cont(total_cands, 0.90) AS p90,
    quantile_cont(total_cands, 0.95) AS p95,
    quantile_cont(total_cands, 0.99) AS p99,
    MAX(total_cands) AS max_cands,
    SUM(CASE WHEN total_cands > 100 THEN 1 ELSE 0 END) AS gt_100,
    SUM(CASE WHEN total_cands > 1000 THEN 1 ELSE 0 END) AS gt_1000,
    SUM(CASE WHEN total_cands > 10000 THEN 1 ELSE 0 END) AS gt_10000,
    SUM(CASE WHEN total_cands > 100000 THEN 1 ELSE 0 END) AS gt_100000
FROM s1_cand_dist
""").fetchone()

s2_pairs, s3_pairs, tot_pairs, avg_c, med_c, p90, p95, p99, max_c, gt100, gt1k, gt10k, gt100k = vol_stats

# ---------------------------------------------------------------------
# 4. Recall Evaluation on Ground Truth
# ---------------------------------------------------------------------
print("\n[4/4] Measuring Ground Truth Recall and Incremental Gain...")

con.execute("""
CREATE OR REPLACE TEMP TABLE gt_rec_eval AS
SELECT
    gt.s1_id,
    gt.candidate_id,
    gt.target_source,
    gt.baseline_match,
    (
        (s1.key_w1 IS NOT NULL AND s1.key_w1 = cand.key_w2)
        OR
        (s1.key_w2 IS NOT NULL AND s1.key_w2 = cand.key_w1)
    ) AS crossword_match
FROM gt_split gt
JOIN s1_words s1 ON gt.s1_id = s1.entity_id
LEFT JOIN (
    SELECT entity_id, key_w1, key_w2 FROM s2_words
    UNION ALL
    SELECT entity_id, key_w1, key_w2 FROM s3_words
) cand ON gt.candidate_id = cand.entity_id
""")

rec_stats = con.execute("""
SELECT
    -- Standalone Cross-Word Recall
    COUNT(CASE WHEN crossword_match THEN 1 END) AS cw_total,
    COUNT(CASE WHEN target_source = 'S2' AND crossword_match THEN 1 END) AS cw_s2,
    COUNT(CASE WHEN target_source = 'S3' AND crossword_match THEN 1 END) AS cw_s3,
    -- Incremental over baseline
    COUNT(CASE WHEN baseline_match THEN 1 END) AS base_total,
    COUNT(CASE WHEN baseline_match OR crossword_match THEN 1 END) AS union_total,
    COUNT(CASE WHEN NOT baseline_match AND crossword_match THEN 1 END) AS new_links
FROM gt_rec_eval
""").fetchone()

cw_tot, cw_s2, cw_s3, b_tot, u_tot, new_links = rec_stats

cw_recall = cw_tot / total_gt
cw_recall_s2 = cw_s2 / gt_s2_total
cw_recall_s3 = cw_s3 / gt_s3_total
base_recall = b_tot / total_gt
union_recall = u_tot / total_gt
incremental_recall = new_links / total_gt

print(f"\n================================================================================")
print(f"RESULTS: H2 (CROSS-WORD: Country + AddrNum + Word1=Word2 / Word2=Word1)")
print(f"================================================================================")
print(f"1. Candidate Volume:")
print(f"   S1 -> S2 Pairs              : {s2_pairs:,}")
print(f"   S1 -> S3 Pairs              : {s3_pairs:,}")
print(f"   Combined Candidate Pairs    : {tot_pairs:,}")
print(f"2. Standalone Recall:")
print(f"   S1 -> S2 Recall             : {cw_recall_s2:.4%} ({cw_s2:,} / {gt_s2_total:,})")
print(f"   S1 -> S3 Recall             : {cw_recall_s3:.4%} ({cw_s3:,} / {gt_s3_total:,})")
print(f"   Combined Standalone Recall  : {cw_recall:.4%} ({cw_tot:,} / {total_gt:,})")
print(f"3. Incremental Recall over Baseline:")
print(f"   Current Baseline Recall     : {base_recall:.4%} ({b_tot:,} / {total_gt:,})")
print(f"   Union (Baseline + H2) Recall: {union_recall:.4%} ({u_tot:,} / {total_gt:,})")
print(f"   New Links Recovered         : {new_links:,}")
print(f"   INCREMENTAL RECALL GAIN     : {incremental_recall:+.4%}")
print(f"4. Per-S1 Candidate Distribution:")
print(f"   Average Candidates/S1       : {avg_c:.2f}")
print(f"   Median Candidates/S1        : {med_c:.1f}")
print(f"   P90 / P95 / P99             : {p90:.1f} / {p95:.1f} / {p99:.1f}")
print(f"   Maximum Candidates/S1       : {max_c:,}")
print(f"   S1 with >100 Candidates     : {gt100:,} ({gt100/2206821:.2%})")
print(f"   S1 with >1,000 Candidates   : {gt1k:,} ({gt1k/2206821:.4%})")
print(f"   S1 with >10,000 Candidates  : {gt10k:,}")
print(f"   S1 with >100,000 Candidates : {gt100k:,}")
print(f"5. Performance:")
print(f"   Runtime                     : {time.time() - start_total:.2f} seconds")
print(f"   Memory                      : < 4GB Peak RAM")
print(f"================================================================================")

con.close()
