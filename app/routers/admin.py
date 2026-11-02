from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserPagePermission, PAGES, ClientContact, ManagerContact
from ..auth import require_admin
from ..templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])

GRANTABLE_PAGES = [p for p in PAGES if p != "admin"]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def admin_home(request: Request, user=Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.created_at.desc()).all()
    perms = {(p.user_id, p.page): p for p in db.query(UserPagePermission).all()}
    client_contacts = db.query(ClientContact).order_by(ClientContact.client).all()

    # Query manager contacts and categorize them for template contexts
    all_managers = db.query(ManagerContact).all()
    dev_quarterly_client_contacts = [
        m for m in all_managers if getattr(m, "report_type", None) == "development" and getattr(m, "client", None)
    ]
    development_contacts = [
        m for m in all_managers if getattr(m, "report_type", None) == "development" and not getattr(m, "client", None)
    ]
    golden_contacts = [m for m in all_managers if getattr(m, "report_type", None) == "golden"]
    shipment_contacts = [m for m in all_managers if getattr(m, "report_type", None) == "shipment"]

    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "users": users,
        "perms": perms,
        "pages": GRANTABLE_PAGES,
        "client_contacts": client_contacts,
        "dev_quarterly_client_contacts": dev_quarterly_client_contacts,
        "development_contacts": development_contacts,
        "golden_contacts": golden_contacts,
        "shipment_contacts": shipment_contacts,
    })


@router.post("/users/{user_id}/role")
def change_role(user_id: int, role: str = Form(...), user=Depends(require_admin), db: Session = Depends(get_db)):
    target = db.query(User).get(user_id)
    if target and role in ("admin", "user"):
        target.role = role
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/users/{user_id}/toggle-active")
def toggle_active(user_id: int, user=Depends(require_admin), db: Session = Depends(get_db)):
    target = db.query(User).get(user_id)
    if target and target.id != user.id:
        target.is_active = not target.is_active
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/permissions/set")
async def set_permission(
    user_id: int = Form(...), page: str = Form(...),
    can_view: bool = Form(False), can_edit: bool = Form(False),
    user=Depends(require_admin), db: Session = Depends(get_db),
):
    if page not in GRANTABLE_PAGES:
        return {"ok": False}
    perm = db.query(UserPagePermission).filter_by(user_id=user_id, page=page).first()
    if not perm:
        perm = UserPagePermission(user_id=user_id, page=page)
        db.add(perm)
    perm.can_view = can_view
    perm.can_edit = can_edit
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Development Samples: per-client notification routing (biweekly pending-return alert)
# ---------------------------------------------------------------------------
@router.post("/client-contacts/create")
def create_client_contact(
    client: str = Form(...), team_emails: str = Form(...),
    user=Depends(require_admin), db: Session = Depends(get_db),
):
    client = client.strip()
    if client and not db.query(ClientContact).filter_by(client=client).first():
        db.add(ClientContact(client=client, team_emails=team_emails.strip()))
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/client-contacts/{contact_id}/update")
def update_client_contact(
    contact_id: int, team_emails: str = Form(...),
    user=Depends(require_admin), db: Session = Depends(get_db),
):
    contact = db.query(ClientContact).get(contact_id)
    if contact:
        contact.team_emails = team_emails.strip()
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@router.post("/client-contacts/{contact_id}/delete")
def delete_client_contact(contact_id: int, user=Depends(require_admin), db: Session = Depends(get_db)):
    contact = db.query(ClientContact).get(contact_id)
    if contact:
        db.delete(contact)
        db.commit()
    return RedirectResponse("/admin", status_code=303)


# ---------------------------------------------------------------------------
# Manager/Report Contacts (Golden, Shipment, Development)
# ---------------------------------------------------------------------------
@router.post("/manager-contacts/create")
def create_manager_contact(
    name: str = Form(""),
    email: str = Form(...),
    report_type: str = Form("development"),
    client: str = Form(None),
    user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    client_val = client.strip() if client else None
    
    # Check if entry already exists for email, report_type, and client combination
    existing = db.query(ManagerContact).filter_by(
        email=email,
        report_type=report_type,
        client=client_val
    ).first()

    if email and not existing:
        contact_kwargs = {
            "name": name.strip(),
            "email": email,
            "report_type": report_type
        }
        if hasattr(ManagerContact, "client"):
            contact_kwargs["client"] = client_val

        db.add(ManagerContact(**contact_kwargs))
        db.commit()

    return RedirectResponse("/admin", status_code=303)


@router.post("/manager-contacts/{contact_id}/delete")
def delete_manager_contact(contact_id: int, user=Depends(require_admin), db: Session = Depends(get_db)):
    contact = db.query(ManagerContact).get(contact_id)
    if contact:
        db.delete(contact)
        db.commit()
    return RedirectResponse("/admin", status_code=303)