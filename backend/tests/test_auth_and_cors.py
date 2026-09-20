"""Auth (X-API-Key), multi-key isolation, and CORS tests."""
import requests
from conftest import BASE_URL, CONSOLE_KEY, WORKER_KEY, PARTNER_KEY

API = f"{BASE_URL}/api"

PROTECTED_GET = [
    "/meta",
    "/facilities",
    "/facilities/nearest?pincode=785004",
    "/facilities/export",
    "/cases",
    "/cases/stats",
    "/cases/CASE-000000-XXXX",
]


class TestPublicRoot:
    def test_root_public_no_key(self):
        r = requests.get(f"{API}/", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "auth" in d
        assert d["status"] == "ok"


class TestMissingKey401:
    def test_all_protected_get_missing_key(self):
        for path in PROTECTED_GET:
            r = requests.get(f"{API}{path}", timeout=15)
            assert r.status_code == 401, f"{path} -> {r.status_code}"

    def test_triage_missing_key(self):
        r = requests.post(f"{API}/triage", json={"symptom_notes": "headache"}, timeout=15)
        assert r.status_code == 401

    def test_import_missing_key(self):
        files = {"file": ("x.csv", b"a,b\n1,2\n", "text/csv")}
        r = requests.post(f"{API}/facilities/import", files=files, timeout=15)
        assert r.status_code == 401


class TestBadKey401:
    def test_get_meta_bad_key(self):
        r = requests.get(f"{API}/meta", headers={"X-API-Key": "garbage_key_xxxxxx"}, timeout=15)
        assert r.status_code == 401

    def test_triage_bad_key(self):
        r = requests.post(
            f"{API}/triage",
            json={"symptom_notes": "headache for a day"},
            headers={"X-API-Key": "garbage"},
            timeout=15,
        )
        assert r.status_code == 401


class TestPerKeyWork:
    def test_console_key(self):
        r = requests.get(f"{API}/meta", headers={"X-API-Key": CONSOLE_KEY}, timeout=15)
        assert r.status_code == 200

    def test_worker_key(self):
        r = requests.get(f"{API}/meta", headers={"X-API-Key": WORKER_KEY}, timeout=15)
        assert r.status_code == 200

    def test_partner_key(self):
        r = requests.get(f"{API}/meta", headers={"X-API-Key": PARTNER_KEY}, timeout=15)
        assert r.status_code == 200

    def test_worker_facilities_list(self):
        r = requests.get(f"{API}/facilities", headers={"X-API-Key": WORKER_KEY}, timeout=15)
        assert r.status_code == 200
        assert len(r.json()) >= 36


class TestCORS:
    def test_allowed_origin_preflight(self):
        r = requests.options(
            f"{API}/meta",
            headers={
                "Origin": "https://symptom-intake-box.emergent.host",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
            timeout=15,
        )
        assert r.headers.get("access-control-allow-origin") == "https://symptom-intake-box.emergent.host"

    def test_disallowed_origin_preflight(self):
        r = requests.options(
            f"{API}/meta",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
            timeout=15,
        )
        assert r.headers.get("access-control-allow-origin") in (None, "")
