import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DevelopmentSample, ActivityLog
from ..auth import require_page_view, require_page_edit, can_edit as _can_edit
from ..email_utils import notify_status_change
from ..templating import templates

router = APIRouter(prefix="/development-samples", tags=["development"])
PAGE = "development_samples"
UPLOAD_DIR = "app/static/uploads"

# Baseline options always offered, even before any record uses them.
# Any additional values already present in the database are appended
# automatically so the dropdown stays in sync with real data.
DEFAULT_CLIENTS = ["Lowes", "Topps", "Wickes", "Adeo", "OBI"]
DEFAULT_LOCATIONS = ["Supplier", "J&J North", "J&J North QA", "J&J West", "J&J Coimbatore"]


def merge_options(defaults: list[str], db_values: list[str]) -> list[str]:
    extra = sorted({v for v in db_values if v and v not in defaults})
    return defaults + extra


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
    request: Request, q: str = "", client: str = "", status: str = "",
    user=Depends(require_page_view(PAGE)), db: Session = Depends(get_db),
):
    query = db.query(DevelopmentSample)
    if q:
        like = f"%{q}%"
        query = query.filter((DevelopmentSample.title.ilike(like)) | (DevelopmentSample.sku_description.ilike(like)))
    if client:
        query = query.filter(DevelopmentSample.client == client)
    if status:
        query = query.filter(DevelopmentSample.status == status)
    items = query.order_by(DevelopmentSample.updated_at.desc()).all()
    db_clients = [c[0] for c in db.query(DevelopmentSample.client).distinct() if c[0]]
    db_from = [c[0] for c in db.query(DevelopmentSample.from_location).distinct() if c[0]]
    db_to = [c[0] for c in db.query(DevelopmentSample.to_location).distinct() if c[0]]
    clients = merge_options(DEFAULT_CLIENTS, db_clients)
    locations = merge_options(DEFAULT_LOCATIONS, db_from + db_to)
    statuses = [s[0] for s in db.query(DevelopmentSample.status).distinct() if s[0]]
    now = datetime.utcnow()
    return templates.TemplateResponse("development_samples.html", {
        "request": request, "items": items, "user": user,
        "clients": clients, "locations": locations, "statuses": statuses,
        "q": q, "client": client, "status": status,
        "can_edit": _can_edit(user, PAGE, db), "now": now,
    })


@router.post("/create")
def create(
    title: str = Form(""), sku_description: str = Form(""), client: str = Form(""),
    supplier_name: str = Form(""), from_location: str = Form(""), to_location: str = Form(""),
    sent_date: str = Form(""), return_date: str = Form(""), status: str = Form("Pending Return"),
    value: str = Form(""), remarks: str = Form(""), product_link: str = Form(""),
    tracking_url: str = Form(""), product_image: UploadFile = File(None),
    user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db),
):
    item = DevelopmentSample(
        title=title, sku_description=sku_description, client=client, supplier_name=supplier_name,
        from_location=from_location, to_location=to_location,
        sent_date=parse_date(sent_date), return_date=parse_date(return_date), status=status,
        value=parse_float(value), remarks=remarks, product_link=product_link,
        tracking_url=tracking_url, product_image=save_upload(product_image), created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.add(ActivityLog(user_email=user.email, page=PAGE, action="created", record_id=item.id, detail=title))
    db.commit()
    return RedirectResponse("/development-samples", status_code=303)


@router.post("/{item_id}/update")
def update(
    item_id: int,
    title: str = Form(""), sku_description: str = Form(""), client: str = Form(""),
    supplier_name: str = Form(""), from_location: str = Form(""), to_location: str = Form(""),
    sent_date: str = Form(""), return_date: str = Form(""), status: str = Form("Pending Return"),
    value: str = Form(""), remarks: str = Form(""), product_link: str = Form(""),
    tracking_url: str = Form(""), product_image: UploadFile = File(None),
    user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db),
):
    item = db.get(DevelopmentSample, item_id)
    if not item:
        return RedirectResponse("/development-samples", status_code=303)
    old_status = item.status
    item.title, item.sku_description, item.client = title, sku_description, client
    item.supplier_name, item.from_location, item.to_location = supplier_name, from_location, to_location
    item.sent_date = parse_date(sent_date)
    item.return_date = parse_date(return_date)
    item.status = status
    item.value = parse_float(value)
    item.remarks, item.product_link, item.tracking_url = remarks, product_link, tracking_url
    new_image = save_upload(product_image)
    if new_image:
        item.product_image = new_image
    item.updated_at = datetime.utcnow()
    db.commit()
    db.add(ActivityLog(user_email=user.email, page=PAGE, action="updated", record_id=item.id, detail=title))
    if old_status != status:
        db.add(ActivityLog(user_email=user.email, page=PAGE, action="status_changed", record_id=item.id,
                            detail=f"{old_status} -> {status}"))
        notify_status_change("Development Samples", title or f"#{item_id}", old_status, status, user.email)
    db.commit()
    return RedirectResponse("/development-samples", status_code=303)


@router.post("/{item_id}/delete")
def delete(item_id: int, user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db)):
    item = db.get(DevelopmentSample, item_id)
    if item:
        db.add(ActivityLog(user_email=user.email, page=PAGE, action="deleted", record_id=item_id, detail=item.title))
        db.delete(item)
        db.commit()
    return RedirectResponse("/development-samples", status_code=303)