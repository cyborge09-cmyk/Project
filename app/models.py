"""Request payloads and the chess vocabulary shared by API and templates."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Status = Literal["planning", "active", "blocked", "completed", "on_hold"]
Piece = Literal["king", "queen", "rook", "bishop", "knight", "pawn"]

# Section 2.2 of the plan: piece -> role, with the glyph and colour used in the UI.
PIECES: dict[str, dict[str, str]] = {
    "king": {"glyph": "♚", "role": "Project Lead", "meaning": "Authority, decision-maker", "color": "#e04a4a"},
    "queen": {"glyph": "♛", "role": "Tech Lead", "meaning": "Versatile, high impact", "color": "#e0942a"},
    "rook": {"glyph": "♜", "role": "Senior Developer", "meaning": "Powerful, structured", "color": "#3b7dd8"},
    "bishop": {"glyph": "♝", "role": "Designer / Architect", "meaning": "Strategic positioning", "color": "#1c9c8b"},
    "knight": {"glyph": "♞", "role": "Specialist", "meaning": "Unique skills, nimble", "color": "#8b5cd6"},
    "pawn": {"glyph": "♟", "role": "Junior / Support", "meaning": "Growing potential", "color": "#7c8798"},
}

# Section 3.1.5: status -> label and colour.
STATUSES: dict[str, dict[str, str]] = {
    "planning": {"label": "Planning", "color": "#d99a24", "hint": "Not yet started"},
    "active": {"label": "Active", "color": "#3b7dd8", "hint": "Currently in progress"},
    "blocked": {"label": "Blocked", "color": "#d9453f", "hint": "Waiting on dependencies"},
    "completed": {"label": "Completed", "color": "#2f9e5f", "hint": "Finished"},
    "on_hold": {"label": "On hold", "color": "#7c8798", "hint": "Paused"},
}

# Only one of each royal piece may sit on a project (section 8.1).
UNIQUE_PIECES = {"king", "queen"}


class SignUpIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class SignInIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class BoardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    rows: int = Field(default=8, ge=2, le=16)
    cols: int = Field(default=8, ge=2, le=16)


class BoardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    rows: int | None = Field(default=None, ge=2, le=16)
    cols: int | None = Field(default=None, ge=2, le=16)
    archived: bool | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    status: Status = "planning"
    progress: int = Field(default=0, ge=0, le=100)
    start_date: date | None = None
    deadline: date | None = None
    pos_x: int = Field(ge=0, le=15)
    pos_y: int = Field(ge=0, le=15)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, tags: list[str]) -> list[str]:
        return [t.strip()[:40] for t in tags if t and t.strip()]


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    status: Status | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    start_date: date | None = None
    deadline: date | None = None
    pos_x: int | None = Field(default=None, ge=0, le=15)
    pos_y: int | None = Field(default=None, ge=0, le=15)
    tags: list[str] | None = Field(default=None, max_length=20)
    blockers: list[str] | None = Field(default=None, max_length=20)


class MemberCreate(BaseModel):
    user_id: str
    piece: Piece = "pawn"
    hours_allocated: float = Field(default=0, ge=0, le=400)


class MemberUpdate(BaseModel):
    piece: Piece | None = None
    hours_allocated: float | None = Field(default=None, ge=0, le=400)
    active: bool | None = None


class MemberMove(BaseModel):
    """Drag a piece from one project square to another."""

    to_project_id: str
    piece: Piece | None = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class BoardMemberCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"
