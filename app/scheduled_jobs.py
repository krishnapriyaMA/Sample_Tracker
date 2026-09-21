"""
Scheduled email jobs for Golden Samples, Development Samples, and Shipment Samples.
"""
from datetime import datetime, timedelta
from collections import defaultdict

from .database import SessionLocal
from .models import GoldenSample, DevelopmentSample, ShipmentSample, ClientContact, ManagerContact
from .email_utils import (
    send_golden_samples_monthly_report,
    notify_pending_return_by_client,
    send_dev_samples_quarterly_report,
    send_shipment_disposal_report,
    send_shipment_samples_quarterly_report,
    send_golden_samples_quarterly_report,
    SMTP_NOTIFY_DEFAULT,
)

GOLDEN_RENEWAL_DAYS = 730    # 2 Years
SHIPMENT_DISPOSAL_DAYS = 365 # 1 Year
WARNING_WINDOW_DAYS = 30     # Flag 30 days in advance


def golden_samples_monthly_job():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        items = db.query(GoldenSample).filter(GoldenSample.status == "Active").all()
        payload = []

        for i in items:
            if not i.start_date:
                continue

            renewal_due_date = i.start_date + timedelta(days=GOLDEN_RENEWAL_DAYS)
            days_remaining = (renewal_due_date - now).days

            if 0 <= days_remaining <= WARNING_WINDOW_DAYS:
                payload.append({
                    "sku": getattr(i, "sku", "") or f"#{i.id}",
                    # Fixed: GoldenSample has no "description" field -- the real
                    # column is "sku_description". Previously always fell back to "-".
                    "description": getattr(i, "sku_description", "") or "-",
                    "client": getattr(i, "client", "") or "-",
                    "supplier": getattr(i, "supplier", getattr(i, "supplier_name", "")) or "-",
                    "renewal_due_date": renewal_due_date.strftime("%d-%b-%Y"),
                })

        report_date = now.strftime("%d-%b-%Y")
        manager_emails = [m.email for m in db.query(ManagerContact).filter_by(report_type="golden").all()]
        send_golden_samples_monthly_report(payload, report_date, to=manager_emails or SMTP_NOTIFY_DEFAULT)
    finally:
        db.close()


def shipment_disposal_job():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        items = (
            db.query(ShipmentSample)
            .filter(ShipmentSample.date != None)
            .filter(ShipmentSample.disposed == False)
            .all()
        )
        payload = []

        for s in items:
            disposal_due_date = s.date + timedelta(days=SHIPMENT_DISPOSAL_DAYS)
            days_remaining = (disposal_due_date - now).days

            # Changed: same fix as golden_samples_monthly_job -- include
            # already-overdue items, not just ones approaching the window.
            if days_remaining <= WARNING_WINDOW_DAYS:
                payload.append({
                    "buyer_ref": getattr(s, "buyer_ref", "") or "-",
                    "po_no": getattr(s, "po_no", "") or "-",
                    "description": getattr(s, "description", "") or f"#{s.id}",
                    "vendor": getattr(s, "vendor", getattr(s, "supplier", "")) or "-",
                    "buyer": getattr(s, "buyer", getattr(s, "client", "")) or "-",
                    "location": getattr(s, "location", ""),
                    "disposal_due_date": disposal_due_date.strftime("%d-%b-%Y"),
                })

        report_date = now.strftime("%d-%b-%Y")
        manager_emails = [m.email for m in db.query(ManagerContact).filter_by(report_type="shipment").all()]
        send_shipment_disposal_report(payload, report_date, to=manager_emails or SMTP_NOTIFY_DEFAULT)
    finally:
        db.close()


def dev_samples_pending_return_job():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        one_month_ago = now - timedelta(days=30)
        items = db.query(DevelopmentSample).filter(DevelopmentSample.status == "Pending Return").all()
        by_client = defaultdict(list)

        for d in items:
            is_overdue_1mo = bool(d.return_date and d.return_date < one_month_ago)
            item_dict = {
                # Fixed: DevelopmentSample has no "sku" field -- the real
                # identifying column is "title". Previously always fell back to "#<id>".
                "sku": getattr(d, "title", "") or f"#{d.id}",
                # Fixed: real column is "sku_description", not "description".
                # Previously always fell back to "-".
                "description": getattr(d, "sku_description", "") or "-",
                "product_link": getattr(d, "product_link", "") or "-",
                "client": getattr(d, "client", "") or "(no client set)",
                "supplier": getattr(d, "supplier_name", getattr(d, "supplier", "")) or "-",
                "return_date": d.return_date.strftime("%Y-%m-%d") if d.return_date else "-",
                "is_overdue_1mo": is_overdue_1mo,
            }
            by_client[d.client or ""].append(item_dict)

        contacts = {c.client: c.team_emails for c in db.query(ClientContact).all()}
        report_date = now.strftime("%d-%b-%Y")

        for client, records in by_client.items():
            team_emails = [e.strip() for e in contacts.get(client, "").split(",") if e.strip()] or SMTP_NOTIFY_DEFAULT
            notify_pending_return_by_client(client, records, team_emails, report_date)
    finally:
        db.close()


def dev_samples_quarterly_job():
    """Generates quarterly report for Development Samples, grouped and routed per client.
    Each client's email includes a summary (total / pending / returned / missing) followed
    by three detail tables. Pending Return rows overdue by more than a month are highlighted.
    Recipients come from ManagerContact rows (report_type='development') with `client` set;
    clients without a matching row fall back to the flat development rows (client is null),
    then SMTP_NOTIFY_DEFAULT."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        one_month_ago = now - timedelta(days=30)
        items = db.query(DevelopmentSample).order_by(DevelopmentSample.client, DevelopmentSample.updated_at.desc()).all()
        by_client = defaultdict(list)
        for d in items:
            by_client[d.client or ""].append(d)

        all_dev_contacts = db.query(ManagerContact).filter_by(report_type="development").all()
        client_map = defaultdict(list)
        fallback_emails = []
        for m in all_dev_contacts:
            if m.client:
                client_map[m.client].append(m.email)
            else:
                fallback_emails.append(m.email)
        fallback_emails = fallback_emails or SMTP_NOTIFY_DEFAULT

        report_date = now.strftime("%d-%b-%Y %I:%M %p")

        for client, records in by_client.items():
            pending = [d for d in records if d.status == "Pending Return"]
            missing = [d for d in records if d.status == "Missing"]
            returned = [d for d in records if d.status == "Returned"]

            summary = {
                "Total Samples": len(records),
                "Pending Return": len(pending),
                "Returned": len(returned),
                "Missing": len(missing),
            }

            # Note: DevelopmentSample has no "sku" column -- the real
            # identifying field is "title". Data below reads d.title; header
            # label kept as "SKU" to match the rest of the report's wording.
            pending_headers = ["SKU", "Description", "Product Link", "Supplier", "Route", "Return Date"]
            pending_rows = [
                [
                    d.title or f"#{d.id}",
                    d.sku_description or "-",
                    d.product_link or "-",
                    d.supplier_name or "-",
                    f"{d.from_location or '—'} → {d.to_location or '—'}",
                    d.return_date.strftime("%d-%b-%Y") if d.return_date else "-",
                ]
                for d in pending
            ]
            pending_highlighted = {
                idx for idx, d in enumerate(pending)
                if d.return_date and d.return_date < one_month_ago
            }

            missing_headers = ["SKU", "Description", "Product Link", "Supplier", "Route", "Responsible Merchandiser"]
            missing_rows = [
                [
                    d.title or f"#{d.id}",
                    d.sku_description or "-",
                    d.product_link or "-",
                    d.supplier_name or "-",
                    f"{d.from_location or '—'} → {d.to_location or '—'}",
                    d.responsible_merchandiser or "-",
                ]
                for d in missing
            ]

            returned_headers = ["SKU", "Description", "Product Link", "Supplier", "To Location"]
            returned_rows = [
                [
                    d.title or f"#{d.id}",
                    d.sku_description or "-",
                    d.product_link or "-",
                    d.supplier_name or "-",
                    d.to_location or "-",
                ]
                for d in returned
            ]

            sections = [
                {
                    "title": "📋 Pending Return",
                    "headers": pending_headers,
                    "rows": pending_rows,
                    "highlighted_indices": pending_highlighted,
                    "nowrap_headers": {"SKU", "Route"},
                },
                {
                    "title": "❗ Missing",
                    "headers": missing_headers,
                    "rows": missing_rows,
                    "nowrap_headers": {"SKU", "Route"},
                },
                {
                    "title": "✅ Returned",
                    "headers": returned_headers,
                    "rows": returned_rows,
                    "nowrap_headers": {"SKU"},
                },
            ]

            team_emails = client_map.get(client) or fallback_emails
            send_dev_samples_quarterly_report(client, summary, sections, report_date, team_emails)
    finally:
        db.close()


def shipment_samples_quarterly_job():
    """Quarterly overview report for Shipment Samples (not client-wise).
    Sections: Overdue Disposal (all rows highlighted), Upcoming Disposal (next 30
    days), Disposed. Recipients come from ManagerContact rows with report_type='shipment'."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        items = db.query(ShipmentSample).filter(ShipmentSample.date != None).all()  # noqa: E711

        overdue, upcoming, disposed = [], [], []
        for s in items:
            if s.disposed:
                disposed.append(s)
                continue
            disposal_due_date = s.date + timedelta(days=SHIPMENT_DISPOSAL_DAYS)
            days_remaining = (disposal_due_date - now).days
            if days_remaining < 0:
                overdue.append(s)
            elif 0 <= days_remaining <= WARNING_WINDOW_DAYS:
                upcoming.append(s)

        summary = {
            "Total Samples": len(items),
            "Overdue for Disposal": len(overdue),
            "Upcoming Disposal (30 Days)": len(upcoming),
            "Disposed": len(disposed),
        }

        due_headers = ["Buyer Ref No", "PO No", "Description", "Vendor", "Buyer", "Location", "Disposal Due Date"]

        def due_row(s):
            disposal_due_date = s.date + timedelta(days=SHIPMENT_DISPOSAL_DAYS)
            return [
                s.buyer_ref or "-",
                s.po_no or "-",
                s.description or f"#{s.id}",
                s.vendor or "-",
                s.buyer or "-",
                s.location or "-",
                disposal_due_date.strftime("%d-%b-%Y"),
            ]

        overdue_rows = [due_row(s) for s in overdue]
        upcoming_rows = [due_row(s) for s in upcoming]

        disposed_headers = ["Buyer Ref No", "PO No", "Description", "Vendor", "Buyer", "Location", "Disposed On"]
        disposed_rows = [
            [
                s.buyer_ref or "-",
                s.po_no or "-",
                s.description or f"#{s.id}",
                s.vendor or "-",
                s.buyer or "-",
                s.location or "-",
                s.disposed_at.strftime("%d-%b-%Y") if s.disposed_at else "-",
            ]
            for s in disposed
        ]

        sections = [
            {
                "title": "🛑 Overdue for Disposal",
                "headers": due_headers,
                "rows": overdue_rows,
                "highlighted_indices": set(range(len(overdue_rows))),
                "nowrap_headers": {"Buyer Ref No", "PO No", "Disposal Due Date"},
            },
            {
                "title": "⏳ Upcoming Disposal (Next 30 Days)",
                "headers": due_headers,
                "rows": upcoming_rows,
                "nowrap_headers": {"Buyer Ref No", "PO No", "Disposal Due Date"},
            },
            {
                "title": "✅ Disposed",
                "headers": disposed_headers,
                "rows": disposed_rows,
                "nowrap_headers": {"Buyer Ref No", "PO No", "Disposed On"},
            },
        ]

        report_date = now.strftime("%d-%b-%Y %I:%M %p")
        manager_emails = [m.email for m in db.query(ManagerContact).filter_by(report_type="shipment").all()]
        send_shipment_samples_quarterly_report(summary, sections, report_date, manager_emails or SMTP_NOTIFY_DEFAULT)
    finally:
        db.close()


def golden_samples_quarterly_job():
    """Quarterly overview report for Golden Samples (not client-wise).
    Sections: Active Golden Samples, with rows highlighted where renewal is overdue.
    Recipients come from ManagerContact rows with report_type='golden'."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        all_items = db.query(GoldenSample).all()
        active = [g for g in all_items if g.status == "Active"]

        summary = {
            "Total Samples": len(all_items),
            "Active Golden Samples": len(active),
        }

        headers = ["SKU", "Description", "Client", "Supplier", "Start Date", "Renewal Due Date"]
        rows = []
        highlighted = set()
        for idx, g in enumerate(active):
            renewal_due_date = g.start_date + timedelta(days=GOLDEN_RENEWAL_DAYS) if g.start_date else None
            rows.append([
                g.sku or f"#{g.id}",
                g.sku_description or "-",
                g.client or "-",
                g.supplier or "-",
                g.start_date.strftime("%d-%b-%Y") if g.start_date else "-",
                renewal_due_date.strftime("%d-%b-%Y") if renewal_due_date else "-",
            ])
            if renewal_due_date and renewal_due_date < now:
                highlighted.add(idx)

        sections = [
            {
                "title": "✨ Active Golden Samples",
                "headers": headers,
                "rows": rows,
                "highlighted_indices": highlighted,
                "nowrap_headers": {"SKU", "Start Date", "Renewal Due Date"},
            },
        ]

        report_date = now.strftime("%d-%b-%Y %I:%M %p")
        manager_emails = [m.email for m in db.query(ManagerContact).filter_by(report_type="golden").all()]
        send_golden_samples_quarterly_report(summary, sections, report_date, manager_emails or SMTP_NOTIFY_DEFAULT)
    finally:
        db.close()


def register_jobs(scheduler):
    # Golden Samples renewal report: 1st of every month, 11:00
    scheduler.add_job(golden_samples_monthly_job, "cron", day=1, hour=11, minute=0, id="golden_monthly")
    # Development Samples pending-return: every 14 days
    scheduler.add_job(dev_samples_pending_return_job, "interval", weeks=2, id="dev_biweekly")
    # Development Samples full report, per client: 1st of Jan/Apr/Jul/Oct, 09:00
    scheduler.add_job(dev_samples_quarterly_job, "cron", month="1,4,7,10", day=1, hour=9, minute=0, id="dev_quarterly")
    # Shipment Samples disposal report: 1st of every month, 11:30
    scheduler.add_job(shipment_disposal_job, "cron", day=1, hour=11, minute=30, id="shipment_disposal")
    # Shipment Samples quarterly overview: 1st of Jan/Apr/Jul/Oct, 09:30
    scheduler.add_job(shipment_samples_quarterly_job, "cron", month="1,4,7,10", day=1, hour=9, minute=30, id="shipment_quarterly")
    # Golden Samples quarterly overview: 1st of Jan/Apr/Jul/Oct, 10:00
    scheduler.add_job(golden_samples_quarterly_job, "cron", month="1,4,7,10", day=1, hour=10, minute=0, id="golden_quarterly")