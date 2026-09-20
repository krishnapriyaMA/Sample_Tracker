import os
import logging
from datetime import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from .database import SessionLocal
from .models import DevelopmentSample
from .email_utils import notify_overdue
from .scheduled_jobs import register_jobs

# Clean relative imports
from .routers import auth as auth_router
from .routers import golden as golden_router
from .routers import shipment as shipment_router
from .routers import development as development_router
from .routers import dashboard as dashboard_router
from .routers import admin as admin_router
from .routers import notifications as notifications_router

from . import seed

load_dotenv()
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Sample Tracking System")

# Middleware must be added before routers
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"))

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers (Mounted ONCE)
app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(golden_router.router)
app.include_router(shipment_router.router)
app.include_router(development_router.router)
app.include_router(notifications_router.router)
app.include_router(admin_router.router)


@app.on_event("startup")
def on_startup():
    seed.run()

    def check_overdue():
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            overdue = (
                db.query(DevelopmentSample)
                .filter(DevelopmentSample.return_date != None)  # noqa: E711
                .filter(DevelopmentSample.return_date < now)
                .filter(DevelopmentSample.status != "Returned")
                .all()
            )
            labels = [f"{d.title or d.id} (due {d.return_date.strftime('%d %b %Y')}, client: {d.client or '-'})" for d in overdue]
            notify_overdue("Development Samples", labels)
        finally:
            db.close()

    scheduler = BackgroundScheduler()
    # Daily overdue check at 08:00 server time
    scheduler.add_job(check_overdue, "cron", hour=8, minute=0, id="dev_overdue_daily")
    register_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler


@app.exception_handler(403)
async def forbidden_handler(request, exc):
    from .templating import templates
    return templates.TemplateResponse("error.html", {"request": request, "message": str(exc.detail)}, status_code=403)


@app.exception_handler(303)
async def redirect_handler(request, exc):
    location = (exc.headers or {}).get("Location", "/login")
    return RedirectResponse(location, status_code=303)