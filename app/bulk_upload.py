"""Bulk upload of Golden / Shipment / Development samples from an Excel (.xlsx) or CSV file.

Column headers in the file must match the database column names (case, spaces and
underscores don't matter: "SKU Description" == "sku_description"). Rows are validated
first; if ANY row has a problem nothing is imported and every problem is reported with
its Excel row number, so the user can fix the file and upload it again.
"""
import csv
import io
import re
from datetime import datetime, date

from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy.orm import Session

from .models import GoldenSample, ShipmentSample, DevelopmentSample, ActivityLog

MAX_ROWS = 5000
MAX_BYTES = 10 * 1024 * 1024

# (column name, kind). kind: str | date | float | bool
CONFIGS = {
    "golden_samples": {
        "model": GoldenSample, "label": "Golden Samples",
        "required": ["sku"], "detail": "sku",
        "defaults": {"status": "Active"},
        "fields": [
            ("sku", "str"), ("sku_description", "str"), ("item_type", "str"), ("client", "str"),
            ("supplier", "str"), ("vendor_ref", "str"), ("barcode", "str"), ("size", "str"),
            ("location", "str"), ("rack", "str"), ("seal_no", "str"), ("status", "str"),
            ("start_date", "date"), ("value", "float"),
        ],
        "example": {"sku": "253891", "sku_description": "Round rose latch", "client": "ADEO",
                    "supplier": "Weavers", "location": "MANGALAPURI OFFICE", "rack": "B2",
                    "status": "Active", "start_date": "2024-09-01"},
    },
    "shipment_samples": {
        "model": ShipmentSample, "label": "Shipment Samples",
        "required": ["buyer_ref"], "detail": "description",
        "defaults": {},
        "fields": [
            ("buyer_ref", "str"), ("po_no", "str"), ("vendor", "str"), ("barcode", "str"),
            ("rack_no", "str"), ("description", "str"), ("buyer", "str"), ("date", "date"),
            ("finish", "str"), ("location", "str"), ("disposed", "bool"),
        ],
        "example": {"buyer_ref": "326450", "po_no": "120004", "vendor": "BKG Overseas",
                    "description": "GLASS VASE", "buyer": "OBI", "rack_no": "B-1",
                    "date": "2026-05-15", "finish": "GREEN", "location": "Delhi HO"},
    },
    "development_samples": {
        "model": DevelopmentSample, "label": "Development Samples",
        "required": ["title"], "detail": "title",
        "defaults": {"status": "Pending Return"},
        "fields": [
            ("title", "str"), ("sku_description", "str"), ("client", "str"), ("supplier_name", "str"),
            ("responsible_merchandiser", "str"), ("from_location", "str"), ("to_location", "str"),
            ("sent_date", "date"), ("return_date", "date"), ("status", "str"), ("value", "float"),
            ("remarks", "str"), ("product_link", "str"), ("tracking_url", "str"),
        ],
        "example": {"title": "3700638", "sku_description": "Utility cart", "client": "Lowes",
                    "supplier_name": "DLJM", "from_location": "Supplier", "to_location": "J&J North",
                    "sent_date": "2026-07-01", "return_date": "2026-07-31", "status": "Pending Return"},
    },
}

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y",
                "%Y/%m/%d", "%d-%b-%Y", "%m/%d/%Y")
TRUE_WORDS = {"1", "true", "yes", "y", "disposed"}
FALSE_WORDS = {"0", "false", "no", "n", ""}


def _norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(h or "").strip().lower()).strip("_")


def _to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():   # Excel stores 834857 as 834857.0
        return str(int(v))
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _to_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    s = str(v).strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError(f"'{s}' is not a valid date (use YYYY-MM-DD)")


def _read_rows(upload: UploadFile):
    """Returns (headers, rows) where rows is a list of (excel_row_number, [cell values])."""
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("File is too large (limit 10 MB).")
    name = (upload.filename or "").lower()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        all_rows = [list(r) for r in csv.reader(io.StringIO(text))]
    elif name.endswith((".xlsx", ".xlsm")):
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ValueError("Could not open the file. Please upload a valid .xlsx file.")
        all_rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
    else:
        raise ValueError("Unsupported file type. Please upload an .xlsx or .csv file.")
    if not all_rows:
        raise ValueError("The file is empty.")
    headers = all_rows[0]
    rows = [(i + 2, r) for i, r in enumerate(all_rows[1:])
            if any(c not in (None, "") and str(c).strip() != "" for c in r)]
    return headers, rows


def process_upload(kind: str, upload: UploadFile, user, db: Session) -> dict:
    cfg = CONFIGS[kind]
    model = cfg["model"]
    fields = dict(cfg["fields"])
    try:
        headers, rows = _read_rows(upload)
    except ValueError as e:
        return {"ok": False, "created": 0, "errors": [str(e)], "warnings": []}

    col_index, ignored = {}, []
    for i, h in enumerate(headers):
        key = _norm_header(h)
        if not key:
            continue
        if key in fields and key not in col_index:
            col_index[key] = i
        else:
            ignored.append(str(h).strip())
    errors = []
    for req in cfg["required"]:
        if req not in col_index:
            errors.append(f"Missing required column '{req}'.")
    if not rows:
        errors.append("No data rows found under the header row.")
    if len(rows) > MAX_ROWS:
        errors.append(f"Too many rows ({len(rows)}); the limit is {MAX_ROWS} per upload.")
    if errors:
        return {"ok": False, "created": 0, "errors": errors, "warnings": []}

    records = []
    for rownum, cells in rows:
        rec, row_errs = {}, []
        for name, idx in col_index.items():
            raw = cells[idx] if idx < len(cells) else None
            try:
                k = fields[name]
                if k == "str":
                    val = _to_str(raw)
                    maxlen = getattr(model, name).type.length
                    if maxlen and len(val) > maxlen:
                        raise ValueError(f"'{name}' is too long ({len(val)} > {maxlen} characters)")
                    rec[name] = val or None
                elif k == "date":
                    rec[name] = _to_date(raw)
                elif k == "float":
                    s = _to_str(raw)
                    try:
                        rec[name] = float(s.replace(",", "")) if s else None
                    except ValueError:
                        raise ValueError(f"'{name}' must be a number, got '{s}'")
                elif k == "bool":
                    s = _to_str(raw).lower()
                    if s in TRUE_WORDS:
                        rec[name] = True
                    elif s in FALSE_WORDS:
                        rec[name] = False
                    else:
                        raise ValueError(f"'{name}' must be Yes/No")
            except ValueError as e:
                msg = str(e)
                if name in msg:
                    row_errs.append(msg)
                else:
                    row_errs.append(f"{name}: {msg}")
        for req in cfg["required"]:
            if not rec.get(req):
                row_errs.append(f"'{req}' is required")
        for k, v in cfg["defaults"].items():
            if not rec.get(k):
                rec[k] = v
        if row_errs:
            errors.append(f"Row {rownum}: " + "; ".join(row_errs))
        else:
            records.append(rec)
        if len(errors) >= 50:
            errors.append("…stopped after 50 problems. Fix these and upload again.")
            break

    warnings = []
    if ignored:
        warnings.append("Ignored columns (not in the database): " + ", ".join(ignored))
    if errors:
        return {"ok": False, "created": 0, "errors": errors, "warnings": warnings}

    page = {"golden_samples": "golden_samples", "shipment_samples": "shipment_samples",
            "development_samples": "development_samples"}[kind]
    objs = [model(**rec, created_by=user.id) for rec in records]
    db.add_all(objs)
    db.flush()
    for obj in objs:
        db.add(ActivityLog(user_email=user.email, page=page, action="created", record_id=obj.id,
                           detail=(getattr(obj, cfg["detail"]) or "bulk upload")))
    db.commit()
    return {"ok": True, "created": len(objs), "errors": [], "warnings": warnings}


def template_response(kind: str) -> StreamingResponse:
    cfg = CONFIGS[kind]
    wb = Workbook()
    ws = wb.active
    ws.title = cfg["label"][:31]
    names = [n for n, _ in cfg["fields"]]
    ws.append(names)
    ws.append([cfg["example"].get(n) for n in names])
    for i, n in enumerate(names, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, len(n) + 4)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{kind}_upload_template.xlsx"'},
    )


# Expose each upload's column list to the templates (used by _bulk_upload.html)
from .templating import templates as _templates  # noqa: E402
for _kind, _cfg in CONFIGS.items():
    _templates.env.globals[f"bulk_cols_{_kind}"] = [n for n, _ in _cfg["fields"]]