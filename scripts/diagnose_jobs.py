"""
Diagnoses why a report job isn't sending anything, without needing SMTP
to actually be configured. Prints: how many source records match the
job's condition, and how many recipients are configured for that report
type. Run this before assuming something is broken -- most "nothing sent"
cases are one of:
  1. No records currently fall inside the job's date window (expected,
     not a bug -- e.g. nothing happens to be due for renewal in the next
     30 days right now).
  2. No ManagerContact/ClientContact rows exist yet for that report type
     (add one via /admin first).
  3. SMTP_HOST isn't set in .env, so send_email() always no-ops.

Usage:
    python diagnose_jobs.py
"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal
from app.models import GoldenSample, ShipmentSample, DevelopmentSample, ClientContact, ManagerContact

GOLDEN_RENEWAL_DAYS = 730
SHIPMENT_DISPOSAL_DAYS = 365
WARNING_WINDOW_DAYS = 30


def check_smtp():
    host = os.getenv("SMTP_HOST", "").strip()
    default_to = os.getenv("SMTP_NOTIFY_DEFAULT", "").strip()
    print("--- SMTP config ---")
    print(f"  SMTP_HOST set: {'YES' if host else 'NO (send_email() will always no-op)'}")
    print(f"  SMTP_NOTIFY_DEFAULT set: {'YES -> ' + default_to if default_to else 'NO (fallback recipients list is empty)'}")
    print()


def check_golden_monthly(db):
    now = datetime.utcnow()
    items = db.query(GoldenSample).filter(GoldenSample.status == "Active").all()
    matching = []
    for i in items:
        if not i.start_date:
            continue
        renewal_due_date = i.start_date + timedelta(days=GOLDEN_RENEWAL_DAYS)
        days_remaining = (renewal_due_date - now).days
        if 0 <= days_remaining <= WARNING_WINDOW_DAYS:
            matching.append(i)
    already_overdue = sum(
        1 for i in items
        if i.start_date and (i.start_date + timedelta(days=GOLDEN_RENEWAL_DAYS)) < now
    )
    recipients = [m.email for m in db.query(ManagerContact).filter_by(report_type="golden").all()]
    print("--- golden_samples_monthly_job ---")
    print(f"  Active golden samples total: {len(items)}")
    print(f"  Entering renewal window in next {WARNING_WINDOW_DAYS} days: {len(matching)}  <-- this is what the monthly job emails about")
    print(f"  Already PAST the 2-year mark (overdue, NOT included by this job): {already_overdue}")
    print(f"  ManagerContact recipients (report_type='golden'): {recipients or 'NONE -- add via /admin'}")
    print()


def check_shipment_monthly(db):
    now = datetime.utcnow()
    items = (
        db.query(ShipmentSample)
        .filter(ShipmentSample.date != None)
        .filter(ShipmentSample.disposed == False)
        .all()
    )
    matching = []
    for s in items:
        due = s.date + timedelta(days=SHIPMENT_DISPOSAL_DAYS)
        days_remaining = (due - now).days
        if 0 <= days_remaining <= WARNING_WINDOW_DAYS:
            matching.append(s)
    already_overdue = sum(
        1 for s in items if (s.date + timedelta(days=SHIPMENT_DISPOSAL_DAYS)) < now
    )
    recipients = [m.email for m in db.query(ManagerContact).filter_by(report_type="shipment").all()]
    print("--- shipment_disposal_job ---")
    print(f"  Undisposed shipment samples with a date: {len(items)}")
    print(f"  Entering disposal window in next {WARNING_WINDOW_DAYS} days: {len(matching)}  <-- this is what the monthly job emails about")
    print(f"  Already PAST 1-year mark (overdue, NOT included by this job): {already_overdue}")
    print(f"  ManagerContact recipients (report_type='shipment'): {recipients or 'NONE -- add via /admin'}")
    print()


def check_dev_pending(db):
    items = db.query(DevelopmentSample).filter(DevelopmentSample.status == "Pending Return").all()
    clients = sorted({d.client or "(no client set)" for d in items})
    contacts = {c.client: c.team_emails for c in db.query(ClientContact).all()}
    print("--- dev_samples_pending_return_job ---")
    print(f"  Pending Return samples: {len(items)}")
    print(f"  Distinct clients among them: {clients or 'NONE'}")
    for c in clients:
        print(f"    {c}: routes to {contacts.get(c, 'SMTP_NOTIFY_DEFAULT (no ClientContact row for this client)')}")
    print()


def check_golden_quarterly(db):
    all_items = db.query(GoldenSample).all()
    active = [g for g in all_items if g.status == "Active"]
    recipients = [m.email for m in db.query(ManagerContact).filter_by(report_type="golden").all()]
    print("--- golden_samples_quarterly_job ---")
    print(f"  Total golden samples: {len(all_items)}  |  Active: {len(active)}")
    print(f"  ManagerContact recipients (report_type='golden'): {recipients or 'NONE -- add via /admin'}")
    print()


def check_shipment_quarterly(db):
    items = db.query(ShipmentSample).filter(ShipmentSample.date != None).all()
    recipients = [m.email for m in db.query(ManagerContact).filter_by(report_type="shipment").all()]
    print("--- shipment_samples_quarterly_job ---")
    print(f"  Shipment samples with a date: {len(items)}")
    print(f"  ManagerContact recipients (report_type='shipment'): {recipients or 'NONE -- add via /admin'}")
    print()


def check_dev_quarterly(db):
    items = db.query(DevelopmentSample).all()
    clients = sorted({d.client or "(no client)" for d in items})
    dev_contacts = db.query(ManagerContact).filter_by(report_type="development").all()
    with_client = [m for m in dev_contacts if m.client]
    fallback = [m for m in dev_contacts if not m.client]
    print("--- dev_samples_quarterly_job ---")
    print(f"  Total development samples: {len(items)}")
    print(f"  Distinct clients: {clients or 'NONE'}")
    print(f"  ManagerContact per-client recipients (report_type='development', client set): "
          f"{[(m.client, m.email) for m in with_client] or 'NONE'}")
    print(f"  ManagerContact fallback recipients (report_type='development', client=NULL): "
          f"{[m.email for m in fallback] or 'NONE -- add via /admin'}")
    print()


def main():
    check_smtp()
    db = SessionLocal()
    try:
        check_golden_monthly(db)
        check_shipment_monthly(db)
        check_dev_pending(db)
        check_golden_quarterly(db)
        check_shipment_quarterly(db)
        check_dev_quarterly(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()