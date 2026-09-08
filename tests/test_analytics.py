"""The derived numbers behind the analytics dashboard."""
from app.service import build_analytics


def make_project(name, status, progress=0, members=(), deadline=None):
    return {
        "id": name,
        "name": name,
        "status": status,
        "progress": progress,
        "deadline": deadline,
        "members": [dict(m) for m in members],
    }


PEOPLE = [
    {"id": "u1", "name": "Ada", "email": "ada@x.com", "job_title": "EM", "department": "Platform"},
    {"id": "u2", "name": "Bob", "email": "bob@x.com", "job_title": "Dev", "department": "Platform"},
]
BOARD = {"id": "b", "rows": 8, "cols": 8}


def member(user_id, name, piece="pawn", hours=10, active=True):
    return {"user_id": user_id, "name": name, "piece": piece, "hours_allocated": hours, "active": active}


def test_totals_and_status_breakdown():
    projects = [
        make_project("a", "active", 50, [member("u1", "Ada", "king")]),
        make_project("b", "blocked", 20, [member("u1", "Ada")]),
        make_project("c", "completed", 100),
    ]
    result = build_analytics(BOARD, projects, PEOPLE)

    assert result["totals"]["projects"] == 3
    assert result["totals"]["squares"] == 64
    assert result["totals"]["avg_progress"] == 35.0  # completed work is excluded
    assert result["totals"]["completion_rate"] == 33.3
    assert result["totals"]["unstaffed"] == 0
    counts = {row["status"]: row["count"] for row in result["by_status"]}
    assert counts == {"planning": 0, "active": 1, "blocked": 1, "completed": 1, "on_hold": 0}


def test_overallocation_is_flagged_past_three_projects():
    projects = [make_project(f"p{i}", "active", members=[member("u2", "Bob")]) for i in range(4)]
    result = build_analytics(BOARD, projects, PEOPLE)

    bob = next(row for row in result["allocation"] if row["id"] == "u2")
    assert bob["project_count"] == 4
    assert bob["hours"] == 40.0
    assert bob["overallocated"] is True
    ada = next(row for row in result["allocation"] if row["id"] == "u1")
    assert ada["overallocated"] is False
    assert result["totals"]["overallocated"] == 1


def test_completed_projects_do_not_consume_capacity():
    projects = [make_project(f"p{i}", "completed", members=[member("u2", "Bob")]) for i in range(5)]
    bob = next(row for row in build_analytics(BOARD, projects, PEOPLE)["allocation"] if row["id"] == "u2")
    assert bob["project_count"] == 0
    assert bob["overallocated"] is False


def test_inactive_assignments_are_ignored():
    projects = [make_project("p", "active", members=[member("u2", "Bob", active=False)])]
    bob = next(row for row in build_analytics(BOARD, projects, PEOPLE)["allocation"] if row["id"] == "u2")
    assert bob["project_count"] == 0


def test_at_risk_picks_up_blocked_and_imminent_deadlines():
    from datetime import date, timedelta

    soon = (date.today() + timedelta(days=3)).isoformat()
    far = (date.today() + timedelta(days=90)).isoformat()
    projects = [
        make_project("blocked", "blocked", 10),
        make_project("due-soon", "active", 60, deadline=soon),
        make_project("comfortable", "active", 60, deadline=far),
        make_project("done", "completed", 100, deadline=soon),
    ]
    at_risk = {row["name"] for row in build_analytics(BOARD, projects, PEOPLE)["at_risk"]}
    assert at_risk == {"blocked", "due-soon"}


def test_unstaffed_in_flight_projects_are_counted():
    projects = [make_project("a", "active"), make_project("b", "planning", members=[member("u1", "Ada")])]
    assert build_analytics(BOARD, projects, PEOPLE)["totals"]["unstaffed"] == 1
