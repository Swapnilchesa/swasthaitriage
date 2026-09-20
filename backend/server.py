import csv
import io
import logging
import os
import random
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, HTTPException, Query, UploadFile
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

from geo import load_seed_facilities, nearest_facilities, resolve_location
from models import (
    CaseRecord,
    Facility,
    FacilityWithDistance,
    TriageRequest,
    TriageResponse,
)
from triage import MODEL_NAME, MODEL_PROVIDER, run_triage

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

client = AsyncIOMotorClient(os.environ["MONGO_URL"])
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Swasth Triage Sandbox API", version="1.0.0")
api_router = APIRouter(prefix="/api")


def new_case_ref() -> str:
    stamp = datetime.now(timezone.utc).strftime("%y%m%d")
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"CASE-{stamp}-{tail}"


async def all_facilities(active_only: bool = True) -> List[Facility]:
    q = {"active": True} if active_only else {}
    docs = await db.facilities.find(q).to_list(2000)
    return [Facility.from_mongo(d) for d in docs]


@app.on_event("startup")
async def seed_facilities():
    count = await db.facilities.count_documents({})
    if count == 0:
        rows = load_seed_facilities()
        await db.facilities.insert_many([Facility(**r).to_mongo() for r in rows])
        logger.info("Seeded %s ESIC/ESIS facilities for Assam", len(rows))
    await db.cases.create_index("case_ref")


@api_router.get("/")
async def root():
    return {
        "service": "Swasth Triage Sandbox",
        "status": "ok",
        "model": f"{MODEL_PROVIDER}/{MODEL_NAME}",
        "coverage": {"state": "Assam", "scheme": "ESIC / ESIS"},
    }


@api_router.get("/meta")
async def meta():
    facilities = await all_facilities()
    districts = sorted({f.district for f in facilities})
    pincodes = sorted({f.pincode for f in facilities if f.pincode})
    return {
        "districts": districts,
        "pincodes": pincodes,
        "facility_types": sorted({f.facility_type for f in facilities}),
        "facility_count": len(facilities),
        "urgency_levels": ["Emergency", "Urgent", "Routine", "Self-care"],
        "durations": [
            "Less than 2 hours",
            "Today",
            "1 day",
            "2-3 days",
            "4-7 days",
            "More than a week",
            "More than a month",
        ],
        "model": f"{MODEL_PROVIDER}/{MODEL_NAME}",
    }


# ---------------- Core black-box endpoint ----------------


@api_router.post("/triage", response_model=TriageResponse)
async def triage(req: TriageRequest):
    started = time.time()
    try:
        result = await run_triage(req)
    except Exception as exc:
        logger.exception("triage failed")
        raise HTTPException(status_code=502, detail=f"Triage engine error: {exc}")

    facilities = await all_facilities()
    loc = resolve_location(
        facilities,
        latitude=req.latitude,
        longitude=req.longitude,
        pincode=req.pincode,
        city=req.city,
        district=req.district,
    )
    nearest: List[FacilityWithDistance] = []
    if loc:
        nearest = nearest_facilities(
            facilities,
            loc["latitude"],
            loc["longitude"],
            recommended_type=result.recommended_facility_type,
        )

    latency = int((time.time() - started) * 1000)
    record = CaseRecord(
        case_ref=new_case_ref(),
        intake=req,
        triage=result,
        resolved_location=loc,
        nearest_facilities=nearest,
        model_used=f"{MODEL_PROVIDER}/{MODEL_NAME}",
        latency_ms=latency,
    )
    inserted = await db.cases.insert_one(record.to_mongo())

    return TriageResponse(
        case_ref=record.case_ref,
        case_id=str(inserted.inserted_id),
        triage=result,
        resolved_location=loc,
        nearest_facilities=nearest,
        model_used=record.model_used,
        latency_ms=latency,
    )


# ---------------- Cases ----------------


@api_router.get("/cases", response_model=List[CaseRecord])
async def list_cases(
    urgency: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, le=200),
):
    query: dict = {}
    if urgency and urgency != "all":
        query["triage.urgency_level"] = urgency
    if q:
        query["$or"] = [
            {"case_ref": {"$regex": q, "$options": "i"}},
            {"intake.caller_name": {"$regex": q, "$options": "i"}},
            {"intake.phone": {"$regex": q, "$options": "i"}},
            {"intake.symptom_notes": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.cases.find(query).sort("created_at", -1).to_list(limit)
    return [CaseRecord.from_mongo(d) for d in docs]


@api_router.get("/cases/stats")
async def case_stats():
    pipeline = [{"$group": {"_id": "$triage.urgency_level", "count": {"$sum": 1}}}]
    rows = await db.cases.aggregate(pipeline).to_list(20)
    counts = {r["_id"]: r["count"] for r in rows}
    total = sum(counts.values())
    return {"total": total, "by_urgency": counts}


@api_router.get("/cases/{case_ref}", response_model=CaseRecord)
async def get_case(case_ref: str):
    doc = await db.cases.find_one({"case_ref": case_ref})
    if not doc:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseRecord.from_mongo(doc)


# ---------------- Facilities ----------------


@api_router.get("/facilities", response_model=List[Facility])
async def list_facilities(
    q: Optional[str] = None,
    district: Optional[str] = None,
    facility_type: Optional[str] = None,
):
    query: dict = {"active": True}
    if district and district != "all":
        query["district"] = district
    if facility_type and facility_type != "all":
        query["facility_type"] = facility_type
    if q:
        query["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"address": {"$regex": q, "$options": "i"}},
            {"pincode": {"$regex": q, "$options": "i"}},
            {"district": {"$regex": q, "$options": "i"}},
        ]
    docs = await db.facilities.find(query).sort("name", 1).to_list(2000)
    return [Facility.from_mongo(d) for d in docs]


@api_router.get("/facilities/nearest", response_model=List[FacilityWithDistance])
async def facilities_nearest(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    pincode: Optional[str] = None,
    city: Optional[str] = None,
    district: Optional[str] = None,
    facility_type: Optional[str] = None,
    limit: int = Query(5, le=25),
):
    facilities = await all_facilities()
    loc = resolve_location(
        facilities,
        latitude=latitude,
        longitude=longitude,
        pincode=pincode,
        city=city,
        district=district,
    )
    if not loc:
        raise HTTPException(status_code=422, detail="Could not resolve a location from the inputs given")
    pool = [f for f in facilities if not facility_type or f.facility_type == facility_type]
    return nearest_facilities(pool, loc["latitude"], loc["longitude"], limit=limit)


CSV_COLUMNS = [
    "name",
    "facility_type",
    "scheme",
    "address",
    "district",
    "block",
    "pincode",
    "state",
    "latitude",
    "longitude",
    "site_code",
    "phone",
]


@api_router.post("/facilities/import")
async def import_facilities(file: UploadFile = File(...), replace: bool = False):
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="Empty CSV")
    missing = {"name", "address", "district", "latitude", "longitude"} - set(reader.fieldnames)
    if missing:
        raise HTTPException(status_code=400, detail=f"CSV missing required columns: {sorted(missing)}")

    rows, errors = [], []
    for i, row in enumerate(reader, start=2):
        try:
            payload = {k: (row.get(k) or "").strip() or None for k in CSV_COLUMNS}
            payload["latitude"] = float(row["latitude"])
            payload["longitude"] = float(row["longitude"])
            payload["facility_type"] = payload["facility_type"] or "Dispensary"
            payload["scheme"] = payload["scheme"] or "ESIC"
            payload["state"] = payload["state"] or "Assam"
            rows.append(Facility(**{k: v for k, v in payload.items() if v is not None}).to_mongo())
        except Exception as exc:
            errors.append(f"row {i}: {exc}")

    if not rows:
        raise HTTPException(status_code=400, detail={"message": "No valid rows", "errors": errors[:10]})

    if replace:
        await db.facilities.delete_many({})
    await db.facilities.insert_many(rows)
    return {"imported": len(rows), "replaced": replace, "errors": errors[:10], "total_facilities": await db.facilities.count_documents({})}


@api_router.get("/facilities/export")
async def export_facilities():
    facilities = await all_facilities(active_only=False)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for f in facilities:
        writer.writerow({k: getattr(f, k, "") for k in CSV_COLUMNS})
    return {"filename": "facilities.csv", "csv": buf.getvalue(), "count": len(facilities)}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
