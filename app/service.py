"""Queries and derived data shared by the API routes and the page routes."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from .models import PIECES, STATUSES
from .supabase import Database, SupabaseError

PROJECT_COLUMNS = (
    "id,board_id,name,description,status,progress,start_date,deadline,pos_x,pos_y,"
    "tags,blockers,velocity,cycle_time,created_at,updated_at,"
    "project_members(id,user_id,piece,hours_allocated,active,joined_at,"
    "profiles(id,full_name,email,avatar_url,job_title,department))"
)

ACTIVE_STATUSES = {"planning", "active", "blocked"}


def eq(value: str) -> str:
    """PostgREST equality filter value."""
    return f"eq.{value}"


async def get_board(db: Database, board_id: str) -> dict[str, Any]:
    board = await db.select_one("boards", filters={"id": eq(board_id)})
    if not board:
        # RLS hides boards the caller cannot see, which is indistinguishable from absent.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Board not found")
    return board


async def get_projects(db: Database, board_id: str) -> list[dict[str, Any]]:
    projects = await db.select(
        "projects",
        columns=PROJECT_COLUMNS,
        filters={"board_id": eq(board_id)},
        order="pos_y.asc,pos_x.asc",
    )
    for project in projects:
        project["members"] = _normalise_members(project.pop("project_members", []))
    return projects


async def get_project(db: Database, project_id: str) -> dict[str, Any]:
    project = await db.select_one("projects", columns=PROJECT_COLUMNS, filters={"id": eq(project_id)})
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    project["members"] = _normalise_members(project.pop("project_members", []))
    return project


def _normalise_members(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    members = []
    for row in rows:
        profile = row.pop("profiles", None) or {}
        piece = row.get("piece", "pawn")
        members.append(
            {
                **row,
                "name": profile.get("full_name") or profile.get("email", "Unknown"),
                "email": profile.get("email", ""),
                "avatar_url": profile.get("avatar_url"),
                "job_title": profile.get("job_title"),
                "department": profile.get("department"),
                "glyph": PIECES.get(piece, PIECES["pawn"])["glyph"],
                "role_label": PIECES.get(piece, PIECES["pawn"])["role"],
            }
        )
    members.sort(key=lambda m: (list(PIECES).index(m.get("piece", "pawn")), m["name"].lower()))
    return members


async def get_board_people(db: Database, board_id: str) -> list[dict[str, Any]]:
    rows = await db.select(
        "board_members",
        columns="role,added_at,profiles(id,full_name,email,avatar_url,job_title,department)",
        filters={"board_id": eq(board_id)},
    )
    people = []
    for row in rows:
        profile = row.get("profiles") or {}
        if not profile:
            continue
        people.append(
            {
                "id": profile["id"],
                "name": profile.get("full_name") or profile.get("email", "Unknown"),
                "email": profile.get("email", ""),
                "avatar_url": profile.get("avatar_url"),
                "job_title": profile.get("job_title"),
                "department": profile.get("department"),
                "board_role": row.get("role", "member"),
            }
        )
    people.sort(key=lambda p: p["name"].lower())
    return people


async def log_activity(
    db: Database,
    *,
    board_id: str,
    actor_id: str,
    action: str,
    project_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Best-effort audit trail; never fail the user's request over it."""
    try:
        await db.insert(
            "activity",
            {
                "board_id": board_id,
                "project_id": project_id,
                "actor_id": actor_id,
                "action": action,
                "detail": detail or {},
            },
            returning=False,
        )
    except SupabaseError:
        pass


async def get_activity(db: Database, board_id: str, limit: int = 30) -> list[dict[str, Any]]:
    rows = await db.select(
        "activity",
        columns="id,action,detail,created_at,project_id,profiles(full_name,email)",
        filters={"board_id": eq(board_id)},
        order="created_at.desc",
        limit=limit,
    )
    for row in rows:
        profile = row.pop("profiles", None) or {}
        row["actor"] = profile.get("full_name") or profile.get("email", "Someone")
    return rows


async def next_free_square(db: Database, board: dict[str, Any]) -> tuple[int, int] | None:
    """First empty square, reading left to right and top to bottom."""
    taken = {
        (p["pos_x"], p["pos_y"])
        for p in await db.select("projects", columns="pos_x,pos_y", filters={"board_id": eq(board["id"])})
    }
    for y in range(board["rows"]):
        for x in range(board["cols"]):
            if (x, y) not in taken:
                return x, y
    return None


# ------------------------------------------------------------- analytics ----
def _days_until(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return (date.fromisoformat(value) - datetime.now(timezone.utc).date()).days
    except ValueError:
        return None


def build_analytics(board: dict[str, Any], projects: list[dict[str, Any]], people: list[dict[str, Any]]) -> dict[str, Any]:
    """Capacity, throughput and risk figures for the analytics dashboard."""
    status_counts = Counter(p["status"] for p in projects)
    by_status = [
        {
            "status": key,
            "label": meta["label"],
            "color": meta["color"],
            "count": status_counts.get(key, 0),
        }
        for key, meta in STATUSES.items()
    ]

    workload: dict[str, dict[str, Any]] = {
        person["id"]: {**person, "projects": [], "hours": 0.0, "pieces": Counter()} for person in people
    }
    for project in projects:
        if project["status"] not in ACTIVE_STATUSES:
            continue
        for member in project["members"]:
            if not member.get("active", True):
                continue
            entry = workload.setdefault(
                member["user_id"],
                {
                    "id": member["user_id"],
                    "name": member["name"],
                    "email": member.get("email", ""),
                    "job_title": member.get("job_title"),
                    "department": member.get("department"),
                    "projects": [],
                    "hours": 0.0,
                    "pieces": Counter(),
                },
            )
            entry["projects"].append(
                {"id": project["id"], "name": project["name"], "status": project["status"], "piece": member["piece"]}
            )
            entry["hours"] += float(member.get("hours_allocated") or 0)
            entry["pieces"][member["piece"]] += 1

    allocation = []
    for entry in workload.values():
        count = len(entry["projects"])
        allocation.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "email": entry.get("email", ""),
                "job_title": entry.get("job_title"),
                "department": entry.get("department"),
                "project_count": count,
                "hours": round(entry["hours"], 1),
                "projects": entry["projects"],
                "top_piece": (entry["pieces"].most_common(1)[0][0] if entry["pieces"] else "pawn"),
                # >3 concurrent projects or >40h allocated is the overallocation signal.
                "overallocated": count > 3 or entry["hours"] > 40,
            }
        )
    allocation.sort(key=lambda a: (-a["project_count"], -a["hours"], a["name"].lower()))

    tracked = [p for p in projects if p["status"] in ACTIVE_STATUSES]
    avg_progress = round(sum(p["progress"] for p in tracked) / len(tracked), 1) if tracked else 0.0
    completed = status_counts.get("completed", 0)
    completion_rate = round(100 * completed / len(projects), 1) if projects else 0.0

    at_risk = []
    for project in projects:
        if project["status"] in {"completed", "on_hold"}:
            continue
        days = _days_until(project.get("deadline"))
        if project["status"] == "blocked" or (days is not None and days <= 7):
            at_risk.append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "status": project["status"],
                    "progress": project["progress"],
                    "days_left": days,
                    "reason": "Blocked" if project["status"] == "blocked" else "Deadline within a week",
                }
            )
    at_risk.sort(key=lambda p: (p["days_left"] is None, p["days_left"] if p["days_left"] is not None else 0))

    squares = board["rows"] * board["cols"]
    return {
        "totals": {
            "projects": len(projects),
            "squares": squares,
            "board_fill": round(100 * len(projects) / squares, 1) if squares else 0.0,
            "people": len(allocation),
            "unstaffed": sum(1 for p in tracked if not p["members"]),
            "avg_progress": avg_progress,
            "completion_rate": completion_rate,
            "overallocated": sum(1 for a in allocation if a["overallocated"]),
        },
        "by_status": by_status,
        "allocation": allocation,
        "at_risk": at_risk,
        "by_department": [
            {"department": dept or "Unassigned", "people": count}
            for dept, count in Counter(a.get("department") for a in allocation).most_common()
        ],
    }
