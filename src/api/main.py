"""
FastAPI — multi-channel webhook receiver.
Implements Repo 3 (DentalDesk) patterns:
  - HMAC-SHA256 signature verification
  - asyncio.Queue per user (prevents concurrent message scrambling)
  - is_status_update() filter
  - format_message_content() WhatsApp markdown conversion
"""
import os
import hmac
import hashlib
import asyncio
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from src.agent.graph import process_message
from src.shared.db import init_db, is_already_processed, mark_as_processed
from src.api.admin import router as admin_router

app = FastAPI(title="AesthEase Clinic Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)
app.mount("/dashboard", StaticFiles(directory="src/static", html=True), name="static")

META_TOKEN     = os.getenv("META_ACCESS_TOKEN")
WA_PHONE_ID    = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
VERIFY_TOKEN   = os.getenv("WEBHOOK_VERIFY_TOKEN", "aesthease_verify_2026")
APP_SECRET     = os.getenv("META_APP_SECRET", "")  # For HMAC-SHA256 verification

# ── Per-user asyncio queues (Repo 3 pattern) ──────────────────────────────────
# Prevents race condition when a user sends two messages in quick succession.
_user_queues: dict[str, asyncio.Queue] = {}
_user_workers: dict[str, asyncio.Task] = {}


def get_user_queue(phone: str) -> asyncio.Queue:
    if phone not in _user_queues:
        _user_queues[phone] = asyncio.Queue()
    return _user_queues[phone]


async def user_worker(phone: str):
    """Process one message at a time per user."""
    queue = get_user_queue(phone)
    while True:
        task = await queue.get()
        try:
            await task()
        except Exception as e:
            print(f"Worker error for {phone}: {e}")
        finally:
            queue.task_done()


def ensure_worker(phone: str):
    if phone not in _user_workers or _user_workers[phone].done():
        _user_workers[phone] = asyncio.create_task(user_worker(phone))


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    init_db()


# ── HMAC-SHA256 signature verification (Repo 3) ───────────────────────────────

def verify_signature(payload: bytes, signature_header: str) -> bool:
    """
    Meta sends X-Hub-Signature-256: sha256=<hex>
    We verify it against APP_SECRET to reject forged webhooks.
    """
    if not APP_SECRET:
        return True  # Skip in dev if secret not set
    expected = "sha256=" + hmac.new(
        APP_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


# ── Status update filter (Repo 3) ─────────────────────────────────────────────

def is_status_update(value: dict) -> bool:
    """
    Meta sends delivered/read receipts as webhook events.
    These have 'statuses' key instead of 'messages'. Ignore them.
    """
    return "statuses" in value or "messages" not in value


# ── WhatsApp markdown formatter (Repo 3) ──────────────────────────────────────

def format_message_content(text: str) -> str:
    """
    Convert standard markdown to WhatsApp markdown.
    WhatsApp uses *bold* not **bold**, _italic_ not *italic*.
    """
    import re
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)   # **bold** → *bold*
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'_\1_', text)  # *italic* → _italic_
    text = re.sub(r'#{1,6}\s+(.+)', r'*\1*', text)    # # Heading → *Heading*
    return text


# ── Shared webhook verification ───────────────────────────────────────────────

def verify_meta_webhook(request: Request):
    params = dict(request.query_params)
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge"), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@app.get("/webhook/whatsapp")
async def verify_whatsapp(request: Request):
    return verify_meta_webhook(request)


@app.post("/webhook/whatsapp")
async def receive_whatsapp(request: Request):
    raw_body = await request.body()

    # HMAC-SHA256 signature check (Repo 3)
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(raw_body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = await request.json() if not raw_body else __import__("json").loads(raw_body)

    try:
        value = body["entry"][0]["changes"][0]["value"]

        # Filter delivered/read receipts (Repo 3: is_status_update)
        if is_status_update(value):
            return {"status": "ok"}

        message = value["messages"][0]
        phone      = message["from"]
        message_id = message.get("id", "")

        # Idempotency — skip if already processed (Repo 3: 4th table)
        if is_already_processed(message_id):
            return {"status": "ok"}
        mark_as_processed(message_id)

        if message.get("type") != "text":
            await send_whatsapp(phone, "Sorry, I can only handle text messages right now.")
            return {"status": "ok"}

        text = message["text"]["body"]

        # Push to per-user queue (Repo 3: asyncio.Queue)
        ensure_worker(phone)
        queue = get_user_queue(phone)

        async def handle():
            reply = process_message(phone, text, channel="whatsapp")
            formatted = format_message_content(reply)
            await send_whatsapp(phone, formatted)

        await queue.put(handle)

    except (KeyError, IndexError):
        pass

    return {"status": "ok"}


async def send_whatsapp(phone: str, text: str):
    import httpx
    url = f"https://graph.facebook.com/v19.0/{WA_PHONE_ID}/messages"
    async with httpx.AsyncClient() as client:
        r = await client.post(url,
            headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": text}}
        )
        if r.status_code != 200:
            print(f"WhatsApp send error: {r.text}")


# ── Facebook Messenger ────────────────────────────────────────────────────────

@app.get("/webhook/messenger")
async def verify_messenger(request: Request):
    return verify_meta_webhook(request)


@app.post("/webhook/messenger")
async def receive_messenger(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(raw_body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = __import__("json").loads(raw_body)
    try:
        for entry in body.get("entry", []):
            for event in entry.get("messaging", []):
                if "message" not in event:
                    continue
                sender_id  = event["sender"]["id"]
                message_id = event["message"].get("mid", "")
                text       = event["message"].get("text", "")
                if not text:
                    continue

                if is_already_processed(message_id):
                    continue
                mark_as_processed(message_id)

                phone = f"fb_{sender_id}"
                ensure_worker(phone)
                queue = get_user_queue(phone)

                async def handle(sid=sender_id, t=text, p=phone):
                    reply = process_message(p, t, channel="messenger")
                    await send_messenger(sid, format_message_content(reply))

                await queue.put(handle)
    except (KeyError, IndexError):
        pass
    return {"status": "ok"}


async def send_messenger(recipient_id: str, text: str):
    import httpx
    async with httpx.AsyncClient() as client:
        await client.post("https://graph.facebook.com/v19.0/me/messages",
            headers={"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"},
            json={"recipient": {"id": recipient_id}, "message": {"text": text}}
        )


# ── Instagram ─────────────────────────────────────────────────────────────────

@app.get("/webhook/instagram")
async def verify_instagram(request: Request):
    return verify_meta_webhook(request)


@app.post("/webhook/instagram")
async def receive_instagram(request: Request):
    raw_body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(raw_body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")

    body = __import__("json").loads(raw_body)
    try:
        for entry in body.get("entry", []):
            for event in entry.get("messaging", []):
                if "message" not in event:
                    continue
                sender_id  = event["sender"]["id"]
                message_id = event["message"].get("mid", "")
                text       = event["message"].get("text", "")
                if not text:
                    continue

                if is_already_processed(message_id):
                    continue
                mark_as_processed(message_id)

                phone = f"ig_{sender_id}"
                ensure_worker(phone)
                queue = get_user_queue(phone)

                async def handle(sid=sender_id, t=text, p=phone):
                    reply = process_message(p, t, channel="instagram")
                    await send_messenger(sid, format_message_content(reply))

                await queue.put(handle)
    except (KeyError, IndexError):
        pass
    return {"status": "ok"}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/")
async def health():
    return {"status": "running", "channels": ["whatsapp", "messenger", "instagram"]}
