"""Signed-cookie sessions holding the Supabase tokens."""
from __future__ import annotations

import base64
import binascii
import json
import time
from typing import Any

from itsdangerous import BadSignature, URLSafeSerializer

from .config import get_settings

COOKIE_NAME = "cb_session"
# Refresh a little before expiry so a request never runs with a dead token.
REFRESH_MARGIN_SECONDS = 60


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().session_secret, salt="chessboard-session")


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Read a JWT payload without verifying it.

    The signature is verified by Supabase on every request; here the claims are only
    used to know when to refresh and to label the UI, and the token itself arrives
    inside a cookie we signed.
    """
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError, binascii.Error):
        return {}


def build(tokens: dict[str, Any]) -> dict[str, Any]:
    """Turn a GoTrue token response into the session payload."""
    access_token = tokens.get("access_token", "")
    claims = decode_jwt_claims(access_token)
    user = tokens.get("user") or {}
    metadata = user.get("user_metadata") or {}
    return {
        "access_token": access_token,
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": int(tokens.get("expires_at") or claims.get("exp") or 0),
        "user_id": user.get("id") or claims.get("sub", ""),
        "email": user.get("email") or claims.get("email", ""),
        "name": metadata.get("full_name") or (user.get("email") or claims.get("email", "")).split("@")[0],
    }


def dumps(session: dict[str, Any]) -> str:
    return _serializer().dumps(session)


def loads(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = _serializer().loads(raw)
    except BadSignature:
        return None
    return value if isinstance(value, dict) and value.get("access_token") else None


def is_expiring(session: dict[str, Any]) -> bool:
    expires_at = int(session.get("expires_at") or 0)
    return expires_at > 0 and expires_at - REFRESH_MARGIN_SECONDS <= time.time()


def apply_cookie(response: Any, session: dict[str, Any]) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        dumps(session),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Any) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
