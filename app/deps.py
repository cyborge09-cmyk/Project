"""Shared FastAPI dependencies."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from . import session as session_mod
from .supabase import Auth, Database, SupabaseError


async def load_session(request: Request) -> dict[str, Any] | None:
    """Return the caller's session, transparently refreshing an expiring token."""
    cached = getattr(request.state, "session", "unset")
    if cached != "unset":
        return cached

    data = session_mod.loads(request.cookies.get(session_mod.COOKIE_NAME))
    if data and session_mod.is_expiring(data):
        try:
            tokens = await Auth().refresh(data["refresh_token"])
            refreshed = session_mod.build(tokens)
            refreshed.setdefault("name", data.get("name", ""))
            data = refreshed
            request.state.new_session = data
        except SupabaseError:
            data = None
            request.state.drop_session = True

    request.state.session = data
    return data


async def optional_user(request: Request) -> dict[str, Any] | None:
    return await load_session(request)


async def current_user(
    user: Annotated[dict[str, Any] | None, Depends(optional_user)],
) -> dict[str, Any]:
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")
    return user


async def get_db(user: Annotated[dict[str, Any], Depends(current_user)]) -> Database:
    """A PostgREST client carrying the caller's JWT, so RLS applies to every query."""
    return Database(user["access_token"])


CurrentUser = Annotated[dict[str, Any], Depends(current_user)]
OptionalUser = Annotated[dict[str, Any] | None, Depends(optional_user)]
Db = Annotated[Database, Depends(get_db)]
