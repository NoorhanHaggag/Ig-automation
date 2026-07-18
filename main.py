"""
FastAPI app entry point.

Run locally:
    uvicorn main:app --reload

Run in production (see Dockerfile):
    uvicorn main:app --host 0.0.0.0 --port 8000
"""
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import init_db, SessionLocal
from routes import api, dashboard, webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")

app = FastAPI(title="Instagram Comment-to-DM Automation")


def _seed_config_from_env():
    """
    If no Config row exists yet and INSTAGRAM_ACCESS_TOKEN is set in the
    environment, seed the DB with it so users who prefer .env-based config
    don't have to re-enter credentials in the dashboard on first run.
    """
    from models import Config

    db = SessionLocal()
    try:
        if db.query(Config).first():
            return
        token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
        ig_account_id = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID")
        if token or ig_account_id:
            db.add(Config(access_token=token, instagram_business_account_id=ig_account_id))
            db.commit()
            logger.info("Seeded initial config from environment variables")
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    init_db()
    _seed_config_from_env()
    logger.info("Database initialized, app starting up")


app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(webhook.router)
app.include_router(api.router)
app.include_router(dashboard.router)


@app.get("/health")
def health():
    return {"status": "ok"}
