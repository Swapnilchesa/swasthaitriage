import json
import math
from pathlib import Path
from typing import List, Optional

from models import Facility, FacilityWithDistance

DATA_FILE = Path(__file__).parent / "data" / "facilities_assam.json"


def load_seed_facilities() -> List[dict]:
    with open(DATA_FILE) as f:
        return json.load(f)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 2)


def maps_url(f: Facility) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={f.latitude},{f.longitude}"


def resolve_location(
    facilities: List[Facility],
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    pincode: Optional[str] = None,
    city: Optional[str] = None,
    district: Optional[str] = None,
) -> Optional[dict]:
    """Best-effort caller coordinates from lat/lng, pincode, district or city text."""
    if latitude is not None and longitude is not None:
        return {"latitude": latitude, "longitude": longitude, "method": "gps", "matched": "caller GPS"}

    def centroid(items, method, matched):
        if not items:
            return None
        return {
            "latitude": round(sum(f.latitude for f in items) / len(items), 6),
            "longitude": round(sum(f.longitude for f in items) / len(items), 6),
            "method": method,
            "matched": matched,
        }

    if pincode:
        pin = pincode.strip()
        exact = [f for f in facilities if f.pincode == pin]
        if exact:
            return centroid(exact, "pincode", f"pincode {pin}")
        if len(pin) >= 3:
            near = [f for f in facilities if f.pincode and f.pincode[:3] == pin[:3]]
            if near:
                return centroid(near, "pincode_area", f"pincode area {pin[:3]}xxx")

    if district:
        d = district.strip().lower()
        hit = [f for f in facilities if f.district.lower() == d]
        if hit:
            return centroid(hit, "district", f"district {district}")

    if city:
        c = city.strip().lower()
        hit = [
            f
            for f in facilities
            if c and (c in f.name.lower() or c in f.address.lower() or c in f.district.lower())
        ]
        if hit:
            return centroid(hit, "city_text", f"city {city}")

    return None


PREFERENCE_MAP = {
    "ESIC Hospital (Emergency / Inpatient)": ["Hospital"],
    "ESIC Hospital (OPD)": ["Hospital"],
    "ESIS Dispensary": ["Dispensary"],
    "ESIS Diagnostic Centre": ["Diagnostic Centre"],
    "Nearest Government Hospital / 108 Ambulance": ["Hospital"],
}


def nearest_facilities(
    facilities: List[Facility],
    latitude: float,
    longitude: float,
    recommended_type: Optional[str] = None,
    limit: int = 5,
) -> List[FacilityWithDistance]:
    scored = []
    for f in facilities:
        item = FacilityWithDistance(
            **f.model_dump(exclude={"distance_km", "maps_url"}),
            distance_km=haversine_km(latitude, longitude, f.latitude, f.longitude),
            maps_url=maps_url(f),
        )
        scored.append(item)
    scored.sort(key=lambda x: x.distance_km)

    preferred_types = PREFERENCE_MAP.get(recommended_type or "", [])
    if not preferred_types:
        return scored[:limit]

    preferred = [
        x for x in scored if x.facility_type in preferred_types and x.distance_km <= 60
    ][:2]
    rest = [x for x in scored if x not in preferred]
    return (preferred + rest)[:limit]
