from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

# Adjust database import path to match app layout
from app.database import get_db
from app.templating import templates  # or Jinja2Templates configuration

router = APIRouter()

@router.get("/notifications", response_class=HTMLResponse)
async def get_notifications_page(request: Request, db: Session = Depends(get_db)):
    # Retrieve notification records if you have a model, or pass an empty list
    notifications = []
    
    return templates.TemplateResponse("notifications.html", {
        "request": request,
        "notifications": notifications,
        "current_user": getattr(request.state, "user", None)
    })