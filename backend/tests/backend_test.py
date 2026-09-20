"""Backend integration tests for Swasth Triage Sandbox API."""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    # Try to read from frontend .env
    envp = "/app/frontend/.env"
    if os.path.exists(envp):
        for line in open(envp):
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip()
BASE_URL = BASE_URL.rstrip("/")

API = f"{BASE_URL}/api"

TRIAGE_TIMEOUT = 90


# ---------------- Meta ----------------
class TestMeta:
    def test_meta_returns_expected_counts(self):
        r = requests.get(f"{API}/meta", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["facility_count"] == 36, f"expected 36 facilities, got {d['facility_count']}"
        assert len(d["districts"]) == 18, f"expected 18 districts, got {len(d['districts'])}"
        assert "Emergency" in d["urgency_levels"]
        assert len(d["facility_types"]) > 0
        assert len(d["pincodes"]) > 0


# ---------------- Facilities filtering ----------------
class TestFacilities:
    def test_list_facilities_no_underscore_id(self):
        r = requests.get(f"{API}/facilities", timeout=30)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) >= 36
        assert "id" in arr[0]
        assert "_id" not in arr[0]

    def test_filter_by_district_jorhat(self):
        r = requests.get(f"{API}/facilities", params={"district": "Jorhat"}, timeout=30)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) > 0
        for f in arr:
            assert f["district"] == "Jorhat"

    def test_filter_by_facility_type(self):
        r = requests.get(f"{API}/facilities", params={"facility_type": "Hospital"}, timeout=30)
        assert r.status_code == 200
        arr = r.json()
        for f in arr:
            assert f["facility_type"] == "Hospital"

    def test_search_q_filter(self):
        r = requests.get(f"{API}/facilities", params={"q": "guwahati"}, timeout=30)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) > 0

    def test_nearest_by_pincode_exact(self):
        r = requests.get(f"{API}/facilities/nearest", params={"pincode": "785004"}, timeout=30)
        assert r.status_code == 200
        arr = r.json()
        assert len(arr) > 0
        # First result should be distance 0.0 for exact pincode match
        assert arr[0]["distance_km"] == 0.0
        # ordered ascending
        for i in range(1, len(arr)):
            assert arr[i]["distance_km"] >= arr[i - 1]["distance_km"]
        assert "maps_url" in arr[0]

    def test_nearest_unresolvable_returns_422(self):
        r = requests.get(
            f"{API}/facilities/nearest",
            params={"pincode": "999999", "city": "", "district": ""},
            timeout=30,
        )
        assert r.status_code == 422


# ---------------- CSV Import ----------------
class TestFacilityImport:
    def test_import_valid_csv_and_cleanup(self):
        csv_data = (
            "name,facility_type,scheme,address,district,block,pincode,state,latitude,longitude\n"
            "TEST_Facility_Import_1,Dispensary,ESIC,TEST Address 1,Kamrup Metropolitan,,781001,Assam,26.14,91.73\n"
            "TEST_Facility_Import_2,Hospital,ESIC,TEST Address 2,Jorhat,,785001,Assam,26.75,94.20\n"
        )
        # get baseline count
        meta_before = requests.get(f"{API}/meta", timeout=30).json()
        before_count = meta_before["facility_count"]

        files = {"file": ("test.csv", csv_data.encode("utf-8"), "text/csv")}
        r = requests.post(f"{API}/facilities/import", files=files, params={"replace": "false"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["imported"] == 2
        assert d["total_facilities"] == before_count + 2

        # cleanup via Mongo directly
        try:
            from pymongo import MongoClient
            mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017").strip().strip('"').strip("'")
            mc = MongoClient(mongo_url)
            dbname = os.environ.get("DB_NAME")
            if not dbname:
                for line in open("/app/backend/.env"):
                    if line.startswith("DB_NAME="):
                        dbname = line.split("=", 1)[1].strip()
            dbname = (dbname or "").strip().strip('"').strip("'")
            res = mc[dbname].facilities.delete_many({"name": {"$regex": "^TEST_Facility_Import_"}})
            assert res.deleted_count == 2
        except Exception as e:
            pytest.fail(f"Cleanup failed: {e}")

        # verify count back to baseline
        meta_after = requests.get(f"{API}/meta", timeout=30).json()
        assert meta_after["facility_count"] == before_count

    def test_import_missing_columns_returns_400(self):
        csv_data = "name,facility_type\nX,Hospital\n"
        files = {"file": ("bad.csv", csv_data.encode("utf-8"), "text/csv")}
        r = requests.post(f"{API}/facilities/import", files=files, timeout=30)
        assert r.status_code == 400


# ---------------- Triage endpoint ----------------
class TestTriage:
    def test_validation_short_symptom(self):
        r = requests.post(f"{API}/triage", json={"symptom_notes": "hi"}, timeout=15)
        assert r.status_code == 422

    def test_triage_no_location_returns_empty_nearest(self):
        payload = {
            "symptom_notes": "mild cough for a day, throat feels dry",
            "duration": "1 day",
            "severity_reported": 3,
        }
        r = requests.post(f"{API}/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["nearest_facilities"] == []
        assert d["resolved_location"] is None
        assert d["triage"]["urgency_level"] in ["Emergency", "Urgent", "Routine", "Self-care"]

    def test_triage_district_only_resolves_location(self):
        payload = {
            "symptom_notes": "persistent headache for 2 days, feeling weak",
            "duration": "2-3 days",
            "severity_reported": 4,
            "district": "Jorhat",
        }
        r = requests.post(f"{API}/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["resolved_location"] is not None
        assert len(d["nearest_facilities"]) > 0

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
        r = requests.post(f"{API}/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        t = d["triage"]
        assert t["urgency_level"] == "Emergency", f"expected Emergency got {t['urgency_level']}"
        assert t["call_108"] is True
        assert len(t["red_flags"]) > 0
        assert t["summary_en"] and t["summary_hi"]
        # nearest sorted ascending
        nf = d["nearest_facilities"]
        assert len(nf) > 0
        for i in range(1, len(nf)):
            assert nf[i]["distance_km"] >= nf[i - 1]["distance_km"]
        assert "maps_url" in nf[0] and nf[0]["maps_url"].startswith("http")

    def test_triage_hindi_fever_urgent_or_routine(self):
        payload = {
            "age": 35,
            "symptom_notes": "पिछले 4 दिनों से बुखार है, बदन दर्द भी है",
            "duration": "4-7 days",
            "severity_reported": 6,
            "pincode": "786125",
            "district": "Tinsukia",
        }
        r = requests.post(f"{API}/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        d = r.json()
        t = d["triage"]
        assert t["urgency_level"] in ["Urgent", "Routine"], f"got {t['urgency_level']}"
        # detected language should indicate Hindi (or Mixed)
        assert t["detected_language"] in ["Hindi", "Mixed"], f"got {t['detected_language']}"
        assert len(d["nearest_facilities"]) > 0

    def test_triage_trivial_not_escalated(self):
        payload = {
            "age": 30,
            "symptom_notes": "mild headache for the last one hour, no other symptoms",
            "duration": "Less than 2 hours",
            "severity_reported": 2,
        }
        r = requests.post(f"{API}/triage", json=payload, timeout=TRIAGE_TIMEOUT)
        assert r.status_code == 200, r.text
        t = r.json()["triage"]
        assert t["urgency_level"] in ["Self-care", "Routine"], f"got {t['urgency_level']}"
        assert len(t["red_flags"]) <= 1


# ---------------- Cases ----------------
class TestCases:
    def test_list_cases_and_filter(self):
        r = requests.get(f"{API}/cases", timeout=30)
        assert r.status_code == 200
        arr = r.json()
        assert isinstance(arr, list)
        if len(arr) >= 2:
            # newest first
            assert arr[0]["created_at"] >= arr[1]["created_at"]

        # urgency filter
        r2 = requests.get(f"{API}/cases", params={"urgency": "Emergency"}, timeout=30)
        assert r2.status_code == 200
        for c in r2.json():
            assert c["triage"]["urgency_level"] == "Emergency"

    def test_case_stats(self):
        r = requests.get(f"{API}/cases/stats", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "total" in d and "by_urgency" in d
        assert d["total"] == sum(d["by_urgency"].values())

    def test_get_unknown_case_404(self):
        r = requests.get(f"{API}/cases/CASE-000000-XXXX", timeout=30)
        assert r.status_code == 404

    def test_get_existing_case_by_ref(self):
        arr = requests.get(f"{API}/cases", timeout=30).json()
        if not arr:
            pytest.skip("no cases yet")
        ref = arr[0]["case_ref"]
        r = requests.get(f"{API}/cases/{ref}", timeout=30)
        assert r.status_code == 200
        assert r.json()["case_ref"] == ref
