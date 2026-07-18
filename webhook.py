"""
Instagram/Facebook webhook endpoints.

GET  /webhook/instagram  -> handles Meta's verification handshake
POST /webhook/instagram  -> receives comment change notifications,
                             validates the signature, matches against
                             active campaigns, and fires reply + DM.
"""
import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request, Response, Depends
from sqlalchemy.orm import Session

import instagram
from database import get_db
from models import Campaign, Config, ProcessedComment

logger = logging.getLogger("webhook")
router = APIRouter()

WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")


@router.get("/webhook/instagram")
async def verify_webhook(request: Request):
    """
    Meta calls this once when you configure the webhook in the App Dashboard.
    We must echo back hub.challenge if hub.verify_token matches ours.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        logger.info("Webhook verification succeeded")
        return Response(content=challenge, media_type="text/plain")

    logger.warning("Webhook verification failed (mode=%s, token_match=%s)", mode, token == WEBHOOK_VERIFY_TOKEN)
    raise HTTPException(status_code=403, detail="Verification token mismatch")


def _verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Validates the X-Hub-Signature-256 header Meta sends on every webhook
    POST, proving the payload actually came from Meta and wasn't forged.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    if not FACEBOOK_APP_SECRET:
        logger.error("FACEBOOK_APP_SECRET is not set — refusing to process webhook")
        return False

    expected_signature = signature_header.split("sha256=", 1)[1]
    computed_hmac = hmac.new(
        key=FACEBOOK_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, computed_hmac)


@router.post("/webhook/instagram")
async def receive_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str = Header(default=None),
):
    raw_body = await request.body()

    if not _verify_signature(raw_body, x_hub_signature_256):
        logger.warning("Rejected webhook: invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    logger.info("Received webhook payload: %s", payload)

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "comments":
                continue
            _handle_comment_event(change.get("value", {}), db)

    # Always return 200 quickly so Meta doesn't retry/disable the webhook.
    return {"status": "received"}


def _handle_comment_event(comment_value: dict, db: Session):
    comment_id = comment_value.get("id")
    comment_text = (comment_value.get("text") or "").lower()
    media_id = comment_value.get("media", {}).get("id")
    commenter_id = comment_value.get("from", {}).get("id")

    if not comment_id or not media_id:
        logger.warning("Skipping malformed comment event: %s", comment_value)
        return

    # Dedup: has this comment already been processed?
    existing = db.query(ProcessedComment).filter_by(comment_id=comment_id).first()
    if existing:
        logger.info("Comment %s already processed, skipping", comment_id)
        return

    campaign = (
        db.query(Campaign)
        .filter_by(post_id=media_id, is_active=True)
        .first()
    )
    if not campaign:
        logger.info("No active campaign for post %s, ignoring comment %s", media_id, comment_id)
        return

    matched_keyword = next((kw for kw in campaign.keyword_list() if kw in comment_text), None)
    if not matched_keyword:
        logger.info("Comment %s did not match any keyword for campaign %s", comment_id, campaign.id)
        return

    config = db.query(Config).first()
    if not config or not config.access_token:
        logger.error("No Instagram access token configured — cannot process comment %s", comment_id)
        _record_processed(db, comment_id, campaign.id, commenter_id, "failed", "No access token configured")
        return

    status, detail = "processed", ""
    try:
        instagram.reply_to_comment(comment_id, campaign.comment_reply_text, config.access_token)
    except instagram.InstagramAPIError as exc:
        logger.error("Failed to reply to comment %s: %s", comment_id, exc)
        status, detail = "failed", f"reply failed: {exc}"

    try:
        # Private replies via comment_id is the standard comment-to-DM mechanism;
        # it doesn't require a prior conversation, unlike the generic /messages endpoint.
        instagram.send_private_reply_to_comment(comment_id, campaign.dm_message_text, config.access_token)
    except instagram.InstagramAPIError as exc:
        logger.error("Failed to DM commenter for comment %s: %s", comment_id, exc)
        status = "failed"
        detail = (detail + f"; dm failed: {exc}").strip("; ")

    _record_processed(db, comment_id, campaign.id, commenter_id, status, detail)


def _record_processed(db: Session, comment_id: str, campaign_id, commenter_id, status: str, detail: str):
    record = ProcessedComment(
        comment_id=comment_id,
        campaign_id=campaign_id,
        commenter_id=commenter_id,
        status=status,
        detail=detail,
    )
    db.add(record)
    db.commit()
