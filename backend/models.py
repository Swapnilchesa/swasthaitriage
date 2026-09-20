from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional

from bson import ObjectId
from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field

URGENCY_LEVELS = ["Emergency", "Urgent", "Routine", "Self-care"]


def _to_str_id(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_to_str_id)]


class BaseDocument(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: Optional[PyObjectId] = Field(
        default=None,
        validation_alias=AliasChoices("_id", "id"),
        serialization_alias="id",
    )

    def to_mongo(self) -> dict:
        doc = self.model_dump(by_alias=True, exclude_none=True)
        doc.pop("id", None)
        doc.pop("_id", None)
        return doc

    @classmethod
    def from_mongo(cls, doc: Optional[dict]):
        if not doc:
            return None
        return cls.model_validate(doc)


class Facility(BaseDocument):
    name: str
    facility_type: str
    scheme: str = "ESIC"
    address: str
    district: str
    block: Optional[str] = None
    pincode: Optional[str] = None
    state: str = "Assam"
    latitude: float
    longitude: float
    site_code: Optional[str] = None
    phone: Optional[str] = None
    active: bool = True


class FacilityWithDistance(Facility):
    distance_km: Optional[float] = None
    maps_url: Optional[str] = None


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    caller_name: Optional[str] = None
    phone: Optional[str] = None
    age: Optional[int] = None
    sex: Optional[str] = None
    symptom_notes: str = Field(min_length=3)
    duration: Optional[str] = None
    severity_reported: Optional[int] = None
    city: Optional[str] = None
    district: Optional[str] = None
    pincode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    agent_id: Optional[str] = None
    source_app: Optional[str] = "console"


class TriageResult(BaseModel):
    urgency_level: str
    urgency_score: int
    confidence: str
    summary_en: str
    summary_hi: str
    reasoning: str
    red_flags: List[str] = []
    recommended_facility_type: str
    recommended_action: str
    call_108: bool = False
    detected_language: Optional[str] = None
    followup_questions: List[str] = []


class CaseRecord(BaseDocument):
    case_ref: str
    intake: TriageRequest
    triage: TriageResult
    resolved_location: Optional[dict] = None
    nearest_facilities: List[FacilityWithDistance] = []
    model_used: str
    latency_ms: int
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TriageResponse(BaseModel):
    case_ref: str
    case_id: Optional[str] = None
    triage: TriageResult
    resolved_location: Optional[dict] = None
    nearest_facilities: List[FacilityWithDistance] = []
    disclaimer: str = (
        "This system performs urgency triage and facility routing only. "
        "It does not provide a medical diagnosis or treatment advice."
    )
    model_used: str
    latency_ms: int
