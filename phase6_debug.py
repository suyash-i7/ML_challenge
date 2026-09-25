import duckdb

con = duckdb.connect("work/entity_resolution.duckdb")

print("\nADDRESS NUMBER EXTRACTION")
print("=" * 60)

rows = con.execute("""
    SELECT
        entity_id,
        address_norm,
        regexp_extract(address_norm, '\\d+', 0) AS addr_num
    FROM train_s1
    LIMIT 10
""").fetchall()

for row in rows:
    print(row)


print("\nADDRESS NUMBER COUNTS")
print("=" * 60)

for table in ["train_s1", "train_s2", "train_s3"]:

    result = con.execute(f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE regexp_extract(address_norm, '\\d+', 0) <> ''
    """).fetchone()[0]

    print(f"{table}: {result:,}")


print("\nS1 × S2 ADDRESS NUMBER JOIN")
print("=" * 60)

result = con.execute("""
    SELECT COUNT(*)
    FROM train_s1 a
    JOIN train_s2 b
      ON regexp_extract(a.address_norm, '\\d+', 0)
       = regexp_extract(b.address_norm, '\\d+', 0)
    WHERE regexp_extract(a.address_norm, '\\d+', 0) <> ''
""").fetchone()[0]

print(f"Candidate pairs: {result:,}")


print("\nS1 × S2 ADDRESS NUMBER + COUNTRY")
print("=" * 60)

result = con.execute("""
    SELECT COUNT(*)
    FROM train_s1 a
    JOIN train_s2 b
      ON a.country = b.country
     AND regexp_extract(a.address_norm, '\\d+', 0)
       = regexp_extract(b.address_norm, '\\d+', 0)
    WHERE regexp_extract(a.address_norm, '\\d+', 0) <> ''
""").fetchone()[0]

print(f"Candidate pairs: {result:,}")

print("\nDONE")