"""
Non-destructive schema migration: brings an existing database up to date with
the current app/models.py, WITHOUT dropping the schema or losing data.

USAGE (from the project root, with venv active, .env pointing at your target DB):

    python -m scripts.alter_schema

Safe to run more than once -- every step checks whether it's already been
applied before doing anything, so re-running just confirms everything is in
place and does nothing destructive.

What this does, table by table:

golden_samples
    - Renames `title` -> `sku` if `title` still exists and `sku` doesn't
      (preserves the data -- values just move to the differently-named column).
    - Adds `start_date` and `renewal_acknowledged_at` if missing.

shipment_samples
    - Adds the new columns (buyer_ref, po_no, vendor, barcode, rack_no,
      description, buyer, date, finish, location, disposed, disposed_at) if
      missing. The OLD columns (po, sku, client, status, manufacturing_date,
      sent_date) are left in place rather than dropped -- they're just no
      longer used by the app, so any old data in them is preserved but
      inert. Run scripts/migrate_shipment_samples.py separately if you want
      that old data copied into the new columns.

development_samples
    - Adds `responsible_merchandiser` if missing.

users / user_page_permissions / client_contacts / manager_contacts / activity_log
    - These are created automatically by Base.metadata.create_all() if they
      don't exist yet -- no ALTER needed, since create_all only ever adds
      missing TABLES, never touches existing ones. This script calls that
      after the ALTERs below, so a completely fresh database still works
      too (nothing to alter, everything just gets created).
"""
import sys

sys.path.insert(0, ".")  # run from project root

from sqlalchemy import text, inspect
from app.database import engine, Base
from app import models  # noqa: F401 -- import so all models register with Base


def column_exists(inspector, table: str, column: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def table_exists(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def main():
    log = []

    with engine.begin() as conn:
        inspector = inspect(conn)

        # --- golden_samples: title -> sku rename ---------------------------
        if table_exists(inspector, "golden_samples"):
            has_title = column_exists(inspector, "golden_samples", "title")
            has_sku = column_exists(inspector, "golden_samples", "sku")
            if has_title and not has_sku:
                conn.execute(text("ALTER TABLE golden_samples RENAME COLUMN title TO sku"))
                log.append("golden_samples: renamed title -> sku (data preserved)")
            elif has_sku:
                log.append("golden_samples: sku column already present, skipped rename")
            else:
                log.append("golden_samples: neither title nor sku found -- table may not exist yet, will be created below")

            if not column_exists(inspector.info_cache and inspect(conn) or inspect(conn), "golden_samples", "start_date"):
                conn.execute(text("ALTER TABLE golden_samples ADD COLUMN IF NOT EXISTS start_date TIMESTAMP"))
                log.append("golden_samples: added start_date")
            if not column_exists(inspect(conn), "golden_samples", "renewal_acknowledged_at"):
                conn.execute(text("ALTER TABLE golden_samples ADD COLUMN IF NOT EXISTS renewal_acknowledged_at TIMESTAMP"))
                log.append("golden_samples: added renewal_acknowledged_at")

        # --- shipment_samples: add the new field set ------------------------
        if table_exists(inspector, "shipment_samples"):
            new_columns = {
                "buyer_ref": "VARCHAR(120)",
                "po_no": "VARCHAR(120)",
                "vendor": "VARCHAR(120)",
                "barcode": "VARCHAR(120)",
                "rack_no": "VARCHAR(60)",
                "description": "VARCHAR(255)",
                "buyer": "VARCHAR(120)",
                "date": "TIMESTAMP",
                "finish": "VARCHAR(120)",
                "location": "VARCHAR(120)",
                "disposed": "BOOLEAN DEFAULT FALSE",
                "disposed_at": "TIMESTAMP",
            }
            for col, coltype in new_columns.items():
                if not column_exists(inspect(conn), "shipment_samples", col):
                    conn.execute(text(f"ALTER TABLE shipment_samples ADD COLUMN IF NOT EXISTS {col} {coltype}"))
                    log.append(f"shipment_samples: added {col}")

        # --- development_samples: add responsible_merchandiser --------------
        if table_exists(inspector, "development_samples"):
            if not column_exists(inspect(conn), "development_samples", "responsible_merchandiser"):
                conn.execute(text(
                    "ALTER TABLE development_samples ADD COLUMN IF NOT EXISTS responsible_merchandiser VARCHAR(120)"
                ))
                log.append("development_samples: added responsible_merchandiser")

    # New tables (client_contacts, manager_contacts, user_page_permissions,
    # activity_log, users) get created here if they don't exist yet.
    # create_all() never touches tables that already exist, so this is safe
    # to run alongside the ALTERs above every time.
    Base.metadata.create_all(bind=engine)
    log.append("Base.metadata.create_all() run -- any missing tables created")

    print("\n".join(log) if log else "Nothing to do -- schema already matches models.py.")
    print("\nDone. Your existing data was not touched or deleted.")


if __name__ == "__main__":
    main()
