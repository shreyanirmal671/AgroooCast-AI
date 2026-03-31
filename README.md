# AgroCast AI (Flask + Web Frontend)

AgroCast AI is a farm intelligence platform with:
- Flask backend with JWT auth and role-based access
- Server-rendered multipage frontend (Flask templates + HTML/CSS/JavaScript)
- English + Hindi language toggle for farmers
- Multi-farm management (save/switch/delete farm locations)
- India state/district presets and location search
- Farm-wise historical trend storage and comparison charts
- Farm-level alert rule editor and channel preferences (WhatsApp/SMS/Email)
- Background notification queue with retry and delivery logs
- ML temperature forecasting pipeline (LightGBM)
- Climate risk alerts with actionable farming advice
- Satellite and weather intelligence ingestion pipeline

## Architecture

- `backend_api.py`: Flask backend + API + template page routes
- `templates/`: Route-specific server-rendered pages (`login`, `dashboard`, `forecast`, etc.)
- `frontend/styles.css`: Responsive UI styling
- `frontend/app.js`: Frontend logic (auth, forecast, alerts, admin)
- `backend_database.py`: SQLAlchemy user repository and schema
- `security.py`: Access/refresh JWT handling and role guards
- `ml_engine.py`: Model training and forecasting
- `processor.py`: Risk analysis and farmer advice engine
- `data_engine.py`: Weather and satellite providers
- `satellite_engine.py`: Google Earth Engine (optional)
- `wsgi.py`: Production WSGI entrypoint
- `.replit`: Replit one-command run configuration
- `Procfile`: Cloud process definition (Render/Replit/Heroku-style)

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
set JWT_SECRET_KEY=replace-with-strong-secret
set JWT_EXPIRE_MINUTES=120

# Live alert delivery (Twilio + SMTP)
set ENABLE_LIVE_ALERT_DISPATCH=true
set TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
set TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
set TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
set TWILIO_SMS_FROM=+1234567890
set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set SMTP_USERNAME=your-email@example.com
set SMTP_PASSWORD=your-app-password
set SMTP_FROM=your-email@example.com
set SMTP_USE_TLS=true

# Optional for Google Earth Engine service account auth
set ENABLE_GEE=true
set GEE_PROJECT=your-gcp-project-id
set GEE_SERVICE_ACCOUNT=service-account@project.iam.gserviceaccount.com
set GEE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"

# Voice Assistant (Whisper + Gemini)
set OPENAI_API_KEY=your-openai-api-key
set GEMINI_API_KEY=your-gemini-api-key
```

3. Train model (optional; auto-trained on first forecast if missing):
```bash
python ml_engine.py
```

4. Start integrated backend + frontend server:
```bash
python backend_api.py
```

5. Open in browser:
```text
http://127.0.0.1:8000/login
```

6. Bootstrap first admin (one-time):
```bash
python create_admin.py
```

## Presentation Run Guide (Windows)

1. Open PowerShell in project root and activate virtual environment:
```powershell
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:
```powershell
python -m pip install -r requirements.txt
```

3. Start app:
```powershell
python backend_api.py
```

4. Open:
```text
http://127.0.0.1:8000/login
```

5. Demo flow for judges:
- Signup/Login as farmer
- Dashboard: set location or use state/city preset, click Refresh
- Show live metrics, predicted charts, and farmer-friendly chart summaries
- Add a farm in My Farms and click Use
- Forecast: show upcoming rows and values
- Farm Map: show selected farm marker and NDVI ring
- Alerts: show risk alerts + advice text
- Insights: show trend chart, comparison chart, alert settings, delivery logs
- (Admin login) Admin tab: load users and role management

## Live Notification Demo Guide (Email + WhatsApp)

Use this sequence to show real-time alert delivery to judges.

1. Open PowerShell in project root and activate venv:
```powershell
.\.venv\Scripts\Activate.ps1
```

2. Set live provider environment variables in the same terminal:
```powershell
$env:ENABLE_LIVE_ALERT_DISPATCH="true"

$env:TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:TWILIO_AUTH_TOKEN="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:TWILIO_WHATSAPP_FROM="whatsapp:+14155238886"
$env:TWILIO_SMS_FROM="+1234567890"

$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="yourmail@gmail.com"
$env:SMTP_PASSWORD="your_app_password"
$env:SMTP_FROM="yourmail@gmail.com"
$env:SMTP_USE_TLS="true"
```

3. Start app:
```powershell
python backend_api.py
```

4. Open:
```text
http://127.0.0.1:8000/login
```

5. In app (farmer account):
- Select a farm.
- Go to Insights.
- Click Quick Setup (now uses farm location + crop profile recommendations).
- Enter recipient WhatsApp number and email if blank.
- Click Save Settings.
- Click Send Test Alert.

6. Show judges:
- Incoming WhatsApp and email on device/inbox.
- Delivery Logs table in Insights.

Twilio Sandbox note:
- Join sandbox from recipient number before demo.
- Keep recipient number in international format (example: +91XXXXXXXXXX).

Troubleshooting checklist:
- Use /forecast endpoint (not /api/forecast).
- Ensure ENABLE_LIVE_ALERT_DISPATCH=true.
- Recheck TWILIO_* and SMTP_* values.
- If provider fails, show Delivery Logs details as transparent proof of dispatch attempts.

## Backend Feature Flow (How It Works)

1. Authentication and session:
- `POST /auth/signup` creates farmer/admin user
- `POST /auth/login` returns access + refresh JWT tokens
- `POST /auth/refresh` rotates short-lived access token
- Frontend automatically retries protected requests with refresh token

2. Location and weather intelligence:
- `GET /locations/presets` returns India state/city presets (including Gujarat)
- `GET /locations/search` supports city/district search
- `POST /weather` fetches hourly weather from Open-Meteo
- `POST /satellite` fetches satellite indices from NASA/GEE or fallback provider

3. Forecast pipeline:
- `POST /forecast` is the main intelligence endpoint
- Pipeline sequence:
	- validate user/token
	- resolve farm location from `farm_id` or lat/lon
	- fetch weather + satellite data
	- run ML model (`ml_engine.py`) to generate microclimate predictions
	- run risk logic (`processor.py`) to generate alerts + advice
	- apply farm-level custom alert rules
	- enqueue notification dispatch task when custom alerts are present
	- store forecast snapshot in farm history

4. Farm management:
- `GET /farms`, `POST /farms`, `DELETE /farms/{farm_id}`
- `GET /farms/{farm_id}/history`
- `POST /farms/compare`
- `GET/PUT /farms/{farm_id}/settings` for alert thresholds/channels
- `GET /farms/{farm_id}/settings/recommendations` for smart farm/crop-based threshold suggestions
- `GET /farms/{farm_id}/delivery-logs` for WhatsApp/SMS/email audit trail

5. Notification and reliability:
- Notification sends are queued via background worker (`task_queue.py`)
- Retries are applied for transient failures
- Delivery results are persisted and shown in Insights page logs

## What To Keep / What Can Be Ignored

- Keep core runtime/code folders: `backend_*.py`, `data_engine.py`, `ml_engine.py`, `processor.py`, `notify_engine.py`, `security.py`, `task_queue.py`, `frontend/`, `templates/`, `models/`, `datasets/`, `alembic/`.
- Generated local artifacts such as `__pycache__/` and temporary `smoke_test.db` are safe to delete.

## Quick Start (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_backend.ps1
```

or

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_frontend.ps1
```

Both scripts now start the same integrated app on port 8000.

## API Endpoints

- `GET /health`
- `POST /auth/signup`
- `POST /auth/login`
- `POST /auth/refresh`
- `POST /weather`
- `POST /satellite`
- `POST /forecast`
- `POST /api/chatbot-text`
- `POST /api/chatbot-voice`
- `GET /locations/search?q=indore`
- `GET /locations/presets`
- `GET /farms`
- `POST /farms`
- `DELETE /farms/{farm_id}`
- `GET /farms/{farm_id}/history?limit=60`
- `POST /farms/compare`
- `GET /farms/{farm_id}/settings`
- `PUT /farms/{farm_id}/settings`
- `GET /farms/{farm_id}/settings/recommendations`
- `GET /farms/{farm_id}/delivery-logs?limit=25`
- `GET /admin/users` (admin only)
- `PATCH /admin/users/{username}/role` (admin only)

`/forecast` returns satellite data, predictions, risk alerts, and farmer advice in a single payload.
When custom alerts trigger for a farm, `/forecast` also returns `notification_delivery` status for WhatsApp/SMS/email dispatch.

## Multipage UI Routes

- `/login`
- `/app/dashboard`
- `/app/forecast`
- `/app/map`
- `/app/alerts`
- `/app/insights`
- `/app/admin`

The dashboard auto-refreshes forecast/weather for the selected farm every 5 minutes while the tab is visible.

## Notes

- Frontend is served directly by Flask from `frontend/`.
- Access token is short-lived; refresh token is used automatically by the frontend.
- SQLite is the default database (`agrocast_dev.db`), suitable for local and Replit MVP deployment.
- You can still set `DATABASE_URL` for PostgreSQL/MySQL in future scaling stages.
- Roles supported: `farmer`, `admin`.

## Replit / Cloud Deploy

- Replit run command is preconfigured in `.replit`.
- WSGI app entrypoint: `wsgi:application`.
- Procfile command: `gunicorn --bind 0.0.0.0:${PORT:-8000} wsgi:application`.

## Alembic Migrations

1. Ensure `DATABASE_URL` is set.
2. Apply migrations:
```bash
alembic -c alembic.ini upgrade head
```

Initial migration file: `alembic/versions/0001_create_users_table.py`.
