"""Thin async clients for Supabase PostgREST and GoTrue.

Talking to the REST endpoints directly (instead of the supabase-py SDK) keeps the
serverless bundle small and lets every query run with the *caller's* JWT, so the
row level security policies in supabase/schema.sql are what actually enforce access.
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

import httpx

from .config import get_settings

_clients: dict[Any, httpx.AsyncClient] = {}


class SupabaseError(Exception):
    """A non-2xx response from Supabase."""

    def __init__(self, status: int, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


class NotConfigured(SupabaseError):
    def __init__(self) -> None:
        super().__init__(503, "Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY.")


def _client() -> httpx.AsyncClient:
    """One pooled client per event loop (serverless invocations reuse a loop)."""
    loop = asyncio.get_event_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        _clients[loop] = client
    return client


async def aclose() -> None:
    for client in list(_clients.values()):
        if not client.is_closed:
            await client.aclose()
    _clients.clear()


def _explain(response: httpx.Response) -> SupabaseError:
    try:
        payload = response.json()
    except ValueError:
        return SupabaseError(response.status_code, response.text.strip() or "Supabase request failed")
    if isinstance(payload, dict):
        message = (
            payload.get("message")
            or payload.get("error_description")
            or payload.get("msg")
            or payload.get("error")
            or payload.get("hint")
            or "Supabase request failed"
        )
        return SupabaseError(response.status_code, str(message), payload)
    return SupabaseError(response.status_code, "Supabase request failed", payload)


async def _request(url: str, method: str, **kwargs: Any) -> httpx.Response:
    try:
        response = await _client().request(method, url, **kwargs)
    except httpx.HTTPError as exc:  # network/DNS/timeout
        raise SupabaseError(502, f"Could not reach Supabase: {exc}") from exc
    if response.status_code >= 400:
        raise _explain(response)
    return response


# --------------------------------------------------------------- PostgREST ---
class Database:
    """PostgREST wrapper scoped to a single user's access token."""

    def __init__(self, token: str | None = None) -> None:
        settings = get_settings()
        if not settings.configured:
            raise NotConfigured()
        self._settings = settings
        self._token = token or settings.supabase_anon_key

    def _headers(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._settings.supabase_anon_key,
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _url(self, table: str) -> str:
        return f"{self._settings.rest_url}/{table}"

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Mapping[str, str] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"select": columns}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = str(limit)
        response = await _request(self._url(table), "GET", params=params, headers=self._headers())
        return response.json()

    async def select_one(self, table: str, **kwargs: Any) -> dict[str, Any] | None:
        rows = await self.select(table, limit=1, **kwargs)
        return rows[0] if rows else None

    async def insert(
        self,
        table: str,
        data: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        upsert_on: str | None = None,
        returning: bool = True,
    ) -> list[dict[str, Any]]:
        prefer = ["return=representation" if returning else "return=minimal"]
        if upsert_on:
            prefer.append("resolution=merge-duplicates")
        headers = self._headers({"Prefer": ",".join(prefer)})
        params = {"on_conflict": upsert_on} if upsert_on else None
        response = await _request(self._url(table), "POST", json=data, params=params, headers=headers)
        return response.json() if returning and response.content else []

    async def update(
        self,
        table: str,
        filters: Mapping[str, str],
        data: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        headers = self._headers({"Prefer": "return=representation"})
        response = await _request(self._url(table), "PATCH", params=dict(filters), json=data, headers=headers)
        return response.json() if response.content else []

    async def delete(self, table: str, filters: Mapping[str, str]) -> None:
        headers = self._headers({"Prefer": "return=minimal"})
        await _request(self._url(table), "DELETE", params=dict(filters), headers=headers)


# ------------------------------------------------------------------ GoTrue ---
class Auth:
    """Email/password auth against Supabase GoTrue."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.configured:
            raise NotConfigured()
        self._settings = settings

    def _headers(self, token: str | None = None) -> dict[str, str]:
        return {
            "apikey": self._settings.supabase_anon_key,
            "Authorization": f"Bearer {token or self._settings.supabase_anon_key}",
            "Content-Type": "application/json",
        }

    async def sign_up(self, email: str, password: str, full_name: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"email": email, "password": password}
        if full_name:
            payload["data"] = {"full_name": full_name}
        response = await _request(
            f"{self._settings.auth_url}/signup", "POST", json=payload, headers=self._headers()
        )
        return response.json()

    async def sign_in(self, email: str, password: str) -> dict[str, Any]:
        response = await _request(
            f"{self._settings.auth_url}/token",
            "POST",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            headers=self._headers(),
        )
        return response.json()

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        response = await _request(
            f"{self._settings.auth_url}/token",
            "POST",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
            headers=self._headers(),
        )
        return response.json()

    async def get_user(self, access_token: str) -> dict[str, Any]:
        response = await _request(
            f"{self._settings.auth_url}/user", "GET", headers=self._headers(access_token)
        )
        return response.json()

    async def sign_out(self, access_token: str) -> None:
        try:
            await _request(f"{self._settings.auth_url}/logout", "POST", headers=self._headers(access_token))
        except SupabaseError:
            # An already-expired token cannot be revoked; the cookie is cleared regardless.
            pass
