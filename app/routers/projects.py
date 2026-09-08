"""Project CRUD, team assignment (the chess pieces), comments and dependencies."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from .. import service
from ..deps import CurrentUser, Db
from ..models import (
    UNIQUE_PIECES,
    CommentCreate,
    MemberCreate,
    MemberMove,
    MemberUpdate,
    ProjectCreate,
    ProjectUpdate,
)
from ..service import eq
from ..supabase import Database, SupabaseError

router = APIRouter(prefix="/api", tags=["projects"])


async def _assert_square_free(db: Database, board: dict[str, Any], x: int, y: int, ignore_id: str | None = None) -> None:
    if not (0 <= x < board["cols"] and 0 <= y < board["rows"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That square is outside the board")
    occupant = await db.select_one(
        "projects", columns="id,name", filters={"board_id": eq(board["id"]), "pos_x": eq(str(x)), "pos_y": eq(str(y))}
    )
    if occupant and occupant["id"] != ignore_id:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Square already holds “{occupant['name']}”")


async def _assert_piece_available(db: Database, project_id: str, piece: str, ignore_member_id: str | None = None) -> None:
    """One king and one queen per project (section 8.1 of the plan)."""
    if piece not in UNIQUE_PIECES:
        return
    rows = await db.select(
        "project_members",
        columns="id,piece,profiles(full_name,email)",
        filters={"project_id": eq(project_id), "piece": eq(piece)},
    )
    for row in rows:
        if row["id"] == ignore_member_id:
            continue
        profile = row.get("profiles") or {}
        held_by = profile.get("full_name") or profile.get("email") or "someone else"
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"This project already has a {piece} ({held_by}). Only one is allowed."
        )


# --------------------------------------------------------------- projects ---
@router.post("/boards/{board_id}/projects", status_code=status.HTTP_201_CREATED)
async def create_project(board_id: str, body: ProjectCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    board = await service.get_board(db, board_id)
    await _assert_square_free(db, board, body.pos_x, body.pos_y)
    payload = body.model_dump()
    payload["start_date"] = body.start_date.isoformat() if body.start_date else None
    payload["deadline"] = body.deadline.isoformat() if body.deadline else None
    payload.update({"board_id": board_id, "created_by": user["user_id"]})
    rows = await db.insert("projects", payload)
    project = rows[0]
    await service.log_activity(
        db,
        board_id=board_id,
        actor_id=user["user_id"],
        action="project.created",
        project_id=project["id"],
        detail={"name": project["name"]},
    )
    project["members"] = []
    return project


@router.get("/projects/{project_id}")
async def read_project(project_id: str, db: Db) -> dict[str, Any]:
    project = await service.get_project(db, project_id)
    comments = await db.select(
        "comments",
        columns="id,body,created_at,author_id,profiles(full_name,email,avatar_url)",
        filters={"project_id": eq(project_id)},
        order="created_at.desc",
        limit=50,
    )
    for comment in comments:
        profile = comment.pop("profiles", None) or {}
        comment["author"] = profile.get("full_name") or profile.get("email", "Someone")
        comment["avatar_url"] = profile.get("avatar_url")
    dependencies = await db.select(
        "project_dependencies",
        columns="depends_on_id,projects!project_dependencies_depends_on_id_fkey(id,name,status,progress)",
        filters={"project_id": eq(project_id)},
    )
    return {
        "project": project,
        "comments": comments,
        "dependencies": [d.get("projects") for d in dependencies if d.get("projects")],
        "people": await service.get_board_people(db, project["board_id"]),
    }


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate, db: Db, user: CurrentUser) -> dict[str, Any]:
    current = await service.get_project(db, project_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        return current
    for key in ("start_date", "deadline"):
        if payload.get(key) is not None:
            payload[key] = payload[key].isoformat()

    if "pos_x" in payload or "pos_y" in payload:
        board = await service.get_board(db, current["board_id"])
        await _assert_square_free(
            db,
            board,
            payload.get("pos_x", current["pos_x"]),
            payload.get("pos_y", current["pos_y"]),
            ignore_id=project_id,
        )

    rows = await db.update("projects", {"id": eq(project_id)}, payload)
    if not rows:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have edit access to this board")
    updated = rows[0]

    if payload.get("status") and payload["status"] != current["status"]:
        action, detail = "project.status_changed", {"from": current["status"], "to": payload["status"]}
    elif "pos_x" in payload or "pos_y" in payload:
        action, detail = "project.moved", {"to": [updated["pos_x"], updated["pos_y"]]}
    else:
        action, detail = "project.updated", {"fields": sorted(payload)}
    await service.log_activity(
        db,
        board_id=current["board_id"],
        actor_id=user["user_id"],
        action=action,
        project_id=project_id,
        detail={**detail, "name": updated["name"]},
    )
    updated["members"] = current["members"]
    return updated


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_project(project_id: str, db: Db, user: CurrentUser) -> None:
    project = await service.get_project(db, project_id)
    await db.delete("projects", {"id": eq(project_id)})
    await service.log_activity(
        db,
        board_id=project["board_id"],
        actor_id=user["user_id"],
        action="project.deleted",
        detail={"name": project["name"]},
    )


# ---------------------------------------------------------------- members ---
@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(project_id: str, body: MemberCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    project = await service.get_project(db, project_id)
    if any(m["user_id"] == body.user_id for m in project["members"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "That person is already on this project")
    await _assert_piece_available(db, project_id, body.piece)
    try:
        rows = await db.insert(
            "project_members",
            {
                "project_id": project_id,
                "user_id": body.user_id,
                "piece": body.piece,
                "hours_allocated": body.hours_allocated,
            },
        )
    except SupabaseError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc
    await service.log_activity(
        db,
        board_id=project["board_id"],
        actor_id=user["user_id"],
        action="member.added",
        project_id=project_id,
        detail={"piece": body.piece, "project": project["name"]},
    )
    return rows[0]


@router.patch("/projects/{project_id}/members/{member_id}")
async def update_member(project_id: str, member_id: str, body: MemberUpdate, db: Db) -> dict[str, Any]:
    await service.get_project(db, project_id)
    payload = body.model_dump(exclude_unset=True)
    if payload.get("piece"):
        await _assert_piece_available(db, project_id, payload["piece"], ignore_member_id=member_id)
    rows = await db.update("project_members", {"id": eq(member_id), "project_id": eq(project_id)}, payload)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return rows[0]


@router.delete("/projects/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_member(project_id: str, member_id: str, db: Db, user: CurrentUser) -> None:
    project = await service.get_project(db, project_id)
    await db.delete("project_members", {"id": eq(member_id), "project_id": eq(project_id)})
    await service.log_activity(
        db,
        board_id=project["board_id"],
        actor_id=user["user_id"],
        action="member.removed",
        project_id=project_id,
        detail={"project": project["name"]},
    )


@router.post("/projects/{project_id}/members/{member_id}/move")
async def move_member(project_id: str, member_id: str, body: MemberMove, db: Db, user: CurrentUser) -> dict[str, Any]:
    """Drag a piece from one square to another."""
    source = await service.get_project(db, project_id)
    target = await service.get_project(db, body.to_project_id)
    if source["board_id"] != target["board_id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pieces can only move within the same board")

    assignment = next((m for m in source["members"] if m["id"] == member_id), None)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    if source["id"] == target["id"]:
        return assignment
    if any(m["user_id"] == assignment["user_id"] for m in target["members"]):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{assignment['name']} is already on “{target['name']}”")

    piece = body.piece or assignment["piece"]
    await _assert_piece_available(db, target["id"], piece)
    rows = await db.update(
        "project_members", {"id": eq(member_id)}, {"project_id": target["id"], "piece": piece}
    )
    if not rows:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have edit access to this board")
    await service.log_activity(
        db,
        board_id=source["board_id"],
        actor_id=user["user_id"],
        action="member.moved",
        project_id=target["id"],
        detail={"who": assignment["name"], "from": source["name"], "to": target["name"]},
    )
    return rows[0]


# --------------------------------------------------------------- comments ---
@router.post("/projects/{project_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(project_id: str, body: CommentCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    project = await service.get_project(db, project_id)
    rows = await db.insert(
        "comments", {"project_id": project_id, "author_id": user["user_id"], "body": body.body.strip()}
    )
    comment = rows[0]
    comment["author"] = user.get("name") or user.get("email", "You")
    await service.log_activity(
        db,
        board_id=project["board_id"],
        actor_id=user["user_id"],
        action="comment.added",
        project_id=project_id,
        detail={"project": project["name"]},
    )
    return comment


@router.delete("/projects/{project_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_comment(project_id: str, comment_id: str, db: Db) -> None:
    await db.delete("comments", {"id": eq(comment_id), "project_id": eq(project_id)})


# ----------------------------------------------------------- dependencies ---
@router.post("/projects/{project_id}/dependencies/{depends_on_id}", status_code=status.HTTP_201_CREATED)
async def add_dependency(project_id: str, depends_on_id: str, db: Db) -> dict[str, Any]:
    if project_id == depends_on_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project cannot depend on itself")
    await service.get_project(db, project_id)
    await service.get_project(db, depends_on_id)
    await db.insert(
        "project_dependencies",
        {"project_id": project_id, "depends_on_id": depends_on_id},
        upsert_on="project_id,depends_on_id",
        returning=False,
    )
    return {"ok": True}


@router.delete("/projects/{project_id}/dependencies/{depends_on_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_dependency(project_id: str, depends_on_id: str, db: Db) -> None:
    await db.delete("project_dependencies", {"project_id": eq(project_id), "depends_on_id": eq(depends_on_id)})
