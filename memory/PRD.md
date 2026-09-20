# Swasth Triage Sandbox — PRD

## Original problem statement
Build a small sandbox (black-box API + demo UI) for a call centre serving workers and labourers in
India. Callers describe a health issue; the executive types it into a UI. An LLM triages urgency
(no medical advice). A facility database routes the caller to the nearest hospital/dispensary based
on their location. Multiple applications will eventually call the API directly.

## User choices
- LLM: **Claude Sonnet 4.6** (via Emergent LLM key / emergentintegrations)
- Output: urgency level (Emergency / Urgent / Routine / Self-care) + reasoning + red flags + recommended facility type
- Facility data: user-supplied Excel — **ESIC / ESIS Assam only** (34 dispensaries + 2 hospitals = 36)
- Location input: city + district + pincode, optional lat/long
- Language: English, Hindi (Devanagari) and Hinglish notes supported
- Theme: **light mode** (user explicitly dislikes dark mode)

## Architecture
- Backend: FastAPI (`/app/backend`)
  - `server.py` — routes; seeds facilities on startup if collection is empty
  - `triage.py` — Claude Sonnet 4.6 prompt with urgency + escalation rules, JSON extraction & validation
  - `geo.py` — location resolution (gps > pincode > pincode area > district > city text), haversine nearest, facility-type preference within 60 km
  - `models.py` — `BaseDocument` / `PyObjectId`, serialises `_id` as `id`
  - `data/facilities_assam.json` — seed data parsed from the user's Excel
- Frontend: React + Tailwind (`/app/frontend/src`), 4 tabs: Live intake & triage, Case logs, Facility directory, API & playground
- DB: MongoDB — collections `facilities`, `cases`

## API (black box)
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/triage` | Triage a complaint + return nearest facilities (the black box) |
| GET | `/api/facilities/nearest` | Routing only (lat/lng, pincode, city or district) |
| GET | `/api/facilities` | Search the directory |
| POST | `/api/facilities/import` | Bulk CSV import |
| GET | `/api/cases`, `/api/cases/stats`, `/api/cases/{case_ref}` | Case log |
| GET | `/api/meta` | Districts, pincodes, facility types, duration options |

## Implemented (2026-06)
### Security hardening + branding (latest)
- `X-API-Key` auth on every endpoint except the public `GET /api/` liveness check. Keys are static
  `label=key` pairs in the `API_KEYS` env var (console / worker-app / partner-app) — delete a pair to
  revoke that app. Constant-time comparison, only the label is logged, never the key.
- Per-key fixed-window rate limiting via an atomic Mongo counter with a TTL index:
  60/min on `POST /api/triage` and `POST /api/facilities/import`, 300/min on read endpoints.
  Returns 429 + `Retry-After`. Verified isolated per key.
- CORS restricted to `CORS_ORIGINS` (custom domain + emergent.host + preview + localhost),
  `allow_credentials=False`, `allow_headers=["X-API-Key","Content-Type"]`.
- Console authenticates with its own key from `REACT_APP_API_KEY` — no login screen.
- Link-preview / SEO metadata replaced (title, description, OG + Twitter tags, custom favicon,
  apple-touch-icon and 1200x630 `og-image.jpg`); all Emergent branding removed from `index.html`.
- Verified: 30/30 backend tests + full UI regression (testing agent iteration 2).
- Triage engine with Emergency / Urgent / Routine / Self-care, urgency score, confidence, red flags,
  recommended facility type, caller action, `call_108` flag, follow-up questions, English + Hindi summaries
- Escalation rules: age <5 / >65, severity 8-10, pregnancy, occupational exposure; guard against over-escalation on vague notes
- Nearest-facility routing with distance in km + Google Maps directions link
- Case log with urgency filter, search and row expansion; stats endpoint
- Facility directory with search/district/type filters and CSV import/export
- API playground with editable JSON body, live response and cURL copy
- Light-mode UI, 4 sample Assam calls (Hinglish / Hindi / low-acuity / pesticide exposure)
- Verified: 19/19 backend tests + full UI flow (testing agent iteration 1)

## Backlog
- P1: rotate API keys to a DB-backed table with an admin UI (currently static env list — revoke needs a redeploy)
- P1: expand coverage beyond Assam / ESIC; add facility phone numbers and OPD timings
- P1: real SMS/WhatsApp dispatch of the facility address to the caller (currently copy-to-clipboard)
- P2: supervisor dashboard (urgency mix over time, agent throughput), case status workflow (dispatched / closed)
- P2: audio intake (Whisper) so the executive can record instead of typing
