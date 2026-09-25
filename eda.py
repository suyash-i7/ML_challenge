import duckdb

con = duckdb.connect()

files = [
    "dataset/train/train_source1.tsv",
    "dataset/train/train_source2.tsv",
    "dataset/train/train_source3.tsv",
]

# ============================================================
# PHASE 1: BASIC DATASET EDA
# ============================================================

for file in files:
    print("\n" + "=" * 60)
    print(file)
    print("=" * 60)

    rows = con.execute(f"""
        SELECT COUNT(*)
        FROM read_csv_auto('{file}', delim='\\t')
    """).fetchone()[0]

    print("Rows:", rows)

    print("\nCountries:")
    result = con.execute(f"""
        SELECT country, COUNT(*) AS count
        FROM read_csv_auto('{file}', delim='\\t')
        GROUP BY country
        ORDER BY count DESC
    """).fetchall()

    for row in result:
        print(row)

    print("\nMissing values:")
    result = con.execute(f"""
        SELECT
            COUNT(*) FILTER (
                WHERE entity_id IS NULL OR entity_id = ''
            ) AS entity_id_missing,

            COUNT(*) FILTER (
                WHERE business_name IS NULL OR business_name = ''
            ) AS name_missing,

            COUNT(*) FILTER (
                WHERE business_address IS NULL OR business_address = ''
            ) AS address_missing,

            COUNT(*) FILTER (
                WHERE country IS NULL OR country = ''
            ) AS country_missing

        FROM read_csv_auto('{file}', delim='\\t')
    """).fetchone()

    print("entity_id:", result[0])
    print("business_name:", result[1])
    print("business_address:", result[2])
    print("country:", result[3])


# ============================================================
# PHASE 2: GROUND TRUTH ANALYSIS
# ============================================================

print("\n")
print("=" * 60)
print("GROUND TRUTH ANALYSIS")
print("=" * 60)

gt_file = "dataset/train/train_ground_truth.tsv"

# Count matches for every S1
result = con.execute(f"""
    SELECT
        source1_entity_id,
        matched_entity_ids
    FROM read_csv(
        '{gt_file}',
        delim='\\t',
        header=true,
        quote='',
        escape=''
    )
""").fetchall()

match_counts = []

for s1_id, matched_ids in result:
    if matched_ids is None or str(matched_ids).strip() == "":
        count = 0
    else:
        count = len(str(matched_ids).split(","))

    match_counts.append(count)

print("\nTotal Source-1 entities:", len(match_counts))

print("\nMatch count distribution:")

from collections import Counter

distribution = Counter(match_counts)

for count in sorted(distribution):
    print(
        f"{count} matches: "
        f"{distribution[count]} S1 entities"
    )

print("\nSingleton / no-match entities:", distribution.get(0, 0))

print("\nEntities with at least one match:",
      len(match_counts) - distribution.get(0, 0))

print("\nMaximum matches for one S1:",
      max(match_counts))

print("\nTotal ground-truth links:",
      sum(match_counts))

# ============================================================
# PHASE 3: SOURCE-2 vs SOURCE-3 MATCH ANALYSIS
# ============================================================

print("\n")
print("=" * 60)
print("PHASE 3: MATCH SOURCE ANALYSIS")
print("=" * 60)

s2_links = 0
s3_links = 0
both_sources = 0
only_s2 = 0
only_s3 = 0
no_match = 0

with open(gt_file, encoding="utf-8") as f:
    next(f)  # skip header

    for line in f:
        line = line.rstrip("\n")

        if "\t" not in line:
            continue

        s1_id, matched = line.split("\t", 1)

        matched = matched.strip()

        if not matched:
            no_match += 1
            continue

        ids = matched.split(",")

        has_s2 = any(x.startswith("S2-") for x in ids)
        has_s3 = any(x.startswith("S3-") for x in ids)

        s2_count = sum(x.startswith("S2-") for x in ids)
        s3_count = sum(x.startswith("S3-") for x in ids)

        s2_links += s2_count
        s3_links += s3_count

        if has_s2 and has_s3:
            both_sources += 1
        elif has_s2:
            only_s2 += 1
        elif has_s3:
            only_s3 += 1

print("\nS2 links:", s2_links)
print("S3 links:", s3_links)
print("Total links:", s2_links + s3_links)

print("\nS1 entities with matches:")
print("Both S2 + S3:", both_sources)
print("Only S2:", only_s2)
print("Only S3:", only_s3)
print("No matches:", no_match)