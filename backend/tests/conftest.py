import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip()
BASE_URL = BASE_URL.rstrip("/")


def _read_env(key):
    v = os.environ.get(key)
    if v:
        return v
    for line in open("/app/backend/.env"):
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _parse_keys():
    raw = _read_env("API_KEYS")
    out = {}
    for item in raw.split(","):
        label, _, key = item.partition("=")
        out[label.strip()] = key.strip()
    return out


API_KEYS = _parse_keys()
CONSOLE_KEY = API_KEYS["console"]
WORKER_KEY = API_KEYS["worker-app"]
PARTNER_KEY = API_KEYS["partner-app"]


@pytest.fixture
def api_url():
    return f"{BASE_URL}/api"


@pytest.fixture
def console_key():
    return CONSOLE_KEY


@pytest.fixture
def worker_key():
    return WORKER_KEY


@pytest.fixture
def partner_key():
    return PARTNER_KEY


@pytest.fixture
def auth_session():
    s = requests.Session()
    s.headers.update({"X-API-Key": CONSOLE_KEY})
    return s
