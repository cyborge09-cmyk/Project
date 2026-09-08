"""Board CRUD, board membership, activity and analytics."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from .. import service
from ..deps import CurrentUser, Db
from ..models import BoardCreate, BoardMemberCreate, BoardUpdate
from ..service import eq

router = APIRouter(prefix="/api/boards", tags=["boards"])


@router.get("")
async def list_boards(db: Db) -> list[dict[str, Any]]:
    boards = await db.select("boards", filters={"archived": "eq.false"}, order="created_at.asc")
    for board in boards:
        counts = await db.select("projects", columns="id,status", filters={"board_id": eq(board["id"])})
        board["project_count"] = len(counts)
        board["active_count"] = sum(1 for c in counts if c["status"] == "active")
        board["blocked_count"] = sum(1 for c in counts if c["status"] == "blocked")
    return boards


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_board(body: BoardCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    rows = await db.insert(
        "boards",
        {
            "name": body.name,
            "description": body.description,
            "rows": body.rows,
            "cols": body.cols,
            "owner_id": user["user_id"],
        },
    )
    board = rows[0]
    await service.log_activity(
        db, board_id=board["id"], actor_id=user["user_id"], action="board.created", detail={"name": board["name"]}
    )
    return board


@router.get("/{board_id}")
async def read_board(board_id: str, db: Db) -> dict[str, Any]:
    board = await service.get_board(db, board_id)
    return {
        "board": board,
        "projects": await service.get_projects(db, board_id),
        "people": await service.get_board_people(db, board_id),
    }


@router.patch("/{board_id}")
async def update_board(board_id: str, body: BoardUpdate, db: Db) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        return await service.get_board(db, board_id)
    rows = await db.update("boards", {"id": eq(board_id)}, payload)
    if not rows:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the board owner can change board settings")
    return rows[0]


@router.delete("/{board_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_board(board_id: str, db: Db) -> None:
    await service.get_board(db, board_id)
    await db.delete("boards", {"id": eq(board_id)})


@router.get("/{board_id}/people")
async def board_people(board_id: str, db: Db) -> list[dict[str, Any]]:
    await service.get_board(db, board_id)
    return await service.get_board_people(db, board_id)


@router.post("/{board_id}/people", status_code=status.HTTP_201_CREATED)
async def add_board_person(board_id: str, body: BoardMemberCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    await service.get_board(db, board_id)
    profile = await db.select_one("profiles", columns="id,email,full_name", filters={"email": eq(body.email)})
    if not profile:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No account for {body.email}. They need to sign up first, then you can add them.",
        )
    await db.insert(
        "board_members",
        {"board_id": board_id, "user_id": profile["id"], "role": body.role},
        upsert_on="board_id,user_id",
    )
    await service.log_activity(
        db, board_id=board_id, actor_id=user["user_id"], action="board.person_added", detail={"email": body.email}
    )
    return {"ok": True, "user_id": profile["id"]}


@router.delete("/{board_id}/people/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_board_person(board_id: str, user_id: str, db: Db) -> None:
    board = await service.get_board(db, board_id)
    if board["owner_id"] == user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The board owner cannot be removed")
    await db.delete("board_members", {"board_id": eq(board_id), "user_id": eq(user_id)})


@router.get("/{board_id}/activity")
async def board_activity(board_id: str, db: Db, limit: int = 30) -> list[dict[str, Any]]:
    await service.get_board(db, board_id)
    return await service.get_activity(db, board_id, min(max(limit, 1), 100))


@router.get("/{board_id}/analytics")
async def board_analytics(board_id: str, db: Db) -> dict[str, Any]:
    board = await service.get_board(db, board_id)
    projects = await service.get_projects(db, board_id)
    people = await service.get_board_people(db, board_id)
    return service.build_analytics(board, projects, people)
