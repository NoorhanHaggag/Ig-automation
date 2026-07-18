"""
JSON REST API consumed by the dashboard frontend (static/app.js).
CRUD for Campaigns, get/set Config, and a post-preview lookup endpoint.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import instagram
from database import get_db
from models import Campaign, Config

logger = logging.getLogger("api")
router = APIRouter(prefix="/api")


# ---------- Schemas ----------

class ConfigIn(BaseModel):
    access_token: str
    page_id: str
    instagram_business_account_id: str


class CampaignIn(BaseModel):
    post_id: str
    keywords: str
    comment_reply_text: str
    dm_message_text: str
    is_active: bool = True


class CampaignUpdate(BaseModel):
    post_id: str | None = None
    keywords: str | None = None
    comment_reply_text: str | None = None
    dm_message_text: str | None = None
    is_active: bool | None = None


# ---------- Config ----------

@router.get("/config")
def get_config(db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config:
        return {"access_token": "", "page_id": "", "instagram_business_account_id": ""}
    return {
        # Mask the token in responses; the raw value is only ever used server-side.
        "access_token": _mask_token(config.access_token),
        "page_id": config.page_id or "",
        "instagram_business_account_id": config.instagram_business_account_id or "",
    }


@router.post("/config")
def save_config(payload: ConfigIn, db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config:
        config = Config()
        db.add(config)

    if payload.access_token:
        config.access_token = payload.access_token
    config.page_id = payload.page_id
    config.instagram_business_account_id = payload.instagram_business_account_id
    db.commit()
    logger.info("Config updated")
    return {"status": "saved"}


def _mask_token(token: str | None) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return token[:4] + "*" * (len(token) - 8) + token[-4:]


# ---------- Campaigns ----------

@router.get("/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return [_campaign_to_dict(c) for c in campaigns]


@router.post("/campaigns")
def create_campaign(payload: CampaignIn, db: Session = Depends(get_db)):
    campaign = Campaign(**payload.model_dump())

    # Best-effort: fetch post preview at creation time so it's cached in the DB.
    config = db.query(Config).first()
    if config and config.access_token:
        try:
            details = instagram.get_post_details(payload.post_id, config.access_token)
            campaign.post_thumbnail_url = details.get("thumbnail_url")
            campaign.post_caption = details.get("caption")
        except instagram.InstagramAPIError as exc:
            logger.warning("Could not fetch post preview for %s: %s", payload.post_id, exc)

    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _campaign_to_dict(campaign)


@router.put("/campaigns/{campaign_id}")
def update_campaign(campaign_id: int, payload: CampaignUpdate, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter_by(id=campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(campaign, field, value)

    db.commit()
    db.refresh(campaign)
    return _campaign_to_dict(campaign)


@router.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter_by(id=campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.delete(campaign)
    db.commit()
    return {"status": "deleted"}


@router.post("/campaigns/{campaign_id}/toggle")
def toggle_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter_by(id=campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign.is_active = not campaign.is_active
    db.commit()
    return {"status": "toggled", "is_active": campaign.is_active}


# ---------- Post preview ----------

@router.get("/post-preview/{post_id}")
def post_preview(post_id: str, db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config or not config.access_token:
        raise HTTPException(status_code=400, detail="Instagram access token not configured yet")

    try:
        details = instagram.get_post_details(post_id, config.access_token)
    except instagram.InstagramAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return details


def _campaign_to_dict(c: Campaign) -> dict:
    return {
        "id": c.id,
        "post_id": c.post_id,
        "post_thumbnail_url": c.post_thumbnail_url,
        "post_caption": c.post_caption,
        "keywords": c.keywords,
        "comment_reply_text": c.comment_reply_text,
        "dm_message_text": c.dm_message_text,
        "is_active": c.is_active,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }
