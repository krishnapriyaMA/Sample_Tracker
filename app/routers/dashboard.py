from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GoldenSample, ShipmentSample, DevelopmentSample, ActivityLog
from ..auth import require_page_view
from ..templating import templates

router = APIRouter(tags=["dashboard"])
PAGE = "dashboard"
RENEWAL_WINDOW_DAYS = 365 * 2
DISPOSAL_WINDOW_DAYS = 365
DISPOSAL_APPROACHING_DAYS = 30  # "approaching soon" = will hit the 1-year mark within this many days


@router.get("/", response_class=HTMLResponse)
@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(require_page_view(PAGE)), db: Session = Depends(get_db)):
    now = datetime.utcnow()

    golden_count = db.query(func.count(GoldenSample.id)).scalar()
    shipment_count = db.query(func.count(ShipmentSample.id)).scalar()
    dev_count = db.query(func.count(DevelopmentSample.id)).scalar()

    def status_breakdown(model):
        rows = db.query(model.status, func.count(model.id)).group_by(model.status).all()
        return {s or "Unknown": c for s, c in rows}

    golden_status = status_breakdown(GoldenSample)
    dev_status = status_breakdown(DevelopmentSample)

    # Golden Samples: active count, and how many of those are due for renewal
    # (Active, start_date 2+ years ago)
    golden_active_count = db.query(GoldenSample).filter(GoldenSample.status == "Active").count()
    renewal_cutoff = now - timedelta(days=RENEWAL_WINDOW_DAYS)
    golden_renewal_due = (
        db.query(GoldenSample)
        .filter(GoldenSample.status == "Active")
        .filter(GoldenSample.start_date != None)  # noqa: E711
        .filter(GoldenSample.start_date < renewal_cutoff)
        .count()
    )

    # Development Samples: pending return vs missing
    dev_pending_return_count = db.query(DevelopmentSample).filter(DevelopmentSample.status == "Pending Return").count()
    dev_missing_count = db.query(DevelopmentSample).filter(DevelopmentSample.status == "Missing").count()

    # Shipment Samples: due for disposal (date 1+ year ago, not yet disposed)
    # vs approaching disposal (will hit the 1-year mark within the next 30 days)
    disposal_cutoff = now - timedelta(days=DISPOSAL_WINDOW_DAYS)
    approaching_boundary = now - timedelta(days=DISPOSAL_WINDOW_DAYS - DISPOSAL_APPROACHING_DAYS)
    shipment_disposal_due = (
        db.query(ShipmentSample)
        .filter(ShipmentSample.date != None)  # noqa: E711
        .filter(ShipmentSample.date < disposal_cutoff)
        .filter(ShipmentSample.disposed == False)  # noqa: E712
        .count()
    )
    shipment_disposal_approaching = (
        db.query(ShipmentSample)
        .filter(ShipmentSample.date != None)  # noqa: E711
        .filter(ShipmentSample.date >= disposal_cutoff)
        .filter(ShipmentSample.date < approaching_boundary)
        .filter(ShipmentSample.disposed == False)  # noqa: E712
        .count()
    )
    shipment_status = {"Due for disposal": shipment_disposal_due, "OK": shipment_count - shipment_disposal_due}

    overdue = (
        db.query(DevelopmentSample)
        .filter(DevelopmentSample.return_date != None, DevelopmentSample.return_date < now)  # noqa: E711
        .filter(DevelopmentSample.status != "Returned")
        .order_by(DevelopmentSample.return_date.asc())
        .all()
    )

    # Status of upcoming 30 days: items whose due date falls between now and now + 30 days.
    upcoming_window = now + timedelta(days=DISPOSAL_APPROACHING_DAYS)

    # Golden: renewal date = start_date + 2 years
    upcoming_golden_rows = (
        db.query(GoldenSample)
        .filter(GoldenSample.status == "Active")
        .filter(GoldenSample.start_date != None)  # noqa: E711
        .filter(GoldenSample.start_date >= renewal_cutoff)
        .filter(GoldenSample.start_date < renewal_cutoff + timedelta(days=DISPOSAL_APPROACHING_DAYS))
        .order_by(GoldenSample.start_date.asc())
        .all()
    )
    upcoming_golden = [
        {
            "sku": g.sku or f"#{g.id}",
            "description": g.sku_description,
            "client": g.client,
            "due": g.start_date + timedelta(days=RENEWAL_WINDOW_DAYS),
        }
        for g in upcoming_golden_rows
    ]

    # Development: return date within the next 30 days, still pending return
    upcoming_dev_rows = (
        db.query(DevelopmentSample)
        .filter(DevelopmentSample.status == "Pending Return")
        .filter(DevelopmentSample.return_date != None)  # noqa: E711
        .filter(DevelopmentSample.return_date >= now)
        .filter(DevelopmentSample.return_date <= upcoming_window)
        .order_by(DevelopmentSample.return_date.asc())
        .all()
    )
    upcoming_dev = [
        {
            "sku": d.title or f"#{d.id}",
            "description": d.sku_description,
            "client": d.client,
            "due": d.return_date,
        }
        for d in upcoming_dev_rows
    ]

    # Shipment: disposal date = date + 1 year, not yet disposed
    upcoming_shipment_rows = (
        db.query(ShipmentSample)
        .filter(ShipmentSample.date != None)  # noqa: E711
        .filter(ShipmentSample.date >= disposal_cutoff)
        .filter(ShipmentSample.date < approaching_boundary)
        .filter(ShipmentSample.disposed == False)  # noqa: E712
        .order_by(ShipmentSample.date.asc())
        .all()
    )
    upcoming_shipment = [
        {
            "sku": s.buyer_ref or f"#{s.id}",
            "description": s.description,
            "client": s.buyer,
            "due": s.date + timedelta(days=DISPOSAL_WINDOW_DAYS),
        }
        for s in upcoming_shipment_rows
    ]

    recent = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(20).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user,
        "golden_count": golden_count, "shipment_count": shipment_count, "dev_count": dev_count,
        "golden_status": golden_status, "shipment_status": shipment_status, "dev_status": dev_status,
        "golden_active_count": golden_active_count, "golden_renewal_due": golden_renewal_due,
        "dev_pending_return_count": dev_pending_return_count, "dev_missing_count": dev_missing_count,
        "shipment_disposal_due": shipment_disposal_due, "shipment_disposal_approaching": shipment_disposal_approaching,
        "overdue": overdue, "recent": recent,
        "upcoming_golden": upcoming_golden, "upcoming_dev": upcoming_dev, "upcoming_shipment": upcoming_shipment,
    })


@router.get("/dashboard/list", response_class=HTMLResponse)
def dashboard_list(
    request: Request,
    category: str,
    filter: str = "all",
    q: str = "",
    user=Depends(require_page_view(PAGE)),
    db: Session = Depends(get_db),
):
    """Returns an HTML fragment (not a full page) for the inline results panel
    on the dashboard -- fetched and injected via JS when a KPI card or
    sub-metric is clicked, so the person never leaves the dashboard."""
    now = datetime.utcnow()

    if category == "golden":
        query = db.query(GoldenSample)
        if filter == "active":
            query = query.filter(GoldenSample.status == "Active")
        elif filter == "renewal_due":
            cutoff = now - timedelta(days=RENEWAL_WINDOW_DAYS)
            query = query.filter(GoldenSample.status == "Active") \
                         .filter(GoldenSample.start_date != None) \
                         .filter(GoldenSample.start_date < cutoff)  # noqa: E711
        if q:
            like = f"%{q}%"
            query = query.filter(
                (GoldenSample.sku.ilike(like)) |
                (GoldenSample.sku_description.ilike(like)) |
                (GoldenSample.client.ilike(like))
            )
        items = query.order_by(GoldenSample.updated_at.desc()).limit(300).all()
        renewal_cutoff = now - timedelta(days=RENEWAL_WINDOW_DAYS)
        for it in items:
            it.renewal_due = bool(it.status == "Active" and it.start_date and it.start_date < renewal_cutoff)
        return templates.TemplateResponse("_dashboard_list_golden.html", {"request": request, "items": items})

    elif category == "development":
        query = db.query(DevelopmentSample)
        if filter == "pending_return":
            query = query.filter(DevelopmentSample.status == "Pending Return")
        elif filter == "missing":
            query = query.filter(DevelopmentSample.status == "Missing")
        if q:
            like = f"%{q}%"
            query = query.filter(
                (DevelopmentSample.title.ilike(like)) |
                (DevelopmentSample.sku_description.ilike(like)) |
                (DevelopmentSample.client.ilike(like))
            )
        items = query.order_by(DevelopmentSample.updated_at.desc()).limit(300).all()
        return templates.TemplateResponse("_dashboard_list_development.html", {"request": request, "items": items})

    elif category == "shipment":
        query = db.query(ShipmentSample)
        disposal_cutoff = now - timedelta(days=DISPOSAL_WINDOW_DAYS)
        approaching_boundary = now - timedelta(days=DISPOSAL_WINDOW_DAYS - DISPOSAL_APPROACHING_DAYS)
        if filter == "disposal_due":
            query = query.filter(ShipmentSample.date != None) \
                         .filter(ShipmentSample.date < disposal_cutoff) \
                         .filter(ShipmentSample.disposed == False)  # noqa: E711,E712
        elif filter == "disposal_soon":
            query = query.filter(ShipmentSample.date != None) \
                         .filter(ShipmentSample.date >= disposal_cutoff) \
                         .filter(ShipmentSample.date < approaching_boundary) \
                         .filter(ShipmentSample.disposed == False)  # noqa: E711,E712
        if q:
            like = f"%{q}%"
            query = query.filter(
                (ShipmentSample.buyer_ref.ilike(like)) |
                (ShipmentSample.po_no.ilike(like)) |
                (ShipmentSample.description.ilike(like)) |
                (ShipmentSample.vendor.ilike(like)) |
                (ShipmentSample.buyer.ilike(like))
            )
        items = query.order_by(ShipmentSample.updated_at.desc()).limit(300).all()
        for it in items:
            it.disposal_due = bool(it.date and it.date < disposal_cutoff and not it.disposed)
            it.disposal_soon = bool(it.date and disposal_cutoff <= it.date < approaching_boundary and not it.disposed)
        return templates.TemplateResponse("_dashboard_list_shipment.html", {"request": request, "items": items})

    return HTMLResponse("<p class='empty-note'>Unknown category.</p>")