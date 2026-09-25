from pathlib import Path
import duckdb
import time

# ============================================================
# PHASE 4
# Normalize source data + create blocking keys
# ============================================================

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "dataset"
WORK = ROOT / "work"

WORK.mkdir(exist_ok=True)

DB_PATH = WORK / "entity_resolution.duckdb"

con = duckdb.connect(str(DB_PATH))

# Use multiple CPU threads
con.execute("PRAGMA threads=4")

print("=" * 70)
print("PHASE 4 — NORMALIZATION + BLOCKING PREPARATION")
print("=" * 70)


def build_parquet(input_file, output_file, label):
    print(f"\n[{label}]")
    print(f"Input : {input_file}")
    print(f"Output: {output_file}")

    start = time.time()

    input_path = input_file.as_posix()
    output_path = output_file.as_posix()

    query = f"""
    COPY (
        SELECT
            entity_id,
            business_name,
            business_address,
            country,

            -- Country normalization
            lower(trim(country)) AS country_norm,

            -- Business name normalization
            trim(
                regexp_replace(
                    regexp_replace(
                        lower(
                            replace(
                                coalesce(business_name, ''),
                                '&',
                                ' and '
                            )
                        ),
                        '[[:punct:]]+',
                        ' ',
                        'g'
                    ),
                    '\\s+',
                    ' ',
                    'g'
                )
            ) AS name_norm,

            -- Address normalization
            trim(
                regexp_replace(
                    regexp_replace(
                        lower(
                            replace(
                                coalesce(business_address, ''),
                                '&',
                                ' and '
                            )
                        ),
                        '[[:punct:]]+',
                        ' ',
                        'g'
                    ),
                    '\\s+',
                    ' ',
                    'g'
                )
            ) AS address_norm

        FROM read_csv_auto(
            '{input_path}',
            delim='\\t',
            header=true
        )
    )
    TO '{output_path}'
    (
        FORMAT PARQUET,
        COMPRESSION ZSTD
    );
    """

    con.execute(query)

    elapsed = time.time() - start

    count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{output_path}')"
    ).fetchone()[0]

    print(f"Rows   : {count:,}")
    print(f"Time   : {elapsed:.1f} seconds")


# ============================================================
# TRAIN DATA
# ============================================================

build_parquet(
    DATASET / "train" / "train_source1.tsv",
    WORK / "train_source1.parquet",
    "TRAIN SOURCE 1"
)

build_parquet(
    DATASET / "train" / "train_source2.tsv",
    WORK / "train_source2.parquet",
    "TRAIN SOURCE 2"
)

build_parquet(
    DATASET / "train" / "train_source3.tsv",
    WORK / "train_source3.parquet",
    "TRAIN SOURCE 3"
)


# ============================================================
# TEST DATA
# ============================================================

build_parquet(
    DATASET / "test" / "test_source1.tsv",
    WORK / "test_source1.parquet",
    "TEST SOURCE 1"
)

build_parquet(
    DATASET / "test" / "test_source2.tsv",
    WORK / "test_source2.parquet",
    "TEST SOURCE 2"
)

build_parquet(
    DATASET / "test" / "test_source3.tsv",
    WORK / "test_source3.parquet",
    "TEST SOURCE 3"
)


# ============================================================
# CREATE INDEXED VIEWS WITH BLOCKING KEYS
# ============================================================

print("\n" + "=" * 70)
print("CREATING BLOCKING KEYS")
print("=" * 70)


def create_blocking_view(parquet_file, view_name):

    path = parquet_file.as_posix()

    con.execute(f"""
        CREATE OR REPLACE VIEW {view_name} AS
        SELECT
            *,

            -- Exact normalized name
            CASE
                WHEN name_norm <> ''
                THEN country_norm || '|' || name_norm
                ELSE NULL
            END AS block_name_exact,

            -- Exact normalized address
            CASE
                WHEN address_norm <> ''
                THEN country_norm || '|' || address_norm
                ELSE NULL
            END AS block_address_exact,

            -- First 5 characters of normalized name
            CASE
                WHEN length(name_norm) >= 5
                THEN country_norm || '|' || substr(name_norm, 1, 5)
                ELSE NULL
            END AS block_name_prefix5,

            -- First 8 characters of normalized address
            CASE
                WHEN length(address_norm) >= 8
                THEN country_norm || '|' || substr(address_norm, 1, 8)
                ELSE NULL
            END AS block_address_prefix8,

            -- Postal/ZIP/PIN-like number
            CASE
                WHEN regexp_extract(
                    address_norm,
                    '[0-9]{{5,6}}'
                ) <> ''
                THEN country_norm || '|' ||
                     regexp_extract(
                         address_norm,
                         '[0-9]{{5,6}}'
                     )
                ELSE NULL
            END AS block_postal

        FROM read_parquet('{path}')
    """)


create_blocking_view(
    WORK / "train_source1.parquet",
    "train_s1"
)

create_blocking_view(
    WORK / "train_source2.parquet",
    "train_s2"
)

create_blocking_view(
    WORK / "train_source3.parquet",
    "train_s3"
)

create_blocking_view(
    WORK / "test_source1.parquet",
    "test_s1"
)

create_blocking_view(
    WORK / "test_source2.parquet",
    "test_s2"
)

create_blocking_view(
    WORK / "test_source3.parquet",
    "test_s3"
)


# ============================================================
# BASIC BLOCK STATISTICS
# ============================================================

print("\n" + "=" * 70)
print("BLOCKING STATISTICS")
print("=" * 70)


for view in ["train_s1", "train_s2", "train_s3"]:

    print(f"\n--- {view} ---")

    for key in [
        "block_name_exact",
        "block_address_exact",
        "block_name_prefix5",
        "block_address_prefix8",
        "block_postal"
    ]:

        result = con.execute(f"""
            SELECT
                COUNT(*) AS rows,
                COUNT(DISTINCT {key}) AS unique_blocks,
                AVG(cnt) AS avg_block_size,
                MAX(cnt) AS max_block_size
            FROM (
                SELECT
                    {key},
                    COUNT(*) AS cnt
                FROM {view}
                WHERE {key} IS NOT NULL
                GROUP BY {key}
            )
        """).fetchone()

        print(
            f"{key:25} "
            f"rows={result[0]:>12,} "
            f"blocks={result[1]:>12,} "
            f"avg={result[2]:>8.2f} "
            f"max={result[3]:>8,}"
        )


print("\n" + "=" * 70)
print("PHASE 4 COMPLETE")
print("=" * 70)

print("\nCreated:")
print(f"  {WORK / 'entity_resolution.duckdb'}")
print(f"  {WORK / 'train_source1.parquet'}")
print(f"  {WORK / 'train_source2.parquet'}")
print(f"  {WORK / 'train_source3.parquet'}")
print(f"  {WORK / 'test_source1.parquet'}")
print(f"  {WORK / 'test_source2.parquet'}")
print(f"  {WORK / 'test_source3.parquet'}")

con.close()