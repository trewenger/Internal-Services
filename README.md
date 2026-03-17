# Internal Services V2

Unified internal web interface consolidating multiple tools into a single Flask application
with tab-based navigation. Deployed on an on-prem server behind IIS (HTTPS via internal AD CS certificate).

---

## Tech Stack

- **Backend:** Flask (Python) + Waitress (production WSGI)
- **Frontend:** Jinja2 templates + Tailwind CSS (CDN)
- **Scheduler:** APScheduler (BackgroundScheduler)
- **Auth:** itsdangerous signed tokens, Werkzeug password hashing
- **Email:** SMTP2GO API

---

## Tabs / Sections

| Section | Description |
|---|---|
| Retail Inventory Manager | Live SKU inventory synced from Fishbowl. Manual and automated sync modes. |
| Various Services | Scheduled internal reports and health checks (On-Time Performance, Tax System Health, Vendor Tracker, WIP Update). |
| Intuiflow | Placeholder (coming soon). |
| Settings | User management — invite, deactivate, reactivate, access control. |

---

## Local Development Setup

**Prerequisites:** Python 3.11+, pip

```bash
# 1. Clone the repo
git clone <repo-url>
cd INTERNAL_SERVICES_V2

# 2. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt
pip install -e ./API_Service_Network

# 4. Create .env file (see Environment Variables section below)

# 5. Run the dev server
python app.py
```

App runs at `http://localhost:5000`. Default login: `admin / changeme`.

---

## Production Deployment

```bash
cd C:\Apps\INTERNAL_SERVICES_V2
.venv\Scripts\python serve.py
```

Waitress binds to `127.0.0.1:5000`. IIS sits in front, terminates TLS, and proxies
HTTPS traffic to Flask.

The app is managed as a Windows service via NSSM.

---

## Environment Variables

Create a `.env` file at the project root (never commit this file):

```
SECRET_KEY=<random 32+ char string>
ADMIN_EMAIL=<email for error alerts>
SENDER_EMAIL=<from address for outgoing emails>
SMTP2GO_API_KEY=<your smtp2go api key>

FISHBOWL_SERVER_ADDRESS=localhost
FISHBOWL_PROD_PORT=<port>
FISHBOWL_TEST_PORT=<port>
FISHBOWL_APP_NAME=<app name>
FISHBOWL_APP_DESCRIPTION=<description>
FISHBOWL_APP_ID=<id>
FISHBOWL_USERNAME=<username>
FISHBOWL_PASSWORD=<password>
FISHBOWL_COMPANY_NAME=<company name>
```

All variables have fallback defaults so the app will start without a `.env` (credentials
will not function until real values are provided).

---

## Project Structure

```
INTERNAL_SERVICES_V2/
├── app.py              ← Flask entry point (dev)
├── serve.py            ← Waitress entry point (production)
├── config.py           ← All env-based config (single source of truth)
├── user_store.py       ← UserStore class — all reads/writes to credentials.json
├── blueprints/         ← One blueprint per section (auth, retail, services, settings, intuiflow)
├── templates/          ← Jinja2 templates, namespaced per section
├── static/js/          ← Frontend JS (retail.js)
└── API_Service_Network/
    ├── src/common/     ← Shared API clients (Fishbowl, Email, Google, etc.)
    ├── RetailInventoryManager/   ← InventoryData, Logger, FishbowlSync classes
    └── VariousInternalServices/  ← 4 service scripts + scheduler config
```

---

## Auth & Access Control

- Users stored in `credentials.json` (hashed passwords, per-section access levels)
- Access levels: `none`, `read`, `write` — per section per user
- Invite flow: Settings page → signed email link → user sets password → account activated
- Password reset: `/forgot-password` → signed email link (1h expiry) → `/reset-password/<token>`
- First run seeds `credentials.json` with `admin / changeme` — **change this immediately**

---

## Auto-created Files

These files are excluded from git and created automatically on first run:

| File | Contents |
|---|---|
| `credentials.json` | User store (seeded with `admin / changeme`) |
| `API_Service_Network/RetailInventoryManager/data.json` | SKU data + RIM config |
| `API_Service_Network/RetailInventoryManager/log.json` | Error log + audit log |
| `API_Service_Network/VariousInternalServices/services_config.json` | Service schedule + run state |
