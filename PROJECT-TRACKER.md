# PROJECT TRACKER — No-Code Workflow Automation

> Single source of truth. Claude updates this every session. On `continue`, read this file first.

**Started:** 2026-09-18 · **Target sample:** Day 5
**Repos:** `workflow-automation-backend`, `workflow-automation-frontend` (both private)
**Stack:** Django 5 + DRF + Channels + Celery + Redis | React (JSX) + Vite + Tailwind | PostgreSQL | Render

---

## CURRENT POSITION

**Day 2 — Trigger + Execution Engine** (in progress)
**Carryover from Day 1:** JWT auth endpoints + React login/register pages (not built), Render services (not created)

---

## RESUME PROTOCOL

When the user says `continue`:
1. Read **CURRENT POSITION** above
2. Read the unchecked boxes in the current day's section
3. Resume at the first unchecked item — do not re-ask scope questions already answered in **DECISIONS**
4. Update checkboxes + CURRENT POSITION before ending the session

---

## DECISIONS (locked — do not re-litigate)

| Topic | Decision |
|---|---|
| Trigger type (MVP) | Generic incoming webhook only, HMAC-verified |
| Flow complexity | Branching / parallel actions supported |
| Run status | Real-time via Django Channels WebSockets |
| Executors (MVP) | Slack + Trello only |
| Payments | Deferred — will be a new Executor class, no engine change |
| Auth | DRF SimpleJWT |
| Frontend | JSX (not TSX), Tailwind, PC-first responsive |
| Theme | Dark IDE aesthetic — base `#0a0b0d`, accent `#f5820c`, Inter + JetBrains Mono |
| Credentials | Plaintext JSONField for now; encryption in Day 4 security pass |

---

## DAY 1 — Foundation ⚠️ PARTIAL

- [x] Django project + DRF + PostgreSQL + `.env` config
- [x] Celery + Redis config written (`config/celery.py`, broker settings)
- [x] Channels ASGI config + `routing.py` placeholder
- [x] Models: `Workflow`, `WorkflowStep`, `WorkflowRun`, `StepRun`, `Credential` + migrations
- [x] Executor registry + `BaseExecutor` interface
- [x] React + Vite + Tailwind scaffold, dark theme tokens, app shell
- [ ] **JWT auth: register/login/refresh endpoints (backend)** ← carryover
- [ ] **React login/register pages + token storage + axios interceptor** ← carryover
- [ ] Render services created (web, worker, Redis, Postgres)

## DAY 2 — Trigger + Execution Engine

- [ ] Auth carryover from Day 1 (do first — everything else needs it)
- [ ] Workflow CRUD endpoints (list/create/retrieve/update/delete, owner-scoped)
- [ ] WorkflowStep bulk save endpoint (accepts full graph from builder)
- [ ] Webhook trigger endpoint: `POST /api/hooks/<workflow_id>/`, HMAC signature check → create `WorkflowRun` → enqueue Celery task
- [ ] Condition evaluator (safe, no raw `eval`)
- [ ] Slack executor
- [ ] Trello executor
- [ ] Celery task: walk step graph honoring branch true/false, write `StepRun` per step, retry w/ backoff
- [ ] Channels consumer per `WorkflowRun` (auth-protected)
- [ ] Celery task publishes step events to channel layer
- [ ] Manual end-to-end test: curl webhook → run executes → events emitted

## DAY 3 — Visual Builder (Frontend)

- [ ] React Flow canvas: trigger / condition / action node types
- [ ] Branching connections from condition nodes
- [ ] Node config panels (webhook secret display, Slack/Trello fields)
- [ ] Save graph → backend; load existing graph on open

## DAY 4 — Run History + Live Status + Security

- [ ] Workflow list/dashboard page
- [ ] Run history table (status, duration, timestamps)
- [ ] WebSocket live status on canvas — node highlights as steps complete
- [ ] Run detail view — per-step output/error
- [ ] Security pass: HTTPS-only, CORS locked, input validation on step config, webhook rate limiting

## DAY 5 — Deploy + Polish

- [ ] Deploy all services to Render, migrations, env vars
- [ ] End-to-end smoke test on production URL
- [ ] Responsive/mobile edge cases
- [ ] README: architecture diagram, setup, implemented vs deferred
- [ ] Demo video/GIF

---

## DEFERRED (post-sample)

- Payment executor (Stripe/Razorpay) — automated payments + file delivery
- More executors: Gmail, Typeform, Google Sheets
- Encrypted credential storage
- Multi-tenant orgs, billing, usage tiers
- Workflow versioning, full audit log
- Horizontal scaling: per-action-type worker pools

---

## SESSION LOG

| Date | Done |
|---|---|
| 2026-09-18 | Day 1 scaffold: backend config, models, executor base, React shell + theme |
