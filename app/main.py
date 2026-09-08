"""Chess Board Project Management Tool -- FastAPI application."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import session as session_mod
from .config import get_settings
from .routers import auth, boards, me, pages, projects
from .supabase import SupabaseError, aclose

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await aclose()


app = FastAPI(
    lifespan=lifespan,
    title="Chess Board PM",
    description="A project management board where every square is a project and every chess piece is a person.",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth.router)
app.include_router(boards.router)
app.include_router(projects.router)
app.include_router(me.router)
app.include_router(pages.router)


@app.middleware("http")
async def persist_session(request: Request, call_next):
    """Write back a session cookie when a token was refreshed mid-request."""
    response = await call_next(request)
    if getattr(request.state, "drop_session", False):
        session_mod.clear_cookie(response)
    elif getattr(request.state, "new_session", None):
        session_mod.apply_cookie(response, request.state.new_session)
    return response


def _is_page_request(request: Request) -> bool:
    """Page routes redirect to the sign-in screen; /api routes get JSON errors."""
    return request.method == "GET" and not request.url.path.startswith("/api/")


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 401 and _is_page_request(request):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(SupabaseError)
async def supabase_error(request: Request, exc: SupabaseError):
    if exc.status in (401, 403) and _is_page_request(request):
        return RedirectResponse("/login", status_code=303)
    # PostgREST speaks in constraint names; map the ones users can actually trip.
    message = exc.message
    if "project_members_one_royal_idx" in str(exc.detail):
        message = "That project already has a king or queen. Only one of each is allowed."
    elif "projects_board_id_pos_x_pos_y_key" in str(exc.detail):
        message = "That square is already taken."
    status_code = exc.status if 400 <= exc.status < 600 else 502
    return JSONResponse({"error": message}, status_code=status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", ())[1:]) or "request"
    return JSONResponse({"error": f"{field}: {first.get('msg', 'is invalid')}"}, status_code=422)


@app.get("/api/health", tags=["meta"])
async def health() -> dict[str, object]:
    return {"ok": True, "supabase_configured": get_settings().configured}
