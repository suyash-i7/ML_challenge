import duckdb
import time
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
OUTPUT = ROOT / "output"
WORK.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

DB_PATH = str(WORK / "entity_resolution.duckdb")

print("=" * 80)
print("MEMBER 1: CANDIDATE GENERATION PIPELINE")
print("Target: High-Recall Selective Ensemble (88.82% Verified Recall)")
print("=" * 80)

con = duckdb.connect(DB_PATH)
con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute(f"PRAGMA temp_directory='{(WORK / 'duckdb_tmp').as_posix()}'")

def build_candidate_keys(table_name, temp_tbl):
    print(f"Creating enriched blocking keys for {table_name} -> {temp_tbl}...")
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE {temp_tbl} AS
    SELECT
        entity_id,
        country_norm,
        name_norm,
        address_norm,
        block_name_exact,
        block_address_exact,
        block_postal,
        regexp_extract(address_norm, '[0-9]+', 0) AS addr_num,
        split_part(name_norm, ' ', 1) AS w1,
        split_part(name_norm, ' ', 2) AS w2,

        -- Key 3: AddrNum + NamePrefix5
        CASE
            WHEN regexp_extract(address_norm, '[0-9]+', 0) <> '' AND length(name_norm) >= 5
            THEN country_norm || '|' || regexp_extract(address_norm, '[0-9]+', 0) || '|' || substr(name_norm, 1, 5)
            ELSE NULL
        END AS k_addr_name5,

        -- Key 4: AddrNum + Word1
        CASE
            WHEN regexp_extract(address_norm, '[0-9]+', 0) <> '' AND length(split_part(name_norm, ' ', 1)) >= 4
            THEN country_norm || '|' || regexp_extract(address_norm, '[0-9]+', 0) || '|' || split_part(name_norm, ' ', 1)
            ELSE NULL
        END AS k_addr_w1,

        -- Key 5: AddrNum + Word2
        CASE
            WHEN regexp_extract(address_norm, '[0-9]+', 0) <> '' AND length(split_part(name_norm, ' ', 2)) >= 4
            THEN country_norm || '|' || regexp_extract(address_norm, '[0-9]+', 0) || '|' || split_part(name_norm, ' ', 2)
            ELSE NULL
        END AS k_addr_w2,

        -- Key 6: Postal + AddrNum
        CASE
            WHEN block_postal IS NOT NULL AND regexp_extract(address_norm, '[0-9]+', 0) <> ''
            THEN block_postal || '|' || regexp_extract(address_norm, '[0-9]+', 0)
            ELSE NULL
        END AS k_post_addr,

        -- Key 7: Postal + NamePrefix4
        CASE
            WHEN block_postal IS NOT NULL AND length(name_norm) >= 4
            THEN block_postal || '|' || substr(name_norm, 1, 4)
            ELSE NULL
        END AS k_post_name4

    FROM {table_name}
    """)

# ---------------------------------------------------------------------
# 1. Prepare Enriched Blocking Tables for Train
# ---------------------------------------------------------------------
start_t = time.time()
print("\n[1/4] Preparing Train Blocking Tables...")
build_candidate_keys("train_s1", "s1_keys")
build_candidate_keys("train_s2", "s2_keys")
build_candidate_keys("train_s3", "s3_keys")
print(f"Enriched blocking tables prepared in {time.time() - start_t:.2f}s")

# ---------------------------------------------------------------------
# 2. Generate Train Candidate Pairs (S1 x S2 and S1 x S3)
# ---------------------------------------------------------------------
print("\n[2/4] Generating Unique Train Candidate Pairs...")

def generate_pairs_for_source(s_cand_tbl, source_label, out_tbl):
    t0 = time.time()
    print(f"  Generating S1 x {source_label} candidate pairs...")
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE {out_tbl} AS
    SELECT DISTINCT
        s1.entity_id AS s1_id,
        c.entity_id AS cand_id,
        '{source_label}' AS cand_source,
        -- Rule flags for Member 2 features
        (s1.block_name_exact IS NOT NULL AND s1.block_name_exact = c.block_name_exact) AS match_exact_name,
        (s1.block_address_exact IS NOT NULL AND s1.block_address_exact = c.block_address_exact) AS match_exact_addr,
        (s1.k_addr_name5 IS NOT NULL AND s1.k_addr_name5 = c.k_addr_name5) AS match_addr_name5,
        (
            (s1.k_addr_w1 IS NOT NULL AND s1.k_addr_w1 = c.k_addr_w2) OR
            (s1.k_addr_w2 IS NOT NULL AND s1.k_addr_w2 = c.k_addr_w1)
        ) AS match_cross_word,
        (s1.k_addr_w2 IS NOT NULL AND s1.k_addr_w2 = c.k_addr_w2) AS match_addr_w2,
        (s1.k_post_addr IS NOT NULL AND s1.k_post_addr = c.k_post_addr) AS match_post_addr,
        (s1.k_post_name4 IS NOT NULL AND s1.k_post_name4 = c.k_post_name4) AS match_post_name4
    FROM s1_keys s1
    JOIN {s_cand_tbl} c ON (
        (s1.block_name_exact IS NOT NULL AND s1.block_name_exact = c.block_name_exact)
        OR (s1.block_address_exact IS NOT NULL AND s1.block_address_exact = c.block_address_exact)
        OR (s1.k_addr_name5 IS NOT NULL AND s1.k_addr_name5 = c.k_addr_name5)
        OR (s1.k_addr_w1 IS NOT NULL AND s1.k_addr_w1 = c.k_addr_w2)
        OR (s1.k_addr_w2 IS NOT NULL AND s1.k_addr_w2 = c.k_addr_w1)
        OR (s1.k_addr_w2 IS NOT NULL AND s1.k_addr_w2 = c.k_addr_w2)
        OR (s1.k_post_addr IS NOT NULL AND s1.k_post_addr = c.k_post_addr)
        OR (s1.k_post_name4 IS NOT NULL AND s1.k_post_name4 = c.k_post_name4)
    )
    """)
    cnt = con.execute(f"SELECT COUNT(*) FROM {out_tbl}").fetchone()[0]
    print(f"  S1 x {source_label} complete: {cnt:,} unique pairs in {time.time() - t0:.2f}s")
    return cnt

cnt_s2 = generate_pairs_for_source("s2_keys", "S2", "pairs_s2")
cnt_s3 = generate_pairs_for_source("s3_keys", "S3", "pairs_s3")

# Combine S2 and S3 candidate pairs into Parquet for Member 2
print("\n[3/4] Exporting Pairwise Parquet for Member 2 (work/train_candidate_pairs.parquet)...")
train_pairs_parquet = (WORK / "train_candidate_pairs.parquet").as_posix()
con.execute(f"""
COPY (
    SELECT * FROM pairs_s2
    UNION ALL
    SELECT * FROM pairs_s3
) TO '{train_pairs_parquet}' (FORMAT PARQUET, COMPRESSION ZSTD);
""")
tot_train_pairs = con.execute(f"SELECT COUNT(*) FROM read_parquet('{train_pairs_parquet}')").fetchone()[0]
print(f"Exported {tot_train_pairs:,} candidate pairs to {train_pairs_parquet}")

# ---------------------------------------------------------------------
# 3. Export Member 1 Aggregated TSV (work/train_candidates.tsv)
# Schema: source1_entity_id, candidate_entity_ids (comma-separated)
# Exactly one row per S1 entity
# ---------------------------------------------------------------------
print("\n[4/4] Aggregating and Exporting work/train_candidates.tsv...")
train_candidates_tsv = (WORK / "train_candidates.tsv").as_posix()

con.execute(f"""
COPY (
    WITH all_pairs AS (
        SELECT s1_id, cand_id FROM pairs_s2
        UNION ALL
        SELECT s1_id, cand_id FROM pairs_s3
    ),
    grouped AS (
        SELECT
            s1_id,
            string_agg(cand_id, ',') AS candidate_entity_ids
        FROM all_pairs
        GROUP BY s1_id
    )
    SELECT
        s1.entity_id AS source1_entity_id,
        COALESCE(g.candidate_entity_ids, '') AS candidate_entity_ids
    FROM train_s1 s1
    LEFT JOIN grouped g ON s1.entity_id = g.s1_id
    ORDER BY s1.entity_id
) TO '{train_candidates_tsv}' (FORMAT CSV, DELIMITER '\t', HEADER true);
""")

tsv_lines = con.execute(f"SELECT COUNT(*) FROM read_csv_auto('{train_candidates_tsv}', delim='\t', header=true)").fetchone()[0]
print(f"Exported work/train_candidates.tsv with {tsv_lines:,} rows (Exact match with S1 count: {tsv_lines == 2206821})")

con.close()
print("\nTrain Candidate Generation Pipeline Complete.")
