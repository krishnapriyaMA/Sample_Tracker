"""
add_missing_columns.py

NON-DESTRUCTIVE. Compares the live database tables against the current
app/models.py and adds ONLY the columns that are missing -- no dropping,
no altering existing columns, no touching existing rows. Safe to run
against a database that already has real data in it.

This is the fix for: "table was created from an older models.py and is
now missing columns the ORM expects" -- without the data loss of
recreate_tables.py.

WHAT IT DOES NOT DO
--------------------
- Does not remove columns that exist in the table but not in models.py
  (e.g. leftovers from an old schema) -- those are left alone.
- Does not change an existing column's type, nullability, or default if
  it already exists, even if models.py now says something different.
- Does not create missing TABLES -- if an entire table doesn't exist
  yet, this reports it but does not create it (run this after tables
  exist; ask if you need a "create missing tables only, don't touch
  existing ones" variant instead).
- Every added column is created NULLABLE, regardless of what models.py
  says, even if the model marks it non-nullable -- adding a NOT NULL
  column to a table that already has rows would fail (existing rows
  would violate it) unless a default is supplied. Tighten the
  constraint by hand in psql/pgAdmin afterward if you need it enforced,
  once you've confirmed the new column is backfilled.

USAGE (from project root):
    python scripts\\add_missing_columns.py            # apply changes
    python scripts\\add_missing_columns.py --dry-run   # show what would run, change nothing
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text

from app.database import engine, Base
import app.models  # noqa: F401  -- registers every model class on Base.metadata


def main():
    parser = argparse.ArgumentParser(description="Add missing columns to match models.py, without dropping anything.")
    parser.add_argument("--dry-run", action="store_true", help="Show the ALTER statements without running them.")
    args = parser.parse_args()

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    statements = []
    missing_tables = []

    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            missing_tables.append(table_name)
            continue

        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            stmt = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}'
            statements.append((table_name, column.name, stmt))

    if missing_tables:
        print("These tables don't exist at all yet (not created by this script):")
        for t in missing_tables:
            print(f"  - {t}")
        print()

    if not statements:
        print("No missing columns on any existing table -- schema already matches models.py.")
        return

    print(f"{'Would add' if args.dry_run else 'Adding'} {len(statements)} column(s):")
    for table_name, col_name, stmt in statements:
        print(f"  [{table_name}] {col_name}")
        print(f"    {stmt}")

    if args.dry_run:
        print("\nDry run -- nothing changed.")
        return

    with engine.begin() as conn:
        for table_name, col_name, stmt in statements:
            conn.execute(text(stmt))

    print("\nDone. Existing data untouched -- only new (nullable) columns were added.")


if __name__ == "__main__":
    main()