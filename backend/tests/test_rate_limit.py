"""Rate limit + per-key isolation test. Assumes RATE_LIMIT_READ has been temporarily lowered (e.g. to 3)."""
import time
import requests
from conftest import BASE_URL, CONSOLE_KEY, WORKER_KEY, PARTNER_KEY

API = f"{BASE_URL}/api"
LIMIT = 3  # must match RATE_LIMIT_READ set in .env for this test


def _hammer(key, n):
    codes = []
    for _ in range(n):
        r = requests.get(f"{API}/meta", headers={"X-API-Key": key}, timeout=15)
        codes.append(r.status_code)
    return codes, r


class TestRateLimit:
    def test_console_hits_429_then_worker_still_200(self):
        # Wait for a fresh window boundary to avoid partial-window flakiness
        time.sleep(1)

        # Fire (LIMIT + 3) requests with console key -> last few should be 429
        codes, last = _hammer(CONSOLE_KEY, LIMIT + 3)
        assert codes.count(200) <= LIMIT, f"expected <= {LIMIT} 200s, got {codes}"
        assert 429 in codes, f"expected a 429 in {codes}"
        assert last.status_code == 429
        assert "Retry-After" in last.headers
        assert int(last.headers["Retry-After"]) >= 0

        # Worker key must NOT be limited (isolation) - single request should still be 200
        r = requests.get(f"{API}/meta", headers={"X-API-Key": WORKER_KEY}, timeout=15)
        assert r.status_code == 200, f"worker got {r.status_code}, isolation broken"

        # Partner key also independent
        r2 = requests.get(f"{API}/meta", headers={"X-API-Key": PARTNER_KEY}, timeout=15)
        assert r2.status_code == 200
