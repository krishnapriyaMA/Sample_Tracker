"""
One-time migration: add report_type/client to the existing manager_contacts
table, and replace the old single-column unique constraint on email with a
composite one on (email, report_type, client).

WHY THIS IS NEEDED
------------------
The old table only had (id, name, email) with email UNIQUE. jobs.py and
admin.py were written assuming report_type and client columns already
existed. Just editing models.py doesn't touch the live database -- SQLAlchemy
only auto-creates tables that don't exist yet (Base.metadata.create_all()),
it never ALTERs an existing table. Without running this migration, every
job in jobs.py that does db.query(ManagerContact).filter_by(report_type=...)
will keep raising an error, because that column won't actually exist in
the database even though models.py now declares it in Python.

WHAT THIS DOES, STEP BY STEP
-----------------------------
1. Adds report_type as nullable first (never add a NOT NULL column with no
   default to a table that already has rows -- it will fail outright on most
   engines, or silently do the wrong thing on the ones that allow it).
2. Backfills every existing row's report_type to 'development' -- this is
   the only report type your OLD table's data could have possibly meant,
   since the prior schema only ever supported Development Samples contacts.
   Existing rows are NOT deleted or touched otherwise.
3. Backfills client to NULL for all existing rows (they become the flat
   "development fallback" recipients list -- exactly matching how
   admin.py's development_contacts filter already interprets
   "report_type == development and no client").
4. Only after backfilling does it enforce NOT NULL on report_type.
5. Drops the old single-column unique constraint/index on email (if it
   exists under a database-specific name -- see the try/except) and adds
   the new composite unique constraint on (email, report_type, client).

BEFORE RUNNING
--------------
- BACK UP YOUR DATABASE FIRST. This is a schema-altering migration.
- Confirm which engine you're on (SQLite vs Postgres/MySQL) -- see the
  branches below. SQLite has limited ALTER TABLE support, so its path
  rebuilds the table; Postgres/MySQL use plain ALTER TABLE statements.
- Run this once. It is not designed to be safely re-run if it partially
  succeeds -- inspect the table state before re-running.

USAGE
-----
    python migrate_manager_contacts.py
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, inspect

load_dotenv()

# Reads the same DATABASE_URL your app's database.py uses (from .env).
# We deliberately do NOT fall back to sqlite:///./dev.db here the way the
# app does -- if DATABASE_URL isn't set, this script should stop rather
# than silently migrating the wrong (empty, local) database.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    print(
        "DATABASE_URL is not set (checked environment and .env). "
        "Refusing to guess -- set it to the same Postgres URL your app uses "
        "before running this migration.",
        file=sys.stderr,
    )
    sys.exit(1)


def existing_unique_constraint_name(inspector, table_name: str, column: str):
    """Find the name of a UNIQUE constraint/index covering exactly this one column,
    so we can drop the right one without guessing a hardcoded name."""
    for uc in inspector.get_unique_constraints(table_name):
        if uc.get("column_names") == [column]:
            return uc.get("name")
    for idx in inspector.get_indexes(table_name):
        if idx.get("unique") and idx.get("column_names") == [column]:
            return idx.get("name")
    return None


def migrate_postgres_or_mysql(engine):
    with engine.begin() as conn:
        inspector = inspect(conn)
        cols = {c["name"] for c in inspector.get_columns("manager_contacts")}

        if "report_type" not in cols:
            conn.execute(text(
                "ALTER TABLE manager_contacts ADD COLUMN report_type VARCHAR(20)"
            ))
        if "client" not in cols:
            conn.execute(text(
                "ALTER TABLE manager_contacts ADD COLUMN client VARCHAR(120)"
            ))

        # Backfill existing rows: the old table only ever served Development
        # Samples contacts, so every pre-existing row becomes a development
        # fallback recipient (client stays NULL).
        conn.execute(text(
            "UPDATE manager_contacts SET report_type = 'development' WHERE report_type IS NULL"
        ))

        # Now safe to enforce NOT NULL with a default for future rows.
        conn.execute(text(
            "ALTER TABLE manager_contacts ALTER COLUMN report_type SET DEFAULT 'development'"
        ))
        conn.execute(text(
            "ALTER TABLE manager_contacts ALTER COLUMN report_type SET NOT NULL"
        ))

        old_uc = existing_unique_constraint_name(inspect(conn), "manager_contacts", "email")
        if old_uc:
            conn.execute(text(f'ALTER TABLE manager_contacts DROP CONSTRAINT "{old_uc}"'))

        conn.execute(text(
            "ALTER TABLE manager_contacts "
            "ADD CONSTRAINT uq_manager_contact_email_type_client "
            "UNIQUE (email, report_type, client)"
        ))
    print("Migration complete (Postgres/MySQL path).")


def migrate_sqlite(engine):
    """SQLite can't drop constraints or reliably ALTER column nullability in
    place, so we rebuild the table: create the new shape, copy the data
    across (backfilling report_type/client), drop the old table, rename."""
    with engine.begin() as conn:
        inspector = inspect(conn)
        cols = {c["name"] for c in inspector.get_columns("manager_contacts")}
        if "report_type" in cols and "client" in cols:
            print("Columns already present -- nothing to do.")
            return

        conn.execute(text("""
            CREATE TABLE manager_contacts_new (
                id INTEGER PRIMARY KEY,
                name VARCHAR(120),
                email VARCHAR(255) NOT NULL,
                report_type VARCHAR(20) NOT NULL DEFAULT 'development',
                client VARCHAR(120),
                UNIQUE (email, report_type, client)
            )
        """))

        # Every existing row is treated as a development-report fallback
        # recipient (client left NULL), matching the only role this table
        # played under the old schema.
        conn.execute(text("""
            INSERT INTO manager_contacts_new (id, name, email, report_type, client)
            SELECT id, name, email, 'development', NULL FROM manager_contacts
        """))

        conn.execute(text("DROP TABLE manager_contacts"))
        conn.execute(text("ALTER TABLE manager_contacts_new RENAME TO manager_contacts"))
    print("Migration complete (SQLite path).")


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    inspector = inspect(engine)

    if "manager_contacts" not in inspector.get_table_names():
        print("manager_contacts table doesn't exist yet -- nothing to migrate. "
              "It will be created fresh with the new schema on next app startup.")
        return

    cols = {c["name"] for c in inspector.get_columns("manager_contacts")}
    if "report_type" in cols and "client" in cols:
        print("report_type and client columns already exist -- nothing to do.")
        return

    if engine.dialect.name == "sqlite":
        migrate_sqlite(engine)
    elif engine.dialect.name in ("postgresql", "mysql"):
        migrate_postgres_or_mysql(engine)
    else:
        print(f"Unsupported dialect '{engine.dialect.name}' -- write a manual "
              f"ALTER TABLE for this engine before proceeding.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()