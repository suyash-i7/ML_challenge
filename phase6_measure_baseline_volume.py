import duckdb
import time

print("=" * 80)
print("MEASURING BASELINE BLOCKING CANDIDATE VOLUMES")
print("=" * 80)

DB_PATH = "work/entity_resolution.duckdb"
con = duckdb.connect(DB_PATH)
con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='6GB'")
con.execute("PRAGMA temp_directory='work/duckdb_tmp'")

keys = [
    ("block_name_exact", "Country + Exact Name"),
    ("block_address_exact", "Country + Exact Address"),
    ("block_name_prefix5", "Country + Name Prefix 5"),
    ("block_address_prefix8", "Country + Address Prefix 8"),
]

for col, label in keys:
    start = time.time()
    # Compute candidate pairs using group-by multiplication: sum(cnt_s1 * cnt_s2)
    s2_pairs = con.execute(f"""
        SELECT COALESCE(SUM(s1.c * s2.c), 0)
        FROM (
            SELECT {col}, COUNT(*) AS c 
            FROM train_s1 
            WHERE {col} IS NOT NULL 
            GROUP BY {col}
        ) s1
        JOIN (
            SELECT {col}, COUNT(*) AS c 
            FROM train_s2 
            WHERE {col} IS NOT NULL 
            GROUP BY {col}
        ) s2
        ON s1.{col} = s2.{col}
    """).fetchone()[0]

    s3_pairs = con.execute(f"""
        SELECT COALESCE(SUM(s1.c * s3.c), 0)
        FROM (
            SELECT {col}, COUNT(*) AS c 
            FROM train_s1 
            WHERE {col} IS NOT NULL 
            GROUP BY {col}
        ) s1
        JOIN (
            SELECT {col}, COUNT(*) AS c 
            FROM train_s3 
            WHERE {col} IS NOT NULL 
            GROUP BY {col}
        ) s3
        ON s1.{col} = s3.{col}
    """).fetchone()[0]

    total_pairs = s2_pairs + s3_pairs
    elapsed = time.time() - start
    print(f"\n{label} ({col}):")
    print(f"  S1 x S2 candidate pairs : {s2_pairs:,}")
    print(f"  S1 x S3 candidate pairs : {s3_pairs:,}")
    print(f"  Total candidate pairs   : {total_pairs:,}")
    print(f"  Calculation time        : {elapsed:.2f}s")

con.close()
