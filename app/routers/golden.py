import os
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GoldenSample, ActivityLog
from ..auth import require_page_view, require_page_edit, can_edit as _can_edit
from ..email_utils import notify_status_change
from ..templating import templates

router = APIRouter(prefix="/golden-samples", tags=["golden"])
PAGE = "golden_samples"
UPLOAD_DIR = "app/static/uploads"
RENEWAL_WINDOW_DAYS = 365 * 2


def save_upload(file: UploadFile | None) -> str | None:
    if not file or not file.filename:
        return None
    ext = os.path.splitext(file.filename)[1]
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(path, "wb") as f:
        f.write(file.file.read())
    return f"/static/uploads/{name}"


def parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def parse_float(s: str):
    """Safely parse the Value field. Returns None for empty/invalid input
    instead of letting a bad value crash the request with a 500."""
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


@router.get("", response_class=HTMLResponse)
def list_view(
    request: Request,
    q: str = "",
    client: str = "",
    status: str = "",
    renewal_due: str = "",
    user=Depends(require_page_view(PAGE)),
    db: Session = Depends(get_db),
):
    query = db.query(GoldenSample)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (GoldenSample.sku.ilike(like)) |
            (GoldenSample.sku_description.ilike(like))
        )
    if client:
        query = query.filter(GoldenSample.client == client)
    if status:
        query = query.filter(GoldenSample.status == status)
    items = query.order_by(GoldenSample.updated_at.desc()).all()

    cutoff = datetime.utcnow() - timedelta(days=RENEWAL_WINDOW_DAYS)
    for it in items:
        it.renewal_due = bool(it.start_date and it.start_date < cutoff)
    if renewal_due == "1":
        items = [it for it in items if it.renewal_due]

    clients = [c[0] for c in db.query(GoldenSample.client).distinct() if c[0]]
    statuses = [s[0] for s in db.query(GoldenSample.status).distinct() if s[0]]
    return templates.TemplateResponse("golden_samples.html", {
        "request": request, "items": items, "user": user,
        "clients": clients, "statuses": statuses,
        "q": q, "client": client, "status": status, "renewal_due": renewal_due,
        "can_edit": _can_edit(user, PAGE, db),
    })


@router.post("/create")
def create(
    request: Request,
    sku: str = Form(""), sku_description: str = Form(""), item_type: str = Form(""),
    client: str = Form(""), supplier: str = Form(""), vendor_ref: str = Form(""),
    barcode: str = Form(""), size: str = Form(""), location: str = Form(""),
    rack: str = Form(""), seal_no: str = Form(""), status: str = Form("Active"),
    start_date: str = Form(""), value: str = Form(""), image: UploadFile = File(None),
    user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db),
):
    item = GoldenSample(
        sku=sku, sku_description=sku_description, item_type=item_type, client=client,
        supplier=supplier, vendor_ref=vendor_ref, barcode=barcode, size=size, location=location,
        rack=rack, seal_no=seal_no, status=status, start_date=parse_date(start_date),
        value=parse_float(value),
        image_path=save_upload(image), created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.add(ActivityLog(user_email=user.email, page=PAGE, action="created", record_id=item.id, detail=sku))
    db.commit()
    return RedirectResponse("/golden-samples", status_code=303)


@router.post("/{item_id}/update")
def update(
    item_id: int, request: Request,
    sku: str = Form(""), sku_description: str = Form(""), item_type: str = Form(""),
    client: str = Form(""), supplier: str = Form(""), vendor_ref: str = Form(""),
    barcode: str = Form(""), size: str = Form(""), location: str = Form(""),
    rack: str = Form(""), seal_no: str = Form(""), status: str = Form("Active"),
    start_date: str = Form(""), value: str = Form(""), image: UploadFile = File(None),
    user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db),
):
    item = db.get(GoldenSample, item_id)
    if not item:
        return RedirectResponse("/golden-samples", status_code=303)
    old_status = item.status
    item.sku, item.sku_description, item.item_type = sku, sku_description, item_type
    item.client, item.supplier, item.vendor_ref = client, supplier, vendor_ref
    item.barcode, item.size, item.location = barcode, size, location
    item.rack, item.seal_no, item.status = rack, seal_no, status
    item.start_date = parse_date(start_date)
    item.value = parse_float(value)
    new_image = save_upload(image)
    if new_image:
        item.image_path = new_image
    item.updated_at = datetime.utcnow()
    db.commit()
    db.add(ActivityLog(user_email=user.email, page=PAGE, action="updated", record_id=item.id, detail=sku))
    if old_status != status:
        db.add(ActivityLog(user_email=user.email, page=PAGE, action="status_changed", record_id=item.id,
                            detail=f"{old_status} -> {status}"))
        notify_status_change("Golden Samples", sku or f"#{item_id}", old_status, status, user.email)
    db.commit()
    return RedirectResponse("/golden-samples", status_code=303)


@router.post("/{item_id}/delete")
def delete(item_id: int, user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db)):
    item = db.get(GoldenSample, item_id)
    if item:
        db.add(ActivityLog(user_email=user.email, page=PAGE, action="deleted", record_id=item_id, detail=item.sku))
        db.delete(item)
        db.commit()
    return RedirectResponse("/golden-samples", status_code=303)