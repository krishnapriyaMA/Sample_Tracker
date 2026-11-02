from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ShipmentSample, ActivityLog
from ..auth import require_page_view, require_page_edit, can_edit as _can_edit
from ..templating import templates
from ..bulk_upload import process_upload, template_response

router = APIRouter(prefix="/shipment-samples", tags=["shipment"])
PAGE = "shipment_samples"
DISPOSAL_WINDOW_DAYS = 365


def parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


@router.get("", response_class=HTMLResponse)
def list_view(
    request: Request, q: str = "", vendor: str = "", buyer: str = "", disposal_due: str = "",
    rack: str = "", finish: str = "", disp_from: str = "", disp_to: str = "",
    user=Depends(require_page_view(PAGE)), db: Session = Depends(get_db),
):
    query = db.query(ShipmentSample)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (ShipmentSample.buyer_ref.ilike(like)) |
            (ShipmentSample.po_no.ilike(like)) |
            (ShipmentSample.description.ilike(like)) |
            (ShipmentSample.barcode.ilike(like))
        )
    if vendor:
        query = query.filter(ShipmentSample.vendor == vendor)
    if buyer:
        query = query.filter(ShipmentSample.buyer == buyer)
    if rack:
        query = query.filter(ShipmentSample.rack_no == rack)
    if finish:
        query = query.filter(ShipmentSample.finish == finish)
    # Disposal date = date + 1 year, so translate the range back onto `date`
    d_from, d_to = parse_date(disp_from), parse_date(disp_to)
    window = timedelta(days=DISPOSAL_WINDOW_DAYS)
    if d_from:
        query = query.filter(ShipmentSample.date >= d_from - window)
    if d_to:
        query = query.filter(ShipmentSample.date < d_to + timedelta(days=1) - window)
    items = query.order_by(ShipmentSample.updated_at.desc()).all()

    cutoff = datetime.utcnow() - timedelta(days=DISPOSAL_WINDOW_DAYS)
    for it in items:
        it.disposal_due = bool(it.date and it.date < cutoff and not it.disposed)
        it.disposal_date = (it.date + timedelta(days=DISPOSAL_WINDOW_DAYS)) if it.date else None
    if disposal_due == "1":
        items = [it for it in items if it.disposal_due]

    vendors = [v[0] for v in db.query(ShipmentSample.vendor).distinct() if v[0]]
    buyers = [b[0] for b in db.query(ShipmentSample.buyer).distinct() if b[0]]
    racks = sorted(x[0] for x in db.query(ShipmentSample.rack_no).distinct() if x[0])
    finishes = sorted(x[0] for x in db.query(ShipmentSample.finish).distinct() if x[0])
    return templates.TemplateResponse("shipment_samples.html", {
        "request": request, "items": items, "user": user,
        "vendors": vendors, "buyers": buyers, "racks": racks, "finishes": finishes,
        "q": q, "vendor": vendor, "buyer": buyer, "disposal_due": disposal_due,
        "rack": rack, "finish": finish, "disp_from": disp_from, "disp_to": disp_to,
        "can_edit": _can_edit(user, PAGE, db),
    })


@router.get("/bulk-template")
def bulk_template(user=Depends(require_page_edit(PAGE))):
    return template_response("shipment_samples")


@router.post("/bulk-upload")
def bulk_upload(file: UploadFile = File(...), user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db)):
    return JSONResponse(process_upload("shipment_samples", file, user, db))


@router.post("/create")
def create(
    buyer_ref: str = Form(""), po_no: str = Form(""), vendor: str = Form(""),
    barcode: str = Form(""), rack_no: str = Form(""), description: str = Form(""),
    buyer: str = Form(""), date: str = Form(""), finish: str = Form(""),
    user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db),
):
    item = ShipmentSample(
        buyer_ref=buyer_ref, po_no=po_no, vendor=vendor, barcode=barcode, rack_no=rack_no,
        description=description, buyer=buyer, date=parse_date(date), finish=finish,
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.add(ActivityLog(user_email=user.email, page=PAGE, action="created", record_id=item.id, detail=description))
    db.commit()
    return RedirectResponse("/shipment-samples", status_code=303)


@router.post("/{item_id}/update")
def update(
    item_id: int,
    buyer_ref: str = Form(""), po_no: str = Form(""), vendor: str = Form(""),
    barcode: str = Form(""), rack_no: str = Form(""), description: str = Form(""),
    buyer: str = Form(""), date: str = Form(""), finish: str = Form(""),
    user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db),
):
    item = db.get(ShipmentSample, item_id)
    if not item:
        return RedirectResponse("/shipment-samples", status_code=303)
    item.buyer_ref, item.po_no, item.vendor = buyer_ref, po_no, vendor
    item.barcode, item.rack_no, item.description = barcode, rack_no, description
    item.buyer, item.finish = buyer, finish
    item.date = parse_date(date)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.add(ActivityLog(user_email=user.email, page=PAGE, action="updated", record_id=item.id, detail=description))
    db.commit()
    return RedirectResponse("/shipment-samples", status_code=303)


@router.post("/{item_id}/mark-disposed")
def mark_disposed(item_id: int, user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db)):
    item = db.get(ShipmentSample, item_id)
    if item:
        item.disposed = True
        item.disposed_at = datetime.utcnow()
        db.commit()
        db.add(ActivityLog(user_email=user.email, page=PAGE, action="updated", record_id=item.id,
                            detail=f"marked disposed: {item.description}"))
        db.commit()
    return RedirectResponse("/shipment-samples", status_code=303)


@router.post("/{item_id}/delete")
def delete(item_id: int, user=Depends(require_page_edit(PAGE)), db: Session = Depends(get_db)):
    item = db.get(ShipmentSample, item_id)
    if item:
        db.add(ActivityLog(user_email=user.email, page=PAGE, action="deleted", record_id=item_id, detail=item.description))
        db.delete(item)
        db.commit()
    return RedirectResponse("/shipment-samples", status_code=303)