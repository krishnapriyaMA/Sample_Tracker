from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from .database import Base

PAGES = ["golden_samples", "shipment_samples", "development_samples", "dashboard", "admin"]
ROLES = ["admin", "user"]


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin | user
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserPagePermission(Base):
    """Per-user, per-page view/edit access, set by an admin from /admin using the
    person's email. Admins always have full access regardless of these rows."""
    __tablename__ = "user_page_permissions"
    __table_args__ = (UniqueConstraint("user_id", "page", name="uq_user_page"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    page = Column(String(50), nullable=False)
    can_view = Column(Boolean, default=False)
    can_edit = Column(Boolean, default=False)


class GoldenSample(Base):
    __tablename__ = "golden_samples"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(255))  # the SKU number itself (e.g. "253891")
    sku_description = Column(String(255))
    item_type = Column(String(120))
    client = Column(String(120), index=True)
    supplier = Column(String(120))
    vendor_ref = Column(String(120))
    barcode = Column(String(120))
    size = Column(String(60))
    location = Column(String(120))
    rack = Column(String(60))
    seal_no = Column(String(60))
    status = Column(String(60), default="Active", index=True)
    start_date = Column(DateTime, nullable=True)  # drives the 2-year renewal flag
    renewal_acknowledged_at = Column(DateTime, nullable=True)  # cleared when start_date is updated
    value = Column(Float, nullable=True)
    image_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class ShipmentSample(Base):
    """Matches the real Power App screen: Buyer Ref, Shipment samples PO No,
    Vendor, Barcode, Rack no., Description, Buyer, Date, Finish, Location."""
    __tablename__ = "shipment_samples"

    id = Column(Integer, primary_key=True, index=True)
    buyer_ref = Column(String(120), index=True)
    po_no = Column(String(120))
    vendor = Column(String(120))
    barcode = Column(String(120))
    rack_no = Column(String(60))
    description = Column(String(255))
    buyer = Column(String(120), index=True)
    date = Column(DateTime, nullable=True)  # disposal = date + 1 year
    finish = Column(String(120))
    location = Column(String(120))
    disposed = Column(Boolean, default=False)  # set once someone marks it disposed
    disposed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class DevelopmentSample(Base):
    __tablename__ = "development_samples"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255))
    sku_description = Column(String(255))
    client = Column(String(120), index=True)
    supplier_name = Column(String(120))
    responsible_merchandiser = Column(String(120))
    from_location = Column(String(120))
    to_location = Column(String(120))
    sent_date = Column(DateTime, nullable=True)
    return_date = Column(DateTime, nullable=True)
    status = Column(String(60), default="Pending Return", index=True)  # Pending Return | Returned | Missing
    value = Column(Float, nullable=True)
    remarks = Column(Text, nullable=True)
    product_link = Column(String(500), nullable=True)
    product_image = Column(String(500), nullable=True)
    tracking_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class ClientContact(Base):
    """Per-client notification routing for Development Sample alerts.
    e.g. client='Wickes' -> team_emails='wickesteam@jandjsourcing.com'.
    Admin manages this from /admin. Falls back to SMTP_NOTIFY_DEFAULT if a
    client has no row here."""
    __tablename__ = "client_contacts"

    id = Column(Integer, primary_key=True)
    client = Column(String(120), unique=True, index=True, nullable=False)
    team_emails = Column(String(500), nullable=False)  # comma-separated


class ManagerContact(Base):
    """Admin-managed recipient list for the quarterly Development Samples
    report. Kept separate from SMTP_NOTIFY_DEFAULT so it's editable without
    touching .env."""
    __tablename__ = "manager_contacts"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=True)
    email = Column(String(255), unique=True, nullable=False)


class ActivityLog(Base):
    """Simple audit trail, also feeds the dashboard 'recent activity' feed."""
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    user_email = Column(String(255))
    page = Column(String(50))
    action = Column(String(50))  # created | updated | deleted | status_changed
    record_id = Column(Integer)
    detail = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)