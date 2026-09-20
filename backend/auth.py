import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pymongo import ReturnDocument

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

logger = logging.getLogger(__name__)

WINDOW = int(os.environ.get("RATE_WINDOW_SECONDS", "60"))
TRIAGE_LIMIT = int(os.environ.get("RATE_LIMIT_TRIAGE", "60"))
READ_LIMIT = int(os.environ.get("RATE_LIMIT_READ", "300"))


def _parse_keys(raw: str) -> dict:
    """API_KEYS format: label=key,label=key — one key per calling app."""
    keys = {}
    for item in raw.split(","):
        label, sep, key = item.partition("=")
        label, key = label.strip(), key.strip()
        if not sep or not label or not key:
            raise RuntimeError("API_KEYS must be formatted as label=key,label=key")
        digest = hashlib.sha256(key.encode()).hexdigest()
        if digest in keys:
            raise RuntimeError("API_KEYS contains a duplicate key")
        keys[digest] = (label, key)
    return keys


KEYS_BY_DIGEST = _parse_keys(os.environ["API_KEYS"])
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def rate_limited(limit: int):
    """Auth + per-key fixed-window rate limit. Counters live in Mongo so they hold across workers."""

    async def dependency(
        request: Request, api_key: str | None = Security(api_key_header)
    ) -> str:
        if not api_key:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header"
            )
        digest = hashlib.sha256(api_key.encode()).hexdigest()
        record = KEYS_BY_DIGEST.get(digest)
        if not record or not hmac.compare_digest(record[1], api_key):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

        label = record[0]
        db = request.app.state.db
        now = datetime.now(timezone.utc)
        window = int(now.timestamp()) // WINDOW
        counter = await db.rate_limits.find_one_and_update(
            {"_id": f"{digest}:{limit}:{window}"},
            {
                "$inc": {"count": 1},
                "$setOnInsert": {
                    "label": label,
                    "expires_at": now + timedelta(seconds=WINDOW + 60),
                },
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if counter["count"] > limit:
            logger.warning("rate limit hit for client '%s' on %s", label, request.url.path)
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Rate limit exceeded: {limit} requests per {WINDOW}s for this key",
                headers={"Retry-After": str(WINDOW - int(now.timestamp()) % WINDOW)},
            )

        request.state.client_label = label
        return label

    return dependency


write_guard = Depends(rate_limited(TRIAGE_LIMIT))
read_guard = Depends(rate_limited(READ_LIMIT))
