import os

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..auth import (
    hash_password,
    verify_password,
    get_current_user_optional,
    create_reset_token,
    verify_reset_token,
)
from ..email_utils import send_password_reset_email
from ..templating import templates

router = APIRouter(tags=["auth"])

ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "").strip().lower()


# ------------------------------------------------------------------- LOGIN
@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Incorrect email or password."},
            status_code=401,
        )

    if not user.is_active:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "This account has been deactivated."},
            status_code=403,
        )

    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------- REGISTER
@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/register")
def register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    name = name.strip()

    if ALLOWED_EMAIL_DOMAIN and not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": f"Registration is restricted to @{ALLOWED_EMAIL_DOMAIN} email addresses."},
            status_code=400,
        )

    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "An account with this email already exists."},
            status_code=400,
        )

    new_user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    request.session["user_id"] = new_user.id
    return RedirectResponse("/", status_code=303)


# ------------------------------------------------------------------ LOGOUT
@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------ FORGOT PASSWORD
@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_form(request: Request):
    return templates.TemplateResponse("forgot_password.html", {"request": request, "sent": False})


@router.post("/forgot-password")
def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    # Always show the same "check your email" message whether or not the
    # address exists -- otherwise this endpoint leaks which emails have
    # accounts.
    if user and user.is_active:
        token = create_reset_token(user)
        reset_url = str(request.url_for("reset_password_form")) + f"?token={token}"
        send_password_reset_email(user.email, reset_url)

    return templates.TemplateResponse("forgot_password.html", {"request": request, "sent": True})


# ------------------------------------------------------------- RESET PASSWORD
@router.get("/reset-password", response_class=HTMLResponse, name="reset_password_form")
def reset_password_form(request: Request, token: str, db: Session = Depends(get_db)):
    user = verify_reset_token(token, db)
    if not user:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": None, "error": "This reset link is invalid or has expired."},
        )
    return templates.TemplateResponse("reset_password.html", {"request": request, "token": token, "error": None})


@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = verify_reset_token(token, db)
    if not user:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": None, "error": "This reset link is invalid or has expired."},
        )

    if password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {"request": request, "token": token, "error": "Passwords don't match."},
        )

    user.password_hash = hash_password(password)
    db.commit()

    # Log them in immediately after a successful reset, same as a fresh login.
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)