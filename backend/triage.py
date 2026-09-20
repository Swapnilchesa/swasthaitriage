import json
import logging
import os
import re
import uuid

from emergentintegrations.llm.chat import LlmChat, UserMessage

from models import TriageRequest, TriageResult

logger = logging.getLogger(__name__)

MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a non-diagnostic medical TRIAGE ENGINE for a call centre that serves \
workers and labourers in Assam, India. A call centre executive types what the caller reported. \
Notes may be in English, Hindi (Devanagari) or Hinglish (roman-script Hindi). You must understand all of them.

YOUR ONLY JOB: decide how URGENT the complaint is and what TYPE of facility they should go to.
YOU MUST NOT: give a diagnosis, name a disease as a conclusion, prescribe medicines, or give dosages.

Urgency levels (pick exactly one):
- "Emergency": possible life/limb threat. Needs immediate care / ambulance 108. e.g. chest pain with sweating or radiating arm pain, breathlessness at rest, unconsciousness, seizure, stroke signs (face droop, one-sided weakness, slurred speech), heavy uncontrolled bleeding, major trauma/crush/fall from height, poisoning or chemical/pesticide exposure, electric shock, severe burns, snake bite, pregnancy bleeding, stiff neck with high fever, inability to pass urine, suicidal intent.
- "Urgent": should be seen within a few hours to same day. e.g. high fever >3 days or with rigors, persistent vomiting/dehydration, moderate injury needing stitches, severe pain (7+/10), infected wound with pus/spreading redness, fever in a diabetic/elderly person, eye injury, animal bite needing vaccination.
- "Routine": can be seen at a dispensary/OPD within 1-3 days. e.g. mild fever a day or two, cough/cold, body ache, mild skin rash, chronic joint pain, medicine refill, routine check.
- "Self-care": simple home measures and monitoring are reasonable. e.g. very mild short-duration headache, minor superficial cut already stopped bleeding, mild acidity.

Escalation rules that OVERRIDE the base level:
- Age under 5 or over 65: escalate one level if there is fever, vomiting, breathlessness or injury.
- Reported severity 8-10 out of 10: never below "Urgent".
- Pregnancy mentioned with any abdominal pain, bleeding or fever: "Emergency".
- Occupational exposure (pesticide, chemical, dust, machinery, construction fall, heat stroke): escalate one level.
- If the notes are too vague to judge, do not guess high; use "Routine" and put concrete clarifying questions in followup_questions.

recommended_facility_type must be one of:
"ESIC Hospital (Emergency / Inpatient)", "ESIC Hospital (OPD)", "ESIS Dispensary", "ESIS Diagnostic Centre", "Nearest Government Hospital / 108 Ambulance"

Return ONLY a JSON object, no markdown fences, no commentary, with exactly these keys:
{
  "urgency_level": "Emergency|Urgent|Routine|Self-care",
  "urgency_score": 1-10 integer,
  "confidence": "high|medium|low",
  "summary_en": "one-line neutral restatement of the complaint in English",
  "summary_hi": "same one-line summary in Hindi (Devanagari)",
  "reasoning": "2-4 sentences explaining the urgency decision, referencing duration, severity, age and risk factors. No diagnosis.",
  "red_flags": ["short specific red-flag symptoms actually present; empty array if none"],
  "recommended_facility_type": "one of the allowed values",
  "recommended_action": "what the executive should tell the caller to do next, 1-2 sentences, action only, no treatment advice",
  "call_108": true only if an ambulance should be called now,
  "detected_language": "English|Hindi|Hinglish|Mixed",
  "followup_questions": ["up to 3 questions the executive should ask to sharpen the triage"]
}"""

ALLOWED_FACILITY_TYPES = {
    "ESIC Hospital (Emergency / Inpatient)",
    "ESIC Hospital (OPD)",
    "ESIS Dispensary",
    "ESIS Diagnostic Centre",
    "Nearest Government Hospital / 108 Ambulance",
}


def _build_user_prompt(req: TriageRequest) -> str:
    lines = [
        f"Caller age: {req.age if req.age is not None else 'not stated'}",
        f"Caller sex: {req.sex or 'not stated'}",
        f"Duration of complaint: {req.duration or 'not stated'}",
        f"Severity reported by caller (1-10): {req.severity_reported if req.severity_reported is not None else 'not stated'}",
        f"Location: {', '.join(filter(None, [req.city, req.district, req.pincode]))or 'not stated'}",
        "",
        "Executive's notes of the complaint:",
        req.symptom_notes.strip(),
    ]
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output: {text[:300]}")
    return json.loads(text[start : end + 1])


async def run_triage(req: TriageRequest) -> TriageResult:
    api_key = os.environ["EMERGENT_LLM_KEY"]
    chat = LlmChat(
        api_key=api_key,
        session_id=f"triage-{uuid.uuid4()}",
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, MODEL_NAME)

    raw = await chat.send_message(UserMessage(text=_build_user_prompt(req)))
    data = _extract_json(raw if isinstance(raw, str) else str(raw))

    level = data.get("urgency_level", "Routine")
    if level not in {"Emergency", "Urgent", "Routine", "Self-care"}:
        level = "Routine"
    data["urgency_level"] = level

    if data.get("recommended_facility_type") not in ALLOWED_FACILITY_TYPES:
        data["recommended_facility_type"] = (
            "Nearest Government Hospital / 108 Ambulance"
            if level == "Emergency"
            else "ESIS Dispensary"
        )

    try:
        data["urgency_score"] = max(1, min(10, int(data.get("urgency_score", 5))))
    except (TypeError, ValueError):
        data["urgency_score"] = 5

    for key in ("red_flags", "followup_questions"):
        if not isinstance(data.get(key), list):
            data[key] = []
        data[key] = [str(x) for x in data[key]][:5]

    return TriageResult(**data)
