"""
app/auth.py

Password hashing + session lookup. Session STORAGE itself is handled by
Starlette's SessionMiddleware (already added in main.py, signed with
SECRET_KEY) -- this file just reads/writes request.session, it does not
manage its own cookie. (An earlier version of this file rolled its own
itsdangerous-signed cookie also named "session" -- that would collide
with SessionMiddleware's own cookie of the same name and corrupt both.
Don't reintroduce that.)

Login/logout in routers/auth.py should just do:
    request.session["user_id"] = user.id      # on login
    request.session.clear()                    # on logout
"""

import os
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .database import get_db
from .models import User, UserPagePermission

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")


# --------------------------------------------------------------- PASSWORDS
# Using bcrypt directly rather than via passlib -- passlib's bcrypt backend
# is unmaintained and breaks against current bcrypt releases (it can't read
# the new __about__ version format bcrypt>=4.1 uses).
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


# ------------------------------------------------------------- RESET TOKENS
# Separate serializer/salt from anything session-related -- this signs a
# short-lived value carried in a URL query param (?token=...), not a
# cookie, so there's no overlap with SessionMiddleware's own cookie.
_reset_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="password-reset")
RESET_TOKEN_MAX_AGE_SECONDS = 60 * 60  # 1 hour


def create_reset_token(user: User) -> str:
    # Fingerprint a slice of the current password_hash into the token so
    # it's invalidated the moment the password actually changes (or if the
    # same link is reused after a successful reset) -- without needing a
    # separate reset_tokens table.
    return _reset_serializer.dumps({"user_id": user.id, "fp": user.password_hash[-12:]})


def verify_reset_token(token: str, db: Session) -> Optional[User]:
    try:
        data = _reset_serializer.loads(token, max_age=RESET_TOKEN_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    user = db.query(User).get(data.get("user_id"))
    if not user or user.password_hash[-12:] != data.get("fp"):
        return None
    return user


# ------------------------------------------------------------- DEPENDENCIES
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Raises a redirect-to-login (via the 303 exception handler in
    main.py) if there's no valid session. Use this on any route that
    requires being logged in."""
    user_id = request.session.get("user_id")
    user = db.query(User).get(user_id) if user_id else None

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Same lookup, but returns None instead of raising -- use this on
    pages that render differently for logged-in vs anonymous users
    without forcing a redirect."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).get(user_id)


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Use this (instead of get_current_user) on any /admin route."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# --------------------------------------------------------- PAGE PERMISSIONS
# Matches UserPagePermission (can_view / can_edit per page, from admin.py) --
# admins always have full access regardless of what's in that table.
def _has_permission(user: User, page: str, db: Session, need: str) -> bool:
    if user.role == "admin":
        return True
    perm = db.query(UserPagePermission).filter_by(user_id=user.id, page=page).first()
    if need == "view":
        return bool(perm and perm.can_view)
    return bool(perm and perm.can_edit)


def require_page_view(page: str):
    """Dependency factory: Depends(require_page_view('golden_samples'))"""
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not _has_permission(user, page, db, "view"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No view access to {page}.")
        return user
    return dependency


def require_page_edit(page: str):
    """Dependency factory: Depends(require_page_edit('golden_samples'))"""
    def dependency(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not _has_permission(user, page, db, "edit"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No edit access to {page}.")
        return user
    return dependency


def can_edit(user: User, page: str, db: Session) -> bool:
    """Plain boolean helper (not a dependency) -- e.g. for a template
    deciding whether to show an edit button, without blocking the page."""
    return _has_permission(user, page, db, "edit")