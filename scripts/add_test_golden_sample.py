"""
Inserts one Active GoldenSample whose start_date is set so its 2-year
renewal date falls 5 days from now -- inside golden_samples_monthly_job's
0-30 day warning window. Use this to test that the job actually sends an
email once a real matching record exists.

Usage:
    python add_test_golden_sample.py
"""
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from app.database import SessionLocal
from app.models import GoldenSample

GOLDEN_RENEWAL_DAYS = 730  # must match scheduled_jobs.py


def main():
    db = SessionLocal()
    try:
        # 725 days ago -> renewal date = 730 - 725 = 5 days from now
        start_date = datetime.utcnow() - timedelta(days=725)

        test_item = GoldenSample(
            sku="TEST-RENEWAL-001",
            sku_description="Test item for renewal alert verification",
            item_type="Test",
            client="Internal Test",
            supplier="N/A",
            status="Active",
            start_date=start_date,
        )
        db.add(test_item)
        db.commit()
        db.refresh(test_item)

        renewal_date = start_date + timedelta(days=GOLDEN_RENEWAL_DAYS)
        print(f"Inserted GoldenSample id={test_item.id}, sku={test_item.sku}")
        print(f"  start_date: {start_date.strftime('%Y-%m-%d')}")
        print(f"  renewal_due_date: {renewal_date.strftime('%Y-%m-%d')}  (should be ~5 days from today)")
        print(f"  days_remaining: {(renewal_date - datetime.utcnow()).days}  (should be between 0 and 30)")
    finally:
        db.close()


if __name__ == "__main__":
    main()