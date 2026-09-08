"""Endpoints about the signed-in person."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..deps import CurrentUser, Db
from ..models import PIECES
from ..service import eq

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("")
async def read_me(db: Db, user: CurrentUser) -> dict[str, Any]:
    profile = await db.select_one("profiles", filters={"id": eq(user["user_id"])})
    return profile or {"id": user["user_id"], "email": user.get("email"), "full_name": user.get("name")}


@router.get("/workload")
async def my_workload(db: Db, user: CurrentUser) -> dict[str, Any]:
    """Every square this person's piece stands on (persona 3, section 4.1)."""
    rows = await db.select(
        "project_members",
        columns="id,piece,hours_allocated,active,projects(id,name,status,progress,deadline,board_id,boards(id,name))",
        filters={"user_id": eq(user["user_id"])},
    )
    assignments = []
    hours = 0.0
    for row in rows:
        project = row.get("projects") or {}
        if not project:
            continue
        board = project.get("boards") or {}
        hours += float(row.get("hours_allocated") or 0)
        assignments.append(
            {
                "assignment_id": row["id"],
                "piece": row["piece"],
                "glyph": PIECES.get(row["piece"], PIECES["pawn"])["glyph"],
                "role_label": PIECES.get(row["piece"], PIECES["pawn"])["role"],
                "hours_allocated": row.get("hours_allocated"),
                "active": row.get("active", True),
                "project_id": project["id"],
                "project_name": project["name"],
                "status": project["status"],
                "progress": project["progress"],
                "deadline": project.get("deadline"),
                "board_id": board.get("id") or project.get("board_id"),
                "board_name": board.get("name", "Board"),
            }
        )
    assignments.sort(key=lambda a: (a["status"] != "blocked", a["deadline"] or "9999-12-31"))
    live = [a for a in assignments if a["status"] in {"planning", "active", "blocked"}]
    return {
        "assignments": assignments,
        "totals": {
            "projects": len(live),
            "hours": round(hours, 1),
            "blocked": sum(1 for a in live if a["status"] == "blocked"),
            "overallocated": len(live) > 3 or hours > 40,
        },
    }
