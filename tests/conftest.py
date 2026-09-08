import os
import time

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SESSION_SECRET", "test-secret-value-for-signing-cookies")
os.environ.setdefault("COOKIE_SECURE", "false")

import pytest
from fastapi.testclient import TestClient

from app import session as session_mod
from app.main import app

USER_ID = "11111111-1111-4111-8111-111111111111"
BOARD_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"
OTHER_PROJECT_ID = "44444444-4444-4444-8444-444444444444"
MEMBER_ID = "55555555-5555-4555-8555-555555555555"
REST = "https://test.supabase.co/rest/v1"
AUTH = "https://test.supabase.co/auth/v1"


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def signed_in(client):
    session = {
        "access_token": "fake.jwt.token",
        "refresh_token": "refresh",
        "expires_at": int(time.time()) + 3600,
        "user_id": USER_ID,
        "email": "lead@example.com",
        "name": "Ada",
    }
    client.cookies.set(session_mod.COOKIE_NAME, session_mod.dumps(session))
    return client


def board_row(**overrides):
    return {
        "id": BOARD_ID,
        "name": "Engineering",
        "description": None,
        "rows": 8,
        "cols": 8,
        "owner_id": USER_ID,
        "archived": False,
        **overrides,
    }


def project_row(**overrides):
    row = {
        "id": PROJECT_ID,
        "board_id": BOARD_ID,
        "name": "Checkout rewrite",
        "description": "",
        "status": "active",
        "progress": 40,
        "start_date": None,
        "deadline": None,
        "pos_x": 0,
        "pos_y": 0,
        "tags": [],
        "blockers": [],
        "velocity": None,
        "cycle_time": None,
        "project_members": [],
    }
    row.update(overrides)
    return row


def member_row(**overrides):
    return {
        "id": MEMBER_ID,
        "user_id": USER_ID,
        "piece": "king",
        "hours_allocated": 20,
        "active": True,
        "joined_at": "2026-01-01T00:00:00Z",
        "profiles": {
            "id": USER_ID,
            "full_name": "Ada",
            "email": "lead@example.com",
            "avatar_url": None,
            "job_title": "EM",
            "department": "Platform",
        },
        **overrides,
    }
