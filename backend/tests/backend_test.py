"""Backend integration tests for Swasth Triage Sandbox API (with X-API-Key auth)."""
import os
import pytest
import requests

from conftest import BASE_URL, CONSOLE_KEY

API = f"{BASE_URL}/api"
TRIAGE_TIMEOUT = 120
HEADERS = {"X-API-Key": CONSOLE_KEY}


def _get(path, **kw):
    kw.setdefault("timeout", 30)
    h = kw.pop("headers", {})
    h.setdefault("X-API-Key", CONSOLE_KEY)
    return requests.get(f"{API}{path}", headers=h, **kw)


def _post(path, **kw):
    kw.setdefault("timeout", 30)
    h = kw.pop("headers", {})
    h.setdefault("X-API-Key", CONSOLE_KEY)
    return requests.post(f"{API}{path}", headers=h, **kw)


class TestMeta:
    def test_meta_returns_expected_counts(self):
        r = _get("/meta")
        assert r.status_code == 200
        d = r.json()
        assert d["facility_count"] == 36
        assert len(d["districts"]) == 18
        assert "Emergency" in d["urgency_levels"]


class TestFacilities:
    def test_list_facilities_no_underscore_id(self):
        r = _get("/facilities")
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) >= 36
        assert "id" in arr[0]
        assert "_id" not in arr[0]

    def test_filter_by_district_jorhat(self):
        r = _get("/facilities", params={"district": "Jorhat"})
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) > 0
        for f in arr:
            assert f["district"] == "Jorhat"

    def test_filter_by_facility_type(self):
        r = _get("/facilities", params={"facility_type": "Hospital"})
        assert r.status_code == 200
        for f in r.json():
            assert f["facility_type"] == "Hospital"

    def test_search_q_filter(self):
        r = _get("/facilities", params={"q": "guwahati"})
        assert r.status_code == 200
        assert len(r.json()) > 0

    def test_nearest_by_pincode_exact(self):
        r = _get("/facilities/nearest", params={"pincode": "785004"})
        assert r.status_code == 200
        arr = r.json()
        assert arr[0]["distance_km"] == 0.0
        for i in range(1, len(arr)):
            assert arr[i]["distance_km"] >= arr[i - 1]["distance_km"]

    def test_nearest_unresolvable_returns_422(self):
        r = _get("/facilities/nearest", params={"pincode": "999999", "city": "", "district": ""})
        assert r.status_code == 422

    def test_export_works(self):
        r = _get("/facilities/export")
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 36


class TestFacilityImport:
    def test_import_valid_csv_and_cleanup(self):
        csv_data = (
            "name,facility_type,scheme,address,district,block,pincode,state,latitude,longitude\n"
            "TEST_Facility_Import_1,Dispensary,ESIC,TEST Address 1,Kamrup Metropolitan,,781001,Assam,26.14,91.73\n"
            "TEST_Facility_Import_2,Hospital,ESIC,TEST Address 2,Jorhat,,785001,Assam,26.75,94.20\n"
        )
        before = _get("/meta").json()["facility_count"]
        files = {"file": ("test.csv", csv_data.encode("utf-8"), "text/csv")}
        r = requests.post(f"{API}/facilities/import", files=files, params={"replace": "false"}, headers=HEADERS, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["imported"] == 2

        from pymongo import MongoClient
        mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
        mongo_url = mongo_url.strip().strip('"')
        for line in open("/app/backend/.env"):
            if line.startswith("MONGO_URL="):
                mongo_url = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("DB_NAME="):
                dbname = line.split("=", 1)[1].strip().strip('"').strip("'")
        mc = MongoClient(mongo_url)
        res = mc[dbname].facilities.delete_many({"name": {"$regex": "^TEST_Facility_Import_"}})
        assert res.deleted_count == 2
        assert _get("/meta").json()["facility_count"] == before

    def test_import_missing_columns_returns_400(self):
        csv_data = "name,facility_type\nX,Hospital\n"
        files = {"file": ("bad.csv", csv_data.encode("utf-8"), "text/csv")}
        r = requests.post(f"{API}/facilities/import", files=files, headers=HEADERS, timeout=30)
        assert r.status_code == 400


class TestTriage:
    def test_validation_short_symptom_with_valid_key(self):
        r = _post("/triage", json={"symptom_notes": "hi"}, timeout=15)
        assert r.status_code == 422  # not 401

    def test_triage_chest_pain_hinglish_emergency(self):
        payload = {
            "caller_name": "TEST_Caller_Chest",
            "age": 48,
            "sex": "male",
            "symptom_notes": "seene mein bahut dard ho raha hai, pasina aa raha hai, left arm mein bhi dard, saans lene mein takleef",
            "duration": "Less than 2 hours",
            "severity_reported": 9,
            "pincode": "781022",
        }
        r = _post("/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        t = d["triage"]
        assert t["urgency_level"] == "Emergency"
        assert t["call_108"] is True
        assert len(t["red_flags"]) > 0
        nf = d["nearest_facilities"]
        assert len(nf) > 0
        for i in range(1, len(nf)):
            assert nf[i]["distance_km"] >= nf[i - 1]["distance_km"]

    def test_triage_trivial_not_escalated(self):
        payload = {
            "age": 30,
            "symptom_notes": "mild headache for the last one hour, no other symptoms",
            "duration": "Less than 2 hours",
            "severity_reported": 2,
        }
        r = _post("/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        t = r.json()["triage"]
        assert t["urgency_level"] in ["Self-care", "Routine"]


class TestCases:
    def test_list_cases(self):
        r = _get("/cases")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_case_stats(self):
        r = _get("/cases/stats")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == sum(d["by_urgency"].values())

    def test_get_unknown_case_404(self):
        r = _get("/cases/CASE-000000-XXXX")
        assert r.status_code == 404

    def test_get_existing_case_by_ref(self):
        arr = _get("/cases").json()
        if not arr:
            pytest.skip("no cases yet")
        ref = arr[0]["case_ref"]
        r = _get(f"/cases/{ref}")
        assert r.status_code == 200
        assert r.json()["case_ref"] == ref
