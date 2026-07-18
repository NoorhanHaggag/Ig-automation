# Instagram Comment → DM Automation

Watches keyword comments on chosen Instagram posts, replies publicly, and
sends the commenter a private DM automatically — the same pattern tools like
ManyChat use, built on the **official Instagram Graph API only** (no
Selenium, no unofficial/private API libraries).

---

## 1. How it works

1. Someone comments a trigger keyword (e.g. `"price"`) on a post you're tracking.
2. Meta sends a webhook to `POST /webhook/instagram`.
3. The app checks: is this post tracked? Does the comment contain a keyword? Has this comment already been handled?
4. If it's a fresh match: posts a public reply to the comment, then sends the commenter a private message.
5. Everything is logged and recorded in the `processed_comments` table so a comment is never actioned twice.

---

## 2. Instagram API setup (do this first)

You need a Facebook Developer App connected to an Instagram **Business** or
**Creator** account. Follow these steps in order.

### Step 1 — Convert your Instagram account

Your Instagram account must be a **Business** or **Creator** account (not
personal), and it must be linked to a Facebook Page.

- Instagram app → Settings → Account type and tools → Switch to Professional Account
- Choose Business or Creator
- Link it to a Facebook Page when prompted (create one if you don't have one)

### Step 2 — Create a Facebook Developer App

1. Go to [developers.facebook.com](https://developers.facebook.com) → **My Apps** → **Create App**
2. Choose **"Other"** → **"Business"** as the app type
3. Give it a name (e.g. "My Comment Automation") and create it

### Step 3 — Add the Instagram Graph API product

1. In your app's dashboard, find **"Add Product"**
2. Add **Instagram Graph API**
3. Also add the **Webhooks** product (you'll configure it in Step 5)

### Step 4 — Request permissions

Under **App Review → Permissions and Features**, request:

- `instagram_manage_comments` — lets the app read/reply to comments
- `instagram_manage_messages` — lets the app send DMs
- `pages_show_list` and `pages_read_engagement` — needed to resolve your Page ↔ Instagram account link

While your app is in **Development Mode**, these permissions work for
accounts you've added as testers/admins on the app (Roles → Roles) without
needing App Review — this is enough to build and test with your own account.
**App Review is required before you can use this on other people's accounts
in production.**

### Step 5 — Generate a long-lived Access Token

1. Go to **Tools → Graph API Explorer**
2. Select your app from the dropdown
3. Select your Page (User Token → Get Token → get a User Access Token with the permissions above)
4. This gives you a **short-lived token (~1 hour)**. Exchange it for a long-lived one (~60 days):

```
GET https://graph.facebook.com/v19.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id={your-app-id}
    &client_secret={your-app-secret}
    &fb_exchange_token={short-lived-token}
```

5. Paste the resulting long-lived token into the app's **Settings** page (or `.env`)

**Refreshing before it expires:** long-lived tokens last 60 days. Call the
same `fb_exchange_token` endpoint above with your *current* long-lived token
(as long as it hasn't expired yet) to get a new 60-day token. The
`instagram.refresh_long_lived_token()` function in `instagram.py` does this —
wire it into a scheduled job (cron, Railway cron, etc.) to run every ~50 days
so it never lapses.

### Step 6 — Configure the Webhook

1. In your app dashboard: **Webhooks** → **Instagram** → **Subscribe to this object**
2. Callback URL: `https://YOUR-DEPLOYED-DOMAIN/webhook/instagram`
3. Verify Token: any string you choose — put the same string in `WEBHOOK_VERIFY_TOKEN` in your `.env`
4. Subscribe to the **`comments`** field
5. Click **Verify and Save** — Meta will call `GET /webhook/instagram` once to confirm; the app handles this automatically

> Webhooks require a public HTTPS URL, so you'll need to deploy first (or use a tunnel like ngrok for local testing) before this step will succeed.

### Step 7 — Find a Post ID

1. Go to **Graph API Explorer**
2. Run: `GET /{instagram-business-account-id}/media?fields=id,caption,thumbnail_url,permalink`
3. Copy the `id` of the post you want to track — paste it into a Campaign's "Post ID" field in the dashboard (it auto-fetches a preview on blur)

---

## 3. Running locally

```bash
cp .env.example .env
# fill in FACEBOOK_APP_SECRET and WEBHOOK_VERIFY_TOKEN at minimum

pip install -r requirements.txt
uvicorn main:app --reload
```

Visit `http://localhost:8000/dashboard/settings` to enter your Instagram
credentials, then `http://localhost:8000/dashboard/campaigns` to add a
campaign.

To receive real webhooks locally, tunnel your local server (e.g.
`ngrok http 8000`) and use the resulting HTTPS URL in Step 6 above.

---

## 4. Deployment

### Docker (anywhere)

```bash
docker build -t ig-automation .
docker run -p 8000:8000 --env-file .env ig-automation
```

### Railway

Push this repo, connect it in Railway, and set the env vars listed in
`railway.toml`. Railway auto-detects the Dockerfile.

### Render

Push this repo, create a new **Blueprint** from `render.yaml`, and fill in
the env vars in the Render dashboard.

> ⚠️ SQLite is a single file on local disk. On most platforms, the
> filesystem is ephemeral between deploys — attach a persistent volume/disk
> (both configs above include one), or switch `DATABASE_URL` to a managed
> Postgres instance for production use.

---

## 5. Important limitation: DMs require a prior interaction or an approved use case

Meta restricts who a Business/Creator account can message. Sending a DM to
someone via the Instagram Messaging API generally requires **one of**:

- The user has messaged your Instagram account within the last 24 hours (standard messaging window), **or**
- Your app uses the **comment-to-DM "Private Replies"** mechanism (`POST /{comment-id}/private_replies`), which Meta allows specifically for replying to a commenter even without a prior conversation — this is what `instagram.send_private_reply_to_comment()` in this app uses by default, **or**
- Your app has been through **App Review** and been approved for the relevant advanced messaging use case, for messaging outside these windows.

**To apply for the broader `instagram_manage_messages` permission:** App
Dashboard → App Review → Permissions and Features → request
`instagram_manage_messages`, and submit a screencast showing the comment →
DM flow along with a written use-case description. Approval typically takes
a few days to a couple of weeks.

Until approved, keep your app in Development Mode and test only with
accounts added under **Roles → Roles** in the app dashboard — this fully
exercises the flow without needing review.

---

## 6. Project structure

```
/
├── main.py              # FastAPI app entry point
├── instagram.py         # Instagram Graph API client (all outbound HTTP calls)
├── models.py             # SQLAlchemy models: Config, Campaign, ProcessedComment
├── database.py           # DB session/engine setup
├── routes/
│   ├── webhook.py         # Webhook verification + comment event handling
│   ├── dashboard.py       # HTML page routes
│   └── api.py             # REST API for campaigns/config (used by the frontend)
├── static/                # CSS + JS for the dashboard
├── templates/             # Jinja2 HTML templates
├── .env.example
├── Dockerfile
├── railway.toml
├── render.yaml
├── requirements.txt
└── README.md
```

## 7. Security notes

- `FACEBOOK_APP_SECRET` and the raw access token never touch the frontend — the Settings page only ever displays a masked version of the token.
- Every webhook POST is validated against the `X-Hub-Signature-256` header using HMAC-SHA256 with your App Secret; unsigned or mismatched requests are rejected with 403.
- `.env` is gitignored — never commit real credentials.

## 8. Health check

`GET /health` → `{"status": "ok"}` — used by Railway/Render/Docker health checks.
