# AI Website Agent Platform

Local-first multi-tenant MVP for embedding a business AI assistant. Each tenant owns its profile, services, FAQs, knowledge, widget key, conversations, leads, business hours, and appointments.

## Features

- Argon2 admin passwords and short-lived tenant-aware JWTs.
- Role-protected admin REST API and strict tenant filters.
- Business profile, services, FAQs, knowledge, hours, blocked periods, leads, conversations, appointments, and analytics.
- Safe local knowledge agent. It answers only from tenant-published information and returns an explicit fallback when information is missing.
- Iframe widget loader: `script src="http://127.0.0.1:5000/widget-loader.js" data-widget-key="..."`.
- Widget booking, rescheduling, and cancellation use the protected public appointment API. The management token remains only in the live iframe memory and is cleared after cancellation.
- Functional HTML/CSS/JavaScript admin dashboard at `http://127.0.0.1:5000/`.
- Admin dashboard review views for conversations, leads, appointment detail/history, and working-hour/blocked-period availability. Owners, admins, and managers can submit the full seven-day schedule atomically; viewer write controls are hidden and enforced again by the API.
- Server-side notification and calendar provider boundaries with local, sanitized test adapters. Appointment persistence remains authoritative if a provider fails.

## Local Setup

Run MongoDB locally on `127.0.0.1:27017`, then in PowerShell:

```powershell
cd "C:\Users\jitendersaini2006\OneDrive\Documents\New project\blackinitel,jitender\backend"
.\venv314\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
# Set strong, different SECRET_KEY and JWT_SECRET_KEY values in .env.
.\venv314\Scripts\python.exe seed_auth_demo.py
.\venv314\Scripts\python.exe run.py
```

Dashboard login: `admin@blackintel.com` / `ChangeMe123!` for local demonstration only. Demo widget key: `demo_black_intel_widget_key`.

Widget test URL: `http://127.0.0.1:5000/widget-frame.html?widget_key=demo_black_intel_widget_key`.

Run tests:

```powershell
.\venv314\Scripts\python.exe -m pytest -q
```

## API Overview

`POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `GET /api/v1/admin/context`.

Admin CRUD: `/api/v1/admin/business`, `/services`, `/faqs`, `/knowledge`, `/business-hours`, `/availability/blocked`, `/leads`, `/conversations`, `/appointments`, `/analytics`, `/widget-config`.

Appointment administration: `GET /api/v1/admin/appointments/<id>` returns the tenant-scoped appointment, history, and linked lead without a management-token digest. Owners, admins, and managers can use `POST /api/v1/admin/appointments/<id>/cancel` and `POST /api/v1/admin/appointments/<id>/reschedule` with `{"start_at":"ISO-8601 time with timezone"}`. Both reuse the server-side slot rules, audit trail, calendar adapter, and notification lifecycle.

Public widget: `/api/v1/public/widget-config`, `/public/conversations`, `/public/conversations/<id>/messages`, `/api/v1/chat`, `/public/leads`, `/public/availability/slots`, `/public/appointments`.

New bookings return a one-time `manage_token`. Keep it only with the visitor's booking confirmation; it is required with the tenant widget key for `POST /api/v1/public/appointments/<id>/cancel` and `/reschedule`. The server stores only a keyed digest of that token.

## Security Notes

Admin tenant identity comes only from validated JWT plus an active database membership. Public endpoints resolve tenants only from an enabled widget public key and optional origin allow-list. Browser code never receives MongoDB or JWT secrets. Appointment token digests and password hashes are filtered from serialized API responses. Basic `nosniff`, referrer, and browser-permission headers are included without blocking the iframe embed. `.env`, virtual environments, caches, and database folders are ignored by Git.

Admin write operations are audited, including business profile, business-hours, widget configuration, blocked availability, leads, and appointment lifecycle changes. Configure `SECRET_KEY` and `JWT_SECRET_KEY` to strong, different values before any non-local deployment; do not use the seeded demo password or widget key outside local testing.

## MVP Limitations

The local agent is an intentionally safe deterministic knowledge retriever, not an external LLM. It answers only sufficiently relevant published tenant content, uses configured business hours for hours questions, and falls back when pricing or other information is unconfirmed. Live email/calendar providers, refresh tokens, CSRF cookie sessions, provider queues, production CORS policy, HTTPS termination, and production deployment hardening are future work. The local adapters already define the create, update, cancel, notification, and availability-shaped integration boundary without external credentials.
