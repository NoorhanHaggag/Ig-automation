"""
Instagram Graph API client.

All outbound calls to Meta's Graph API live here so the rest of the app
never talks to `requests`/HTTP directly. Every function:
  - logs the outcome (success or failure) for auditability
  - retries on rate-limit (HTTP 429 / Graph error code 4, 17, 32) with
    exponential backoff
  - raises InstagramAPIError on unrecoverable failures so callers can
    decide how to handle them (e.g. mark a ProcessedComment as "failed")

Only the official Instagram Graph API is used here — no Selenium, no
unofficial/private API libraries (instagrapi, etc).
"""
import logging
import time
from typing import Optional

import requests

logger = logging.getLogger("instagram_api")

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

# Graph API error codes that indicate a transient rate limit — safe to retry.
RATE_LIMIT_ERROR_CODES = {4, 17, 32, 613}
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2


class InstagramAPIError(Exception):
    """Raised when a Graph API call fails after retries are exhausted."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _request_with_retry(method: str, url: str, **kwargs) -> dict:
    """
    Wraps requests.request with retry + exponential backoff on rate limits.
    Raises InstagramAPIError on final failure.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, timeout=15, **kwargs)
            payload = {}
            try:
                payload = response.json()
            except ValueError:
                pass

            if response.status_code == 200:
                logger.info("Graph API %s %s succeeded (attempt %d)", method, url.split("?")[0], attempt)
                return payload

            error_code = payload.get("error", {}).get("code")
            is_rate_limited = response.status_code == 429 or error_code in RATE_LIMIT_ERROR_CODES

            if is_rate_limited and attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF_SECONDS ** attempt
                logger.warning(
                    "Graph API rate limited (status=%s code=%s). Retrying in %ds (attempt %d/%d)",
                    response.status_code, error_code, backoff, attempt, MAX_RETRIES,
                )
                time.sleep(backoff)
                last_error = InstagramAPIError(
                    f"Rate limited: {payload}", status_code=response.status_code, payload=payload
                )
                continue

            # Non-retryable error
            logger.error("Graph API %s %s failed: %s", method, url.split("?")[0], payload)
            raise InstagramAPIError(
                f"Graph API call failed: {payload.get('error', {}).get('message', response.text)}",
                status_code=response.status_code,
                payload=payload,
            )

        except requests.RequestException as exc:
            last_error = InstagramAPIError(f"Network error calling Graph API: {exc}")
            if attempt < MAX_RETRIES:
                backoff = BASE_BACKOFF_SECONDS ** attempt
                logger.warning("Network error on attempt %d/%d, retrying in %ds: %s", attempt, MAX_RETRIES, backoff, exc)
                time.sleep(backoff)
                continue

    logger.error("Graph API call exhausted retries: %s", last_error)
    raise last_error or InstagramAPIError("Unknown error calling Graph API")


def reply_to_comment(comment_id: str, message: str, access_token: str) -> dict:
    """
    Posts a public reply to an Instagram comment.
    POST /{comment-id}/replies
    """
    url = f"{GRAPH_API_BASE}/{comment_id}/replies"
    result = _request_with_retry(
        "POST",
        url,
        data={"message": message, "access_token": access_token},
    )
    logger.info("Replied to comment %s", comment_id)
    return result


def send_dm(instagram_user_id: str, message: str, access_token: str, ig_business_account_id: str) -> dict:
    """
    Sends a private DM to a commenter via the Instagram Messaging API.
    POST /{ig-business-account-id}/messages

    NOTE: Per Meta policy, this only works if the recipient has messaged the
    business before, OR your app has the instagram_manage_messages permission
    with the "comment-to-DM" / private replies use case approved. See README.
    """
    url = f"{GRAPH_API_BASE}/{ig_business_account_id}/messages"
    payload = {
        "recipient": {"id": instagram_user_id},
        "message": {"text": message},
    }
    result = _request_with_retry(
        "POST",
        url,
        json=payload,
        params={"access_token": access_token},
    )
    logger.info("Sent DM to Instagram user %s", instagram_user_id)
    return result


def send_private_reply_to_comment(comment_id: str, message: str, access_token: str) -> dict:
    """
    Alternative to send_dm: Meta's "Private Replies" endpoint lets you message
    a commenter directly by comment_id without needing a prior conversation,
    which is the standard mechanism comment-to-DM tools rely on.
    POST /{comment-id}/private_replies
    """
    url = f"{GRAPH_API_BASE}/{comment_id}/private_replies"
    result = _request_with_retry(
        "POST",
        url,
        data={"message": message, "access_token": access_token},
    )
    logger.info("Sent private reply (DM) for comment %s", comment_id)
    return result


def get_post_details(post_id: str, access_token: str) -> dict:
    """
    Fetches thumbnail URL + caption for a post, used to render a preview
    in the dashboard when adding a campaign.
    GET /{post-id}?fields=caption,media_url,thumbnail_url,permalink
    """
    url = f"{GRAPH_API_BASE}/{post_id}"
    result = _request_with_retry(
        "GET",
        url,
        params={
            "fields": "caption,media_url,thumbnail_url,permalink,media_type",
            "access_token": access_token,
        },
    )
    # Video posts use thumbnail_url; images use media_url directly.
    thumbnail = result.get("thumbnail_url") or result.get("media_url")
    return {
        "caption": result.get("caption", ""),
        "thumbnail_url": thumbnail,
        "permalink": result.get("permalink", ""),
        "media_type": result.get("media_type", ""),
    }


def refresh_long_lived_token(current_token: str, app_secret: str, app_id: str) -> dict:
    """
    Exchanges a still-valid long-lived token for a fresh one, resetting the
    60-day expiry clock. Meant to be called periodically (e.g. via a cron
    job every ~50 days) — see README for setup.
    GET /refresh_access_token / oauth/access_token flow.
    """
    url = f"{GRAPH_API_BASE}/oauth/access_token"
    result = _request_with_retry(
        "GET",
        url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": current_token,
        },
    )
    logger.info("Refreshed long-lived access token")
    return result
