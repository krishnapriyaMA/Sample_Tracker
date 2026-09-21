"""
One-time (safe to re-run) migration: adds golden_id / shipment_id / dev_id to the
three sample tables, backfills every existing row with a unique ID, then adds a
UNIQUE index on each column.

Run from the project root (same folder that contains the `app` package):

    python migrate_add_sample_ids.py

Why this is needed: Base.metadata.create_all() only creates missing tables. It
never adds columns to a table that already exists, so the live database has to
be altered explicitly.

Safe to re-run: columns/indexes are created with IF NOT EXISTS and only rows
whose ID is still NULL get a new one -- existing IDs are never changed. If you
bulk-load rows with raw SQL later (e.g. the CSV migration script), re-run this
to give those rows IDs.

Everything runs in a single transaction: if anything fails, nothing is applied.
"""
from sqlalchemy import text

from app.database import engine
from app.models import new_golden_id, new_shipment_id, new_dev_id

TARGETS = [
    # (table, column, generator)
    ("golden_samples", "golden_id", new_golden_id),
    ("shipment_samples", "shipment_id", new_shipment_id),
    ("development_samples", "dev_id", new_dev_id),
]


def main() -> None:
    with engine.begin() as conn:
        for table, column, generate in TARGETS:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} VARCHAR(20)"))

            used = set(
                conn.execute(text(f"SELECT {column} FROM {table} WHERE {column} IS NOT NULL")).scalars()
            )
            missing = conn.execute(text(f"SELECT id FROM {table} WHERE {column} IS NULL")).scalars().all()

            updates = []
            for row_id in missing:
                new_id = generate()
                while new_id in used:
                    new_id = generate()
                used.add(new_id)
                updates.append({"id": row_id, "v": new_id})

            if updates:
                conn.execute(text(f"UPDATE {table} SET {column} = :v WHERE id = :id"), updates)

            # Same name SQLAlchemy uses for Column(unique=True, index=True)
            conn.execute(
                text(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})")
            )
            print(f"{table}.{column}: backfilled {len(updates)} row(s)")

    print("Done.")


if __name__ == "__main__":
    main()