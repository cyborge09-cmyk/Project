"""End-to-end route tests with Supabase's REST API mocked."""
import re

import httpx
import pytest
import respx

from tests.conftest import (
    AUTH,
    BOARD_ID,
    MEMBER_ID,
    OTHER_PROJECT_ID,
    PROJECT_ID,
    REST,
    USER_ID,
    board_row,
    member_row,
    project_row,
)


def test_health(client):
    body = client.get("/api/health").json()
    assert body == {"ok": True, "supabase_configured": True}


def test_anonymous_visitor_is_sent_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_anonymous_api_call_is_401(client):
    assert client.get("/api/boards").status_code == 401


def test_login_page_renders_the_board_pitch(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert "Every square a project" in page.text


@respx.mock
def test_sign_in_sets_a_session_cookie(client):
    respx.post(f"{AUTH}/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "abc.def.ghi",
                "refresh_token": "r",
                "expires_at": 4102444800,
                "user": {"id": USER_ID, "email": "lead@example.com", "user_metadata": {"full_name": "Ada"}},
            },
        )
    )
    response = client.post("/api/auth/login", json={"email": "lead@example.com", "password": "hunter22"})
    assert response.status_code == 200
    assert "cb_session" in response.cookies


@respx.mock
def test_bad_credentials_surface_supabase_message(client):
    respx.post(f"{AUTH}/token").mock(
        return_value=httpx.Response(400, json={"error_description": "Invalid login credentials"})
    )
    response = client.post("/api/auth/login", json={"email": "lead@example.com", "password": "nope1234"})
    assert response.status_code == 400
    assert response.json() == {"error": "Invalid login credentials"}


@respx.mock
def test_board_page_renders_projects_and_pieces(signed_in):
    project = project_row(project_members=[member_row()])
    respx.get(f"{REST}/boards").mock(return_value=httpx.Response(200, json=[board_row()]))
    respx.get(f"{REST}/projects").mock(return_value=httpx.Response(200, json=[project]))
    respx.get(f"{REST}/board_members").mock(
        return_value=httpx.Response(200, json=[{"role": "owner", "added_at": "", "profiles": member_row()["profiles"]}])
    )
    respx.get(f"{REST}/activity").mock(return_value=httpx.Response(200, json=[]))

    page = signed_in.get(f"/boards/{BOARD_ID}")
    assert page.status_code == 200
    assert "Checkout rewrite" in page.text
    assert "Engineering" in page.text
    # The board data is handed to the client as JSON for the interactive layer.
    assert '"pos_x": 0' in page.text


@respx.mock
def test_missing_board_is_404(signed_in):
    respx.get(f"{REST}/boards").mock(return_value=httpx.Response(200, json=[]))
    response = signed_in.get(f"/api/boards/{BOARD_ID}")
    assert response.status_code == 404


@respx.mock
def test_creating_a_project_on_a_taken_square_is_rejected(signed_in):
    respx.get(f"{REST}/boards").mock(return_value=httpx.Response(200, json=[board_row()]))
    respx.get(f"{REST}/projects").mock(return_value=httpx.Response(200, json=[{"id": PROJECT_ID, "name": "Checkout rewrite"}]))
    create = respx.post(f"{REST}/projects").mock(return_value=httpx.Response(201, json=[project_row()]))

    response = signed_in.post(
        f"/api/boards/{BOARD_ID}/projects", json={"name": "New thing", "pos_x": 0, "pos_y": 0}
    )
    assert response.status_code == 409
    assert "already holds" in response.json()["error"]
    assert not create.called


@respx.mock
def test_creating_a_project_off_the_board_is_rejected(signed_in):
    respx.get(f"{REST}/boards").mock(return_value=httpx.Response(200, json=[board_row(rows=4, cols=4)]))
    response = signed_in.post(
        f"/api/boards/{BOARD_ID}/projects", json={"name": "New thing", "pos_x": 7, "pos_y": 0}
    )
    assert response.status_code == 400
    assert "outside the board" in response.json()["error"]


@respx.mock
def test_creating_a_project_stores_the_square_and_logs_activity(signed_in):
    respx.get(f"{REST}/boards").mock(return_value=httpx.Response(200, json=[board_row()]))
    respx.get(f"{REST}/projects").mock(return_value=httpx.Response(200, json=[]))
    create = respx.post(f"{REST}/projects").mock(
        return_value=httpx.Response(201, json=[project_row(name="New thing", pos_x=2, pos_y=3)])
    )
    activity = respx.post(f"{REST}/activity").mock(return_value=httpx.Response(201, json=[]))

    response = signed_in.post(
        f"/api/boards/{BOARD_ID}/projects",
        json={"name": "New thing", "pos_x": 2, "pos_y": 3, "status": "planning", "deadline": "2026-12-01"},
    )
    assert response.status_code == 201
    sent = create.calls.last.request
    body = sent.read().decode()
    assert '"pos_x":2' in body and '"pos_y":3' in body
    assert '"deadline":"2026-12-01"' in body
    assert BOARD_ID in body
    assert activity.called


@respx.mock
def test_second_king_on_a_project_is_refused(signed_in):
    respx.get(f"{REST}/projects").mock(
        return_value=httpx.Response(200, json=[project_row(project_members=[member_row()])])
    )
    respx.get(f"{REST}/project_members").mock(return_value=httpx.Response(200, json=[member_row()]))
    insert = respx.post(f"{REST}/project_members").mock(return_value=httpx.Response(201, json=[]))

    response = signed_in.post(
        f"/api/projects/{PROJECT_ID}/members",
        json={"user_id": "99999999-9999-4999-8999-999999999999", "piece": "king"},
    )
    assert response.status_code == 409
    assert "already has a king" in response.json()["error"]
    assert not insert.called


@respx.mock
def test_a_person_cannot_be_added_to_the_same_project_twice(signed_in):
    respx.get(f"{REST}/projects").mock(
        return_value=httpx.Response(200, json=[project_row(project_members=[member_row()])])
    )
    response = signed_in.post(f"/api/projects/{PROJECT_ID}/members", json={"user_id": USER_ID, "piece": "pawn"})
    assert response.status_code == 409
    assert "already on this project" in response.json()["error"]


@respx.mock
def test_moving_a_piece_updates_the_assignment(signed_in):
    source = project_row(project_members=[member_row()])
    target = project_row(id=OTHER_PROJECT_ID, name="Billing", pos_x=1, project_members=[])

    def by_id(request):
        wanted = request.url.params.get("id", "")
        row = target if OTHER_PROJECT_ID in wanted else source
        return httpx.Response(200, json=[row])

    respx.get(f"{REST}/projects").mock(side_effect=by_id)
    respx.get(f"{REST}/project_members").mock(return_value=httpx.Response(200, json=[]))
    update = respx.patch(f"{REST}/project_members").mock(
        return_value=httpx.Response(200, json=[member_row(project_id=OTHER_PROJECT_ID)])
    )
    respx.post(f"{REST}/activity").mock(return_value=httpx.Response(201, json=[]))

    response = signed_in.post(
        f"/api/projects/{PROJECT_ID}/members/{MEMBER_ID}/move", json={"to_project_id": OTHER_PROJECT_ID}
    )
    assert response.status_code == 200
    body = update.calls.last.request.read().decode()
    assert OTHER_PROJECT_ID in body


@respx.mock
def test_a_piece_cannot_move_to_a_square_where_the_person_already_stands(signed_in):
    source = project_row(project_members=[member_row()])
    target = project_row(id=OTHER_PROJECT_ID, name="Billing", project_members=[member_row(id="other")])

    def by_id(request):
        wanted = request.url.params.get("id", "")
        return httpx.Response(200, json=[target if OTHER_PROJECT_ID in wanted else source])

    respx.get(f"{REST}/projects").mock(side_effect=by_id)
    update = respx.patch(f"{REST}/project_members").mock(return_value=httpx.Response(200, json=[]))

    response = signed_in.post(
        f"/api/projects/{PROJECT_ID}/members/{MEMBER_ID}/move", json={"to_project_id": OTHER_PROJECT_ID}
    )
    assert response.status_code == 409
    assert "already on" in response.json()["error"]
    assert not update.called


@respx.mock
def test_progress_outside_the_range_is_rejected_before_reaching_supabase(signed_in):
    call = respx.patch(f"{REST}/projects").mock(return_value=httpx.Response(200, json=[project_row()]))
    response = signed_in.patch(f"/api/projects/{PROJECT_ID}", json={"progress": 140})
    assert response.status_code == 422
    assert "progress" in response.json()["error"]
    assert not call.called


@respx.mock
def test_adding_an_unknown_teammate_explains_why(signed_in):
    respx.get(f"{REST}/boards").mock(return_value=httpx.Response(200, json=[board_row()]))
    respx.get(f"{REST}/profiles").mock(return_value=httpx.Response(200, json=[]))
    response = signed_in.post(f"/api/boards/{BOARD_ID}/people", json={"email": "ghost@example.com"})
    assert response.status_code == 404
    assert "sign up first" in response.json()["error"]


@respx.mock
def test_my_workload_summarises_assignments(signed_in):
    respx.get(f"{REST}/project_members").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": MEMBER_ID,
                    "piece": "knight",
                    "hours_allocated": 30,
                    "active": True,
                    "projects": {
                        "id": PROJECT_ID,
                        "name": "Checkout rewrite",
                        "status": "blocked",
                        "progress": 20,
                        "deadline": "2026-10-01",
                        "board_id": BOARD_ID,
                        "boards": {"id": BOARD_ID, "name": "Engineering"},
                    },
                }
            ],
        )
    )
    body = signed_in.get("/api/me/workload").json()
    assert body["totals"] == {"projects": 1, "hours": 30.0, "blocked": 1, "overallocated": False}
    assert body["assignments"][0]["glyph"] == "♞"
    assert body["assignments"][0]["board_name"] == "Engineering"


@respx.mock
def test_expired_session_without_a_usable_refresh_token_redirects_to_login(client):
    import time

    from app import session as session_mod

    stale = {
        "access_token": "old.jwt.token",
        "refresh_token": "dead",
        "expires_at": int(time.time()) - 10,
        "user_id": USER_ID,
        "email": "lead@example.com",
        "name": "Ada",
    }
    client.cookies.set(session_mod.COOKIE_NAME, session_mod.dumps(stale))
    respx.post(f"{AUTH}/token").mock(return_value=httpx.Response(401, json={"message": "Invalid Refresh Token"}))

    response = client.get("/my-work", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


@respx.mock
def test_an_expiring_session_is_refreshed_transparently(client):
    import time

    from app import session as session_mod

    stale = {
        "access_token": "old.jwt.token",
        "refresh_token": "good",
        "expires_at": int(time.time()) - 10,
        "user_id": USER_ID,
        "email": "lead@example.com",
        "name": "Ada",
    }
    client.cookies.set(session_mod.COOKIE_NAME, session_mod.dumps(stale))
    respx.post(f"{AUTH}/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new.jwt.token",
                "refresh_token": "good2",
                "expires_at": int(time.time()) + 3600,
                "user": {"id": USER_ID, "email": "lead@example.com", "user_metadata": {}},
            },
        )
    )
    respx.get(f"{REST}/project_members").mock(return_value=httpx.Response(200, json=[]))

    response = client.get("/my-work")
    assert response.status_code == 200
    # The rotated tokens are written straight back onto the response.
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(session_mod.COOKIE_NAME + "=")
    refreshed = session_mod.loads(set_cookie.split("=", 1)[1].split(";", 1)[0])
    assert refreshed["access_token"] == "new.jwt.token"


def test_tampered_session_cookie_is_ignored(client):
    client.cookies.set("cb_session", "not-a-valid-signed-value")
    assert client.get("/api/boards").status_code == 401


@respx.mock
def test_supabase_outage_is_reported_as_bad_gateway(signed_in):
    respx.get(f"{REST}/project_members").mock(side_effect=httpx.ConnectError("boom"))
    response = signed_in.get("/api/me/workload")
    assert response.status_code == 502
    assert "Could not reach Supabase" in response.json()["error"]
