"""
Migrate Shipment Samples from Excel (Shipment_samples_migr.xlsx) into the
shipment_samples table.

Column mapping applied (source -> ShipmentSample field):
    Buyer                   -> buyer
    Vendor                  -> vendor
    Date                    -> date
    Buyer Ref               -> buyer_ref
    Description             -> description
    Barcode                 -> barcode
    Finish                  -> finish
    Rack no.                -> rack_no
    Shipment samples PO No  -> po_no
    Location                -> location
    Remarks                 -> disposed (True only when Remarks is exactly
                                "Disposed"; the sheet's other values are None
                                and "Not for disposal", both -> False)

NOT mapped (on purpose):
    Title          - sheet only has a sequential row number here; the
                     ShipmentSample model has no `title` column to put it in.
    disposed_at    - not derivable from the sheet (it records only whether
                     something was disposed, not when), so it's left as
                     None/NULL for every migrated row.
    __PowerAppsId__, Item Type, Path - source/export metadata, not app data.

BEHAVIOUR
---------
- Always inserts every row (duplicates and blanks included), matching the
  Golden/Development Samples migrations.
- Each row is inserted inside its own SAVEPOINT (session.begin_nested()), so
  one bad row is rolled back and logged without aborting the rest.
- --dry-run parses and validates everything but writes nothing to the DB.
- Every row's outcome is written to migration_report_shipment_<timestamp>.csv
  next to this script.

USAGE
-----
    python scripts/migrate_shipment_samples.py --file Shipment_samples_migr.xlsx --dry-run
    python scripts/migrate_shipment_samples.py --file Shipment_samples_migr.xlsx

Run from the project root (the directory containing the `app` package), or
from inside scripts/ - PROJECT_ROOT below resolves one level up either way.
"""

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import SessionLocal, engine  # noqa: E402
from app.models import ShipmentSample  # noqa: E402

# Source column name -> ShipmentSample attribute name
COLUMN_MAP = {
    "Buyer": "buyer",
    "Vendor": "vendor",
    "Date": "date",
    "Buyer Ref": "buyer_ref",
    "Description": "description",
    "Barcode": "barcode",
    "Finish": "finish",
    "Rack no.": "rack_no",
    "Shipment samples PO No": "po_no",
    "Location": "location",
    "Remarks": "_remarks",  # not a model field directly - used below to derive `disposed`
}

DATE_FIELDS = {"date"}
STRING_FIELDS = {
    "buyer", "vendor", "buyer_ref", "description", "barcode",
    "finish", "rack_no", "po_no", "location", "_remarks",
}


def clean_str(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def clean_date(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def load_rows(xlsx_path: Path):
    df = pd.read_excel(xlsx_path, sheet_name=0, dtype=object)
    # Normalize headers: strip whitespace so "Buyer Ref " matches "Buyer Ref"
    df.columns = [str(c).strip() for c in df.columns]

    missing = [src for src in COLUMN_MAP if src not in df.columns]
    if missing:
        raise SystemExit(
            f"These expected source columns are missing from the sheet: {missing}\n"
            f"Sheet actually has: {list(df.columns)}"
        )

    rows = []
    for i, raw in enumerate(df.to_dict(orient="records"), start=2):  # row 2 = first data row
        mapped = {}
        for src_col, field in COLUMN_MAP.items():
            value = raw.get(src_col)
            if field in DATE_FIELDS:
                mapped[field] = clean_date(value)
            elif field in STRING_FIELDS:
                mapped[field] = clean_str(value)
            else:
                mapped[field] = value
        rows.append({"_row_num": i, **mapped})
    return rows


def derive_disposed(row: dict) -> dict:
    """Turn the raw Remarks text into the model's `disposed` boolean.
    `disposed_at` is left unset (None) since the sheet doesn't record when
    the disposal actually happened - only that it did."""
    remarks = (row.pop("_remarks", None) or "").strip().lower()
    row["disposed"] = remarks == "disposed"
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", required=True, help="Path to Shipment_samples_migr.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report only; write nothing to the DB")
    parser.add_argument("--created-by", type=int, default=None, help="User id to stamp on created_by, if any")
    args = parser.parse_args()

    xlsx_path = Path(args.file)
    if not xlsx_path.exists():
        raise SystemExit(f"File not found: {xlsx_path}")

    print(f"DB target: {engine.url}")
    print(f"Mode: {'DRY RUN (no writes)' if args.dry_run else 'LIVE'} - always inserts everything (no dedup, no blank skip)")

    rows = load_rows(xlsx_path)
    print(f"Read {len(rows)} data rows from {xlsx_path.name}")

    session = SessionLocal()
    report_rows = []
    inserted = failed = 0

    try:
        for row in rows:
            row_num = row.pop("_row_num")
            row = derive_disposed(row)
            description = row.get("description")

            try:
                with session.begin_nested():  # SAVEPOINT: isolates this row
                    obj = ShipmentSample(**row, created_by=args.created_by)
                    session.add(obj)
                    session.flush()
                    inserted += 1
                    report_rows.append({"row": row_num, "description": description, "outcome": "inserted", "reason": ""})
            except Exception as exc:  # noqa: BLE001
                failed += 1
                report_rows.append({"row": row_num, "description": description, "outcome": "failed", "reason": str(exc)})

        if args.dry_run:
            session.rollback()
            print("\nDry run complete - no changes were written.")
        else:
            session.commit()
            print("\nChanges committed.")

    finally:
        session.close()

    report_path = PROJECT_ROOT / f"migration_report_shipment_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["row", "description", "outcome", "reason"])
        writer.writeheader()
        writer.writerows(report_rows)

    print("\n--- Summary ---")
    print(f"Inserted: {inserted}")
    print(f"Failed:   {failed}")
    print(f"Full report written to: {report_path}")


if __name__ == "__main__":
    main()