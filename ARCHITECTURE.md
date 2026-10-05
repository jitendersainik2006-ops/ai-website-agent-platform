# AI Website Agent Platform - Architecture Plan

## 1. Complete System Architecture

The platform is a multi-tenant SaaS product. A tenant is one business. Every record is scoped by `tenant_id`, so the same platform can safely serve many businesses without company-specific code.

```text
Business website -> Embed loader -> Isolated chat widget (iframe)
                                      |
Admin dashboard --------------------> Flask API
                                      |
              Auth / tenant access / validation / audit logging
                                      |
       MongoDB <-> Services <-> LLM gateway / retrieval / scheduling
                                      |
                         Calendar and notification adapters
```

- The public widget is embedded on a customer website and communicates only with public API endpoints.
- The admin dashboard uses protected admin endpoints to manage business content and operations.
- Flask contains the business rules. Browser code never talks directly to MongoDB, calendars, or the LLM provider.
- MongoDB stores tenant data, conversations, leads, availability, appointments, and audit records.
- The LLM gateway performs retrieval, applies policies, and can call tightly controlled server-side tools.
- Calendar and email/SMS providers are adapters, so providers can be changed without rewriting scheduling logic.
- A background worker will handle slow work such as notifications, document processing, analytics aggregation, and calendar retries.

## 2. Frontend Pages

Public experience:

- Embeddable chat widget: conversation, service interest, contact capture, consent, available slot picker, booking confirmation, and human-support fallback.
- Optional demo host page: used to test a configured widget before placing it on a customer site.

Admin experience:

- Login and password reset.
- Dashboard: conversation, lead, booking, and conversion summaries using Chart.js.
- Company profile: name, description, address, contacts, working hours, branding, timezone.
- Services: create, edit, publish, archive, and define appointment duration.
- Knowledge and FAQs: maintain approved answers and upload/import approved documents.
- Leads: searchable pipeline with owner, notes, status, source, and follow-up actions.
- Appointments: calendar/list view, availability, blocked dates, cancel/reschedule actions.
- Agent settings: welcome message, tone, escalation rules, lead fields, approved sources, and safety settings.
- Embed settings: allowed domains, theme, install snippet, public widget key, and widget preview.
- Team, roles, integrations, audit log, and security settings.

Every visible command will call a real API and show loading, success, empty, and error states.

## 3. Backend Modules

- `app`: Flask application factory, configuration, extensions, error handling, health checks.
- `api`: versioned blueprints for public widget APIs and protected admin APIs.
- `auth`: login, refresh/revocation, password reset, invitations, role checks, session protection.
- `tenancy`: resolves the current tenant and enforces tenant filters everywhere.
- `organizations`, `services`, `faqs`, `knowledge`: business-content CRUD and publishing.
- `conversations`, `leads`, `appointments`, `availability`: core product workflows.
- `agent`: prompt assembly, retrieval, tool authorization, response filtering, evaluation hooks.
- `integrations`: LLM, calendar, email/SMS, storage, and analytics provider adapters.
- `repositories`: MongoDB persistence and indexes, isolated from HTTP routes.
- `schemas`: request/response validation and serialization.
- `security`: rate limiting, CORS, CSRF, audit logging, encryption helpers, redaction.
- `workers`: asynchronous notifications, ingestion, retries, and scheduled maintenance.

## 4. MongoDB Collections And Important Fields

- `tenants`: `_id`, name, slug, status, timezone, branding, plan, created_at.
- `users`: `_id`, email, password_hash, name, mfa_config, status, created_at.
- `memberships`: `tenant_id`, `user_id`, role, permissions, invited_by, status.
- `widget_configs`: `tenant_id`, public_key, allowed_origins, theme, enabled, version.
- `services`: `tenant_id`, title, description, status, tags, appointment_type_id, published_at.
- `faqs`: `tenant_id`, question, answer, category, status, source_url, updated_at.
- `knowledge_documents` and `knowledge_chunks`: `tenant_id`, source, content, metadata, embedding, status, version.
- `agent_settings`: `tenant_id`, system_policy, greeting, tone, lead_fields, escalation_rules, model_config.
- `conversations`: `tenant_id`, visitor_id, channel, status, locale, last_message_at, lead_id.
- `messages`: `tenant_id`, conversation_id, role, content, tool_calls, citations, created_at.
- `leads`: `tenant_id`, name, email, phone, company, service_id, status, score, consent, source, conversation_id, owner_id.
- `appointment_types`: `tenant_id`, name, duration_minutes, buffer_minutes, active.
- `availability_rules`: `tenant_id`, timezone, weekday, start_time, end_time, appointment_type_id.
- `blackout_dates`: `tenant_id`, start_at, end_at, reason.
- `appointments`: `tenant_id`, lead_id, service_id, start_at, end_at, timezone, status, provider_event_id, idempotency_key.
- `integrations`: `tenant_id`, provider, encrypted_credentials, configuration, status.
- `audit_logs`: `tenant_id`, actor_id, action, entity_type, entity_id, metadata, ip, created_at.
- `analytics_events`: `tenant_id`, event_name, anonymous_visitor_id, conversation_id, metadata, created_at.

Critical indexes include `tenant_id` on every tenant collection, `{tenant_id, email}` for leads, `{tenant_id, start_at}` for appointments, unique public widget keys, and TTL indexes for temporary sessions and selected logs.

## 5. API Endpoint Plan

All routes use `/api/v1`. Public routes accept only a scoped widget key and an allowed browser origin; admin routes require a user session and role.

- `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/password-reset`.
- `GET|PATCH /admin/tenant`, `GET|POST|PATCH|DELETE /admin/services`, `/admin/faqs`, `/admin/knowledge`.
- `GET|POST|PATCH /admin/leads`, `POST /admin/leads/{id}/notes`, `POST /admin/leads/{id}/assign`.
- `GET|POST|PATCH /admin/appointments`, `POST /admin/appointments/{id}/cancel`, `POST /admin/appointments/{id}/reschedule`.
- `GET|PUT /admin/availability`, `/admin/agent-settings`, `/admin/widget-config`, `/admin/analytics`, `/admin/audit-logs`.
- `GET /public/widget-config`, `POST /public/conversations`, `POST /public/conversations/{id}/messages`.
- `POST /public/leads`, `GET /public/availability/dates`, `GET /public/availability/slots`.
- `POST /public/appointments`, `POST /public/appointments/{id}/cancel`.
- `GET /health` and restricted operational metrics endpoints.

## 6. AI Agent Architecture

The agent uses retrieval-augmented generation (RAG), not a single hard-coded prompt.

1. Resolve tenant from the widget key and validate the origin.
2. Load only the tenant's published company profile, services, FAQs, and approved knowledge chunks.
3. Classify the visitor intent: information, FAQ, service interest, lead capture, scheduling, reschedule, or escalation.
4. Build a policy-bound prompt that includes tenant context and conversation history.
5. Call the LLM through a server-only provider adapter. API credentials stay in environment-managed secrets.
6. Permit only structured server tools: search approved knowledge, create/update lead with consent, query availability, create/cancel/reschedule appointment, or request human follow-up.
7. Validate each tool payload, enforce tenant scope, store the result, then return a concise answer with source references where useful.

The agent cannot run arbitrary code, access other tenants, disclose hidden prompts or secrets, or write directly to MongoDB. Low-confidence answers trigger a clear handoff path rather than invented information.

## 7. Appointment Scheduling Workflow

1. The visitor selects a service or consultation type.
2. The widget requests available dates and slots in the business timezone, then displays the visitor's local timezone.
3. The visitor selects a slot and gives required contact details plus consent.
4. The API validates the service, availability rules, blackout dates, business hours, and existing bookings.
5. The API creates a short reservation/lock and performs an atomic final conflict check.
6. It creates the appointment with an idempotency key, optionally creates an external calendar event, and queues confirmations.
7. The widget shows a confirmed booking; the dashboard receives the lead and appointment immediately.
8. Cancellation and rescheduling repeat validation and preserve an audit trail.

Initial delivery can use platform-managed availability. Google Calendar and Microsoft 365 adapters can be added after the core flow is stable.

## 8. Lead Management Workflow

Interest can be detected during chat or explicitly submitted through a contact form. The agent asks for consent before collecting personal data, validates the submitted fields, and creates or updates a tenant-scoped lead without overwriting meaningful existing information.

The lead is linked to its conversation, selected service, source page, appointment, score, and status. Team members can assign an owner, add notes, change the pipeline stage, filter by service/source, and trigger approved follow-up actions. All sensitive updates create audit records.

## 9. Admin Dashboard Structure

The dashboard navigation should be: Overview, Inbox, Leads, Appointments, Services, Knowledge, Agent, Embed, Analytics, Team, Integrations, and Security. It is an operational workspace rather than a decorative landing page. Tables support search, filters, sorting, pagination, and detail views. Roles determine which sections and commands a person can access.

## 10. Website Embed Architecture

Businesses install a small versioned loader:

```html
<script src="https://platform.example/widget-loader.js" data-widget-key="public_key"></script>
```

The loader creates an iframe hosted by the platform. The iframe isolates widget CSS and JavaScript from the host business website. It receives only theme/configuration data, validates `postMessage` origins, and uses a short-lived anonymous visitor session. The public key identifies a widget configuration; it is not a database credential. Allowed domains, version pinning, CSP, Subresource Integrity where suitable, and throttling protect the embed surface.

## 11. Authentication And Authorization

Admins authenticate with email and password stored using Argon2id (or bcrypt if Argon2id is unavailable). The app uses short-lived access tokens and rotating, Secure, HttpOnly, SameSite refresh cookies. Password reset tokens are single-use and expire quickly. MFA is recommended for owners and administrators.

Roles: `owner`, `admin`, `manager`, `agent`, and `viewer`. A central authorization check verifies both role permissions and `tenant_id` ownership for every protected operation. Invitations, account disabling, token revocation, and session listings are included in the security area.

## 12. Security Considerations

- Enforce HTTPS, secure headers, CSP, strict CORS allow-lists, CSRF protection for cookie endpoints, and browser-safe output encoding.
- Validate every request using schemas; limit request size, file types, and upload sources.
- Apply per-IP, per-widget, and per-account rate limits; add WAF and bot protection in deployment.
- Keep provider credentials and encryption keys in a secret manager, never in HTML, JavaScript, source control, or MongoDB plaintext.
- Encrypt sensitive integration credentials and selected PII fields; redact PII and secrets from logs.
- Apply tenant filtering in repositories, authorization in services, and tests that attempt cross-tenant access.
- Defend the LLM layer against prompt injection: retrieve trusted tenant content only, separate instructions from documents, constrain tools, validate parameters, and maintain an evaluation set of adversarial prompts.
- Protect document ingestion against SSRF and malicious files. Use malware scanning when file upload is enabled.
- Keep dependency updates, backups, retention/deletion policies, monitoring, incident logging, and restore drills in the release process.

## 13. Recommended Folder Structure

```text
blackinitel,jitender/
  ARCHITECTURE.md
  README.md
  backend/
    app/
      api/v1/  auth/  domain/  services/  repositories/
      integrations/  security/  schemas/  workers/
    tests/
    requirements.txt
  frontend/
    admin/       # HTML, CSS, JavaScript dashboard
    widget/      # iframe widget and versioned loader
    shared/
  infra/
    docker/  nginx/  deployment/
  docs/
  .env.example
  docker-compose.yml
```

## 14. Development Phases

1. Confirm requirements, tenant boundaries, data retention, roles, and threat model.
2. Create Flask/MongoDB foundation, environment configuration, application factory, tenant middleware, authentication, and audit logging.
3. Build the admin dashboard foundation and functional CRUD for profile, services, FAQs, availability, and agent settings.
4. Build the isolated widget, public configuration API, conversation storage, and secure embed validation.
5. Add the LLM gateway, approved knowledge retrieval, citations, tool validation, and human handoff.
6. Implement lead capture, pipeline management, availability, atomic booking, and confirmation notifications.
7. Add calendar integrations, analytics, team administration, operations screens, and hardening.
8. Perform security review, load testing, backups/restore validation, pilot deployment, and monitored iteration.

The first working MVP should include: tenant setup, admin-managed services/FAQs, a real embedded widget, chat with approved knowledge, consent-based lead capture, availability lookup, appointment booking, and admin visibility of the resulting data.

## 15. Testing Strategy

- Unit tests: schema validation, permissions, tenant filtering, service logic, scheduling calculations, and agent tool authorization.
- Integration tests: Flask endpoints against an isolated MongoDB database, including indexes and error cases.
- End-to-end browser tests: login, content management, embedded chat, lead capture, slot selection, booking, cancellation, and responsive widget behavior.
- Contract tests: widget-loader to public API and provider adapter interfaces.
- AI evaluations: a versioned set of factual, ambiguous, unsafe, prompt-injection, and cross-tenant prompts with expected outcomes.
- Security tests: authentication failures, privilege escalation, IDOR/cross-tenant probes, XSS, CSRF, rate limits, secret scanning, and dependency scanning.
- Reliability tests: duplicate booking attempts, provider failures, retries, idempotency, backup restoration, and audit-log integrity.
- Performance tests: concurrent widget traffic, availability calculations, database query plans, and load targets before production.

## Implementation Boundary

No application code has been created in this folder. This document is the approved starting point for the next instruction: implementation should begin in Phase 2, after the product decisions in Phase 1 are confirmed.
