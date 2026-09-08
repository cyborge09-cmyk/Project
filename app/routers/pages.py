"""Server-rendered pages. Interactions on top of them are handled by static/js."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import service
from ..config import get_settings
from ..deps import CurrentUser, Db, OptionalUser
from ..models import PIECES, STATUSES
from ..supabase import Database

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
templates.env.globals.update(PIECES=PIECES, STATUSES=STATUSES)


def render(request: Request, name: str, user: dict[str, Any] | None = None, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"user": user, **context})


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, user: OptionalUser):
    if not get_settings().configured:
        return render(request, "setup.html")
    if not user:
        return RedirectResponse("/login", status_code=303)

    db = Database(user["access_token"])
    boards = await db.select("boards", filters={"archived": "eq.false"}, order="created_at.asc")
    if len(boards) == 1:
        return RedirectResponse(f"/boards/{boards[0]['id']}", status_code=303)
    for board in boards:
        projects = await db.select("projects", columns="status", filters={"board_id": service.eq(board["id"])})
        board["project_count"] = len(projects)
        board["blocked_count"] = sum(1 for p in projects if p["status"] == "blocked")
    return render(request, "dashboard.html", user, boards=boards)


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request, user: OptionalUser, next: str = "/"):
    if not get_settings().configured:
        return render(request, "setup.html")
    if user:
        return RedirectResponse(next or "/", status_code=303)
    return render(request, "login.html", next_url=next or "/")


@router.get("/boards/{board_id}", response_class=HTMLResponse)
async def board_page(request: Request, board_id: str, db: Db, user: CurrentUser):
    board = await service.get_board(db, board_id)
    projects = await service.get_projects(db, board_id)
    people = await service.get_board_people(db, board_id)
    return render(
        request,
        "board.html",
        user,
        board=board,
        initial={"board": board, "projects": projects, "people": people},
        activity=await service.get_activity(db, board_id, 12),
    )


@router.get("/boards/{board_id}/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, board_id: str, db: Db, user: CurrentUser):
    board = await service.get_board(db, board_id)
    projects = await service.get_projects(db, board_id)
    people = await service.get_board_people(db, board_id)
    return render(
        request,
        "analytics.html",
        user,
        board=board,
        analytics=service.build_analytics(board, projects, people),
    )


@router.get("/my-work", response_class=HTMLResponse)
async def my_work_page(request: Request, db: Db, user: CurrentUser):
    from .me import my_workload  # local import keeps the route module import-light

    workload = await my_workload(db, user)
    return render(request, "my_work.html", user, workload=workload)
