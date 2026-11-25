# Swasth Triage Sandbox — Functional & Business Specification

| Item | Value |
|---|---|
| Document version | 1.1 (June 2026) |
| Status | **v1 built and running in preview.** **v2 (severity-based triage) proposed, waiting for client sign-off** |
| Scope | Assam · ESIC / ESIS facilities only |
| Owner | Swasth programme team |

> **Clinical disclaimer.** This system triages **urgency** and suggests **where to go**. It does not diagnose, prescribe or give medical advice. The clinical framework in Section 7 is a **draft for clinical review**. Clinicians and the client must sign it off before anyone relies on it.

---

## 1. Business Context

### 1.1 Problem
Workers and labourers in India call a health helpline to describe a health problem. Call-centre executives are not clinicians. They need help to:
1. Decide how urgent the problem is.
2. Send the caller to the right ESIC/ESIS facility that is closest to them.
3. Record every call the same way so it can be audited.

### 1.2 Objectives
| # | Objective | How we measure it |
|---|---|---|
| O1 | Triage every call consistently and in a way that can be explained | 100% of cases store the reasoning and red flags |
| O2 | Get emergencies to 108 or the emergency department straight away | `call_108` flagged on every danger-sign case; no under-triage in the test cases |
| O3 | Refer callers to the nearest suitable ESIC/ESIS facility | Distance and a directions link included with every case that has a known location |
| O4 | Make the triage engine reusable as a black-box API | Other applications can call the REST API with their own API key |
| O5 | Support the languages callers actually use | English, Hindi (Devanagari) and Hinglish notes are accepted |

### 1.3 Stakeholders and Users
| Role | Need |
|---|---|
| Call-centre executive | A fast, guided screen and a clear, ready-to-read instruction for the caller |
| Supervisor / programme team | Case logs, urgency or severity mix, and an audit trail |
| Client clinical lead | Control over the clinical framework that drives the decisions |
| Partner app developers | A stable, documented REST API with keys and rate limits |
| Caller (worker or labourer) | The right facility at the right time, explained in their own language |

### 1.4 In Scope / Out of Scope
**In scope:** urgency or severity triage, referral pathway, nearest-facility routing in Assam (36 ESIC/ESIS sites in 18 districts), case logging, facility directory with CSV import and export, API with an interactive playground.

**Out of scope:** diagnosis, medicines or dosages, appointment booking, payments, user logins (the console uses an API key), states other than Assam, and non-ESIC facilities. The only exception to the last item is the Severe fallback, which may point to a government hospital (Section 7).

---

## 2. Solution Overview

```
Operator Console (React, light theme)  ─┐
Partner / worker apps                  ─┼─► FastAPI  /api/*  ──► Claude Sonnet 4.6 (triage)
                                        │      │
                                        │      └──► MongoDB: facilities, cases, rate_limits
```

- **Frontend tabs:** Live intake & triage · Case logs · Facility directory · API & playground
- **AI model:** Claude Sonnet 4.6, accessed through the Emergent LLM key
- **Data:** Facilities are loaded from the client's Excel file (34 ESIS dispensaries and 2 ESIC hospitals)

---

## 3. Functional Requirements — v1 (As Built)

### FR-1 Intake
- Fields: caller name, phone, age, sex, symptom notes (required, at least 3 characters), duration, city, district, pincode, optional latitude/longitude, agent ID.
- Notes can be written in English, Hindi or Hinglish. The system detects the language and stores it.
- Four sample calls are included for demos.
- *v1 also has a manual "reported severity" slider from 1 to 10. **v2 removes it** (see Section 6).*

### FR-2 AI Triage (v1)
Output fields: `urgency_level` (Emergency / Urgent / Routine / Self-care), `urgency_score`, `confidence`, `summary_en`, `summary_hi`, `reasoning`, `red_flags[]`, `recommended_facility_type`, `recommended_action`, `call_108`, `detected_language`, `followup_questions[]`.
- Escalation modifiers: age under 5 or over 65, pregnancy, occupational exposure (for example pesticides), and reported severity of 8 to 10.
- Guard against over-escalation: vague notes on their own must not be marked as an emergency.

### FR-3 Facility Routing
- The caller's location is worked out in this order: GPS, then exact pincode, then pincode area, then district, then free-text city.
- The nearest facility is found by straight-line (haversine) distance. Within 60 km, the recommended facility type is preferred.
- Each result includes the distance in km and a Google Maps directions link.

### FR-4 Case Log
- Every triage is saved with a reference in the format `SW-…`, plus the intake, result, resolved location, facilities, model used and response time.
- Logs can be filtered by urgency and searched, and each row expands to show the full detail. A stats endpoint is also available.

### FR-5 Facility Directory
- Search and filter by district and facility type. Facilities can be bulk-loaded by CSV import and downloaded by CSV export.

### FR-6 Developer API and Playground
- An editable JSON request, a live response and a copyable cURL command for each endpoint.

### FR-7 Security
- Every endpoint except `GET /api/` requires an `X-API-Key` header. Keys are stored as `label=key` pairs in the backend `API_KEYS` setting. To revoke an app's access, delete its pair and redeploy.
- Rate limits per key: 60 requests/min for triage and import, 300 requests/min for reads. Over the limit returns HTTP 429 with a `Retry-After` header.
- CORS only allows origins listed in `CORS_ORIGINS`. Allowed methods are GET, POST and OPTIONS. Allowed headers are `X-API-Key` and `Content-Type`.

---

## 4. API Contract — v1

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/` | Public liveness check |
| GET | `/api/meta` | Districts, pincodes, facility types, duration options |
| POST | `/api/triage` | Triage plus nearest facilities in one call (the black box) |
| GET | `/api/cases`, `/api/cases/stats`, `/api/cases/{case_ref}` | Case log |
| GET | `/api/facilities` | Directory search |
| GET | `/api/facilities/nearest` | Routing only (lat/lng, pincode, city or district) |
| POST | `/api/facilities/import` | Bulk CSV import |
| GET | `/api/facilities/export` | CSV export |

Every triage response includes a disclaimer, `model_used` and `latency_ms`.

---

## 5. Non-Functional Requirements
| Area | Requirement |
|---|---|
| UX | **Light mode only**, chosen by the client. Usable at call-centre pace, with a target of under 10 seconds per AI step |
| Explainability | Every decision stores its reasoning and red flags. In v2 it also stores the clinical principles applied |
| Privacy | Phone number and health notes are personal data. A retention policy is still to be defined (open item) |
| Availability | If the AI call fails, the console shows an error. A fallback that is safe for call centres is in the backlog |
| Branding | Swasth title, favicon and Open Graph / Twitter social cards. Production picks these up after a republish |

---

## 6. v2 Change Request — Severity-Based Triage (Proposed)

### 6.1 Client Requirement (summary)
1. Classify every case into one of three severity levels: **Mild / Moderate / Severe**.
2. Base the decision on **defined clinical principles**.
3. **Remove** the executive's manual severity field. The AI decides severity.
4. Follow this flow: **Chief Complaint → Probing Questions → AI Assessment → Severity Classification → Referral Pathway**.

### 6.2 New Functional Requirements
| ID | Requirement |
|---|---|
| FR-v2-1 | Remove `severity_reported` from the UI, sample calls, API models, prompt and documentation |
| FR-v2-2 | **Start step:** the executive enters the chief complaint and basic demographics. The AI returns 3 to 5 targeted probing questions in the caller's language, with an English gloss |
| FR-v2-3 | **Emergency short-circuit:** if the chief complaint already shows a clear danger sign, return **Severe** with `call_108` straight away and skip the questions |
| FR-v2-4 | **Complete step:** the executive records the caller's answers. Any question can be marked "caller doesn't know" |
| FR-v2-5 | The AI returns a severity, the principles applied, red flags, confidence, unanswered questions, the referral pathway and `call_108` |
| FR-v2-6 | Map the severity to a referral pathway (Section 7.3) and attach the nearest matching facilities |
| FR-v2-7 | Save the full set of questions and answers, plus the audit trail, on the case. Show them in Case logs |
| FR-v2-8 | Publish the approved framework, with a version stamp, at `GET /api/meta/framework`. Store the framework version on every case |
| FR-v2-9 | Show Mild, Moderate and Severe as three distinct colours on the console and in the logs, with filters and stats by severity |

### 6.3 Proposed API Additions
| Method | Path | Request | Response |
|---|---|---|---|
| POST | `/api/triage/start` | chief complaint, age, sex, location, language hint | `session_id`, `questions[]` (each with `id`, `text`, `text_en`), or a direct Severe result |
| POST | `/api/triage/complete` | `session_id`, `answers[]` | severity result + `nearest_facilities` + `case_ref` |
| GET | `/api/meta/framework` | — | Framework text, version and effective date |
| POST | `/api/triage` | (existing) | Kept as a single-call option for partner apps that send a full narrative. This is a decision for the client |

**Severity result contract (v2):**
```json
{
  "severity": "Mild | Moderate | Severe",
  "confidence": "high | medium | low",
  "principles_applied": ["P1 Danger signs: none", "P3 Trajectory: worsening over 2 days"],
  "red_flags": [],
  "probing_summary": "…",
  "unanswered_questions": [],
  "referral_pathway": { "facility_type": "ESIC Hospital OPD", "timeframe": "Same day" },
  "call_108": false,
  "caller_instruction_en": "…",
  "caller_instruction_hi": "…",
  "framework_version": "v1-draft"
}
```

---

## 7. Clinical Severity Framework (v1 — Draft for Clinical Review)

### 7.1 Principles (evaluated in order)
| # | Principle | Rule |
|---|---|---|
| P1 | **Danger signs first (ABCD)** | Airway or breathing compromise, shock or major bleeding, altered consciousness or seizure, major trauma, obstetric emergency, poisoning or snakebite → **Severe** |
| P2 | **Symptom-specific red flags** | For example: chest pain with sweating, sudden weakness on one side, a stiff neck with fever, blood in vomit or stool, severe dehydration → **Severe** (or Moderate if the client decides so) |
| P3 | **Trajectory and duration** | Rapidly worsening symptoms → move up one level. Stable symptoms with a long duration point to Moderate or Mild |
| P4 | **Functional impact** | Unable to work, eat or walk → at least **Moderate** |
| P5 | **Vulnerability modifiers** | Age under 5 or over 65 (cutoff still to be confirmed: 60 or 65), pregnancy, chronic illness, occupational exposure → move up one level |
| P6 | **Uncertainty rule** | If key answers are missing and danger signs cannot be ruled out → **Moderate with low confidence**, and never Mild |
| P7 | **Prohibited outputs** | No diagnosis, no medicine names or dosages, no reassurance that goes against a red flag |

### 7.2 Severity Definitions
- **Severe:** a possible threat to life or limb, which needs care immediately.
- **Moderate:** needs a clinician's assessment the same day or within 24 hours.
- **Mild:** can be managed at a dispensary visit at the caller's convenience, with clear advice to come back sooner if things get worse.

### 7.3 Referral Pathway (proposed)
| Severity | Pathway | Timeframe | `call_108` |
|---|---|---|---|
| Severe | 108 ambulance, or the emergency department of the nearest ESIC hospital. If that is too far, the nearest government hospital | Immediately | Yes |
| Moderate | ESIC Hospital OPD. If the hospital is more than about 1 hour away, the ESIS dispensary first for onward referral | Same day / within 24 h | No |
| Mild | ESIS dispensary, with advice to monitor and come back if not better in 48 to 72 hours or if it gets worse | Within 1–3 days | No |

---

## 8. Decisions Needed from the Client Before Building v2
1. Does Mild / Moderate / Severe **replace** the four urgency levels, or is it **mapped onto** them?
2. Is there an ESIC, MoHFW or internal SOP to use word for word instead of Section 7?
3. Is the Moderate pathway approved: hospital OPD, or the dispensary first?
4. Is a single symptom-specific red flag always Severe?
5. Is the age cutoff over 60 or over 65?
6. Should the pathway move up a level when the caller has trouble reaching a facility (for example distance or no transport)?
7. Should probing questions be adaptive (generated by AI), fixed per complaint category, or a mix of both?
8. Can executives skip questions? Is the uncertainty rule (P6) accepted?
9. Should the single-call `/api/triage` stay available for partner apps?

---

## 9. Acceptance Criteria (v2)
- There is no manual severity input anywhere in the UI or the API.
- Every case moves through the steps complaint → questions → assessment → severity → pathway, and stores its audit trail and framework version.
- The test set (English, Hindi and Hinglish) passes:
  - **Severe:** chest pain with sweating, unconscious, pesticide ingestion, snakebite, heavy bleeding in pregnancy.
  - **Moderate:** high fever for 3 days in a child, a vomiting adult who cannot eat.
  - **Mild:** a mild cold for 2 days, a minor muscle strain.
  - **Under-triage:** none of the Severe cases may be classified as Mild or Moderate.
  - **Over-escalation:** vague, low-risk notes must not be classified as Severe.
- Danger signs in the chief complaint skip the questions and return Severe within a single AI call.
- API-key enforcement, rate limits and CORS behave the same way as in v1.

---

## 10. Roadmap
| Priority | Item |
|---|---|
| P0 | v2 severity-based triage, after the framework is signed off |
| P1 | Store API keys in the database with an admin screen, so revoking a key does not need a redeploy |
| P1 | A fallback for when the AI is unavailable (a rule-based danger-sign checklist) |
| P1 | A data retention and PII policy for case records |
| P1 | Facility phone numbers and OPD timings. Expansion beyond Assam and ESIC |
| P2 | Send the facility details to the caller by SMS or WhatsApp |
| P2 | Supervisor dashboard and a case status workflow |
| P2 | Voice intake (speech-to-text) |

## 11. Operational Notes
- Changes in preview go live on the production domain only after **Republish**. Preview and production have separate settings.
- After republishing, social link previews may need a re-scrape on WhatsApp, LinkedIn and X before the Swasth branding appears.
