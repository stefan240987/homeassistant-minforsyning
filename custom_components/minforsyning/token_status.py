"""Read a KMD Bearer token's expiry without verifying its signature."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

STATUS_VALID = "Gyldig"
STATUS_EXPIRED = "Udløbet"
STATUS_INVALID = "Ugyldig"


def decode_jwt_payload(access_token) -> dict | None:
    """Return the JWT payload, or None when the token is not a readable JWT."""
    if not isinstance(access_token, str):
        return None
    token = access_token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) < 2 or not parts[1]:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding)
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def token_expiry(access_token, now=None) -> datetime | None:
    """UTC expiry from the exp claim, or None when it cannot be read."""
    payload = decode_jwt_payload(access_token)
    if payload is None or "exp" not in payload:
        return None
    try:
        exp = int(payload["exp"])
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(exp, timezone.utc)


def token_status(access_token, now=None) -> str:
    """Gyldig, Udløbet or Ugyldig. An unreadable token is Ugyldig, never an exception."""
    expires = token_expiry(access_token)
    if expires is None:
        return STATUS_INVALID
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if expires <= current.astimezone(timezone.utc):
        return STATUS_EXPIRED
    return STATUS_VALID
