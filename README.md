# AesthEase Clinic Bot 🌸

AI receptionist for beauty & wellness clinics.  
Handles patient enquiries, FAQ answering, and appointment booking — 24/7, automatically — across WhatsApp, Instagram DM, and Facebook Messenger.

---

## What it does

- Patient messages on WhatsApp / Instagram / Messenger → bot replies instantly
- Answers clinic FAQs from a JSON knowledge base (RAG with ChromaDB)
- Books, reschedules, and cancels appointments via Google Calendar
- Registers new patients (name, age, contact)
- Remembers full conversation history across sessions (SQLite)
- Admin dashboard to view patients, appointments, and conversation logs

---

## Architecture

```
Patient (WhatsApp / Instagram / Messenger)
    ↓
FastAPI webhook  ←  HMAC-SHA256 signature verification
    ↓
asyncio.Queue (one message at a time per user)
    ↓
LangGraph Agent  →  search_faq (RAG)
                 →  get_available_slots (Google Calendar)
                 →  book_appointment
                 →  cancel_appointment
                 →  register_patient
    ↓
SQLite (patients · appointments · messages · processed_messages)
    ↓
Reply sent back via Meta Graph API
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Channels | WhatsApp Cloud API · Instagram Messaging API · Facebook Messenger API |
| Backend | FastAPI + Python |
| AI agent | LangGraph StateGraph |
| RAG knowledge base | ChromaDB + OpenAI text-embedding-3-small |
| FAQ source | `faq/data.json` (JSON, loaded with jq_schema pattern) |
| Tool input validation | Pydantic (`ReservationTimeModel`, `DateModel`) |
| Appointment scheduling | Google Calendar API |
| Persistence | SQLite — 4 tables |
| Message safety | asyncio.Queue per user · HMAC-SHA256 webhook verification · idempotency deduplication |
| Deployment | Railway |

---

## Project structure

```
aesthease-clinic-bot/
├── src/
│   ├── api/
│   │   ├── main.py          # FastAPI — webhook receiver (WhatsApp / Messenger / Instagram)
│   │   └── admin.py         # Admin REST API (stats, patients, appointments, messages)
│   ├── agent/
│   │   └── graph.py         # LangGraph agent — tools, routing, history rebuild
│   ├── mcp_server/
│   │   └── calendar_tools.py# Google Calendar — check slots, create/delete events
│   └── shared/
│       ├── db.py            # SQLite — 4 tables, idempotency, history
│       ├── models.py        # Pydantic models + tool parameter validators
│       └── rag.py           # ChromaDB — index & query FAQ
├── faq/
│   └── data.json            # Clinic FAQ knowledge base (edit this to customise)
├── frontend/
│   └── dashboard.html       # Admin dashboard — open in browser, no build step
├── .env.example             # All required environment variables
├── Procfile                 # Railway deployment config
└── requirements.txt
```

---

## Quick start

```bash
git clone https://github.com/YOUR_USERNAME/aesthease-clinic-bot
cd aesthease-clinic-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in OPENAI_API_KEY at minimum — other keys needed for full WhatsApp integration

mkdir -p data
python -c "from src.shared.db import init_db; init_db()"
python -c "from src.shared.rag import index_faq_documents; index_faq_documents()"

uvicorn src.api.main:app --reload --port 8000
```

Test the agent locally (no WhatsApp needed):

```bash
curl -X POST http://localhost:8000/webhook/whatsapp \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{"changes": [{"value": {
      "messages": [{"from": "447700000001", "id": "test_001",
                    "type": "text", "text": {"body": "How much is Botox?"}}]
    }}]}]
  }'
```

Open the admin dashboard:

```bash
open frontend/dashboard.html   # macOS
# or double-click the file in Finder / Explorer
# Set API URL to http://localhost:8000 and token to value of ADMIN_TOKEN
```

---

## Environment variables

```env
# OpenAI
OPENAI_API_KEY=sk-...

# Meta (one token covers WhatsApp + Messenger + Instagram)
META_ACCESS_TOKEN=EAAxxxxxxx
META_APP_SECRET=your_app_secret        # Used for HMAC-SHA256 webhook verification
WHATSAPP_PHONE_NUMBER_ID=1234567890

# Webhook
WEBHOOK_VERIFY_TOKEN=aesthease_verify_2026

# Google Calendar
GOOGLE_CALENDAR_ID=your_calendar@group.calendar.google.com
GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}

# Database
DB_PATH=data/clinic.db

# Admin dashboard
ADMIN_TOKEN=your_admin_token_here
```

---

## Webhook URLs (register in Meta Developer Console)

```
WhatsApp:  https://your-app.railway.app/webhook/whatsapp
Messenger: https://your-app.railway.app/webhook/messenger
Instagram: https://your-app.railway.app/webhook/instagram
```

Use the same `WEBHOOK_VERIFY_TOKEN` value for all three.

---

## Customising the knowledge base

Edit `faq/data.json` — each entry is a question/answer pair:

```json
[
  {
    "question": "How much does X cost?",
    "answer": "X costs £Y per session."
  }
]
```

After editing, re-index:

```bash
python -c "from src.shared.rag import index_faq_documents; index_faq_documents()"
```

---

## Key engineering patterns

| Pattern | Source | File |
|---|---|---|
| WhatsApp Cloud API webhook | GreatHayat/langgraph-whatsapp-bot | `src/api/main.py` |
| Google Calendar integration | GreatHayat/langgraph-whatsapp-bot | `src/mcp_server/calendar_tools.py` |
| JSON knowledge base + Pydantic validators | Nachoeigu/agentic-customer-service-medical-clinic | `src/shared/models.py`, `rag.py` |
| One-tool-at-a-time prompt rule | Nachoeigu/agentic-customer-service-medical-clinic | `src/agent/graph.py` |
| SQLite 4-table persistence | oxi-p/DentalDesk | `src/shared/db.py` |
| asyncio.Queue per-user message queuing | oxi-p/DentalDesk | `src/api/main.py` |
| HMAC-SHA256 webhook verification | oxi-p/DentalDesk | `src/api/main.py` |
| Conversation history rebuild from DB | oxi-p/DentalDesk | `src/agent/graph.py` |
| WhatsApp markdown formatting | oxi-p/DentalDesk | `src/api/main.py` |
| Status update filtering | oxi-p/DentalDesk | `src/api/main.py` |

---

## Deploying to Railway

1. Push this repo to GitHub
2. Create a new Railway project → Deploy from GitHub repo
3. Add all environment variables in Railway dashboard
4. Railway auto-detects the `Procfile` and runs `uvicorn`
5. Copy the Railway public URL and register it as your Meta webhook

---

## Admin dashboard

Open `frontend/dashboard.html` in any browser.  
Set the API URL to your Railway domain and enter your `ADMIN_TOKEN`.  
No login server required — authentication is handled via the token header.

Features: patient list · appointment management · per-patient conversation viewer · live stats by channel.
