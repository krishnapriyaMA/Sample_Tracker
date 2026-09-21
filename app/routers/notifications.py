from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

# Adjust database import path to match app layout
from app.database import get_db
from app.templating import templates  # or Jinja2Templates configuration
from app.auth import require_page_view  # same helper used by the other routers

router = APIRouter()
PAGE = "notifications"


@router.get("/notifications", response_class=HTMLResponse)
async def get_notifications_page(
    request: Request,
    user=Depends(require_page_view(PAGE)),
    db: Session = Depends(get_db),
):
    # Retrieve notification records if you have a model, or pass an empty list
    notifications = []

    return templates.TemplateResponse("notifications.html", {
        "request": request,
        "notifications": notifications,
        "user": user,
    })