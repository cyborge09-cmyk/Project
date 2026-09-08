"""Sign up, sign in, sign out."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import session as session_mod
from ..deps import OptionalUser
from ..models import SignInIn, SignUpIn
from ..supabase import Auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _session_response(tokens: dict, payload: dict) -> JSONResponse:
    response = JSONResponse(payload)
    session_mod.apply_cookie(response, session_mod.build(tokens))
    return response


@router.post("/signup")
async def sign_up(body: SignUpIn) -> JSONResponse:
    result = await Auth().sign_up(body.email, body.password, body.full_name)
    if not result.get("access_token"):
        # The project requires email confirmation before a session is issued.
        return JSONResponse(
            {"ok": True, "confirmation_required": True, "message": "Check your inbox to confirm your email, then sign in."}
        )
    return _session_response(result, {"ok": True, "confirmation_required": False})


@router.post("/login")
async def sign_in(body: SignInIn) -> JSONResponse:
    tokens = await Auth().sign_in(body.email, body.password)
    return _session_response(tokens, {"ok": True})


@router.post("/logout")
async def sign_out(request: Request, user: OptionalUser) -> JSONResponse:
    if user:
        await Auth().sign_out(user["access_token"])
    request.state.session = None
    request.state.new_session = None  # do not let a mid-request refresh re-set the cookie
    response = JSONResponse({"ok": True})
    session_mod.clear_cookie(response)
    return response
