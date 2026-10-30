"""Streak counting in the learner's timezone, and the iCalendar export (no network)."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import Goal, Roadmap, StudyReminder, User
from app.routes import learning_routes
from app.routes.auth_routes import get_current_user
from app.services import learning_features_service as lfs
from app.services.activity_service import ActivityService
from app.utils import ical

streaks = ActivityService.compute_streaks
NOW = datetime(2026, 10, 25, 10, 0)          # a Sunday, 10:00 UTC
D = lambda days_ago, hour=12: datetime(2026, 10, 25, hour, 0) - timedelta(days=days_ago)


# ---- streaks -----------------------------------------------------------------
def test_no_activity():
    assert streaks([], NOW) == {"day_streak": 0, "longest_streak": 0, "studied_today": False}


def test_streak_survives_until_a_full_day_is_missed():
    assert streaks([D(1), D(2), D(3)], NOW)["day_streak"] == 3          # nothing yet today: still alive
    assert streaks([D(0), D(1), D(2)], NOW) == {"day_streak": 3, "longest_streak": 3, "studied_today": True}
    assert streaks([D(2), D(3)], NOW)["day_streak"] == 0                # yesterday missed: broken


def test_longest_streak_is_remembered_after_a_break():
    out = streaks([D(0), D(1), D(5), D(6), D(7), D(8)], NOW)
    assert out["day_streak"] == 2 and out["longest_streak"] == 4


def test_days_follow_the_learners_timezone_not_utc():
    # 20:00 UTC on the 24th is 01:30 on the 25th in IST (+330): that is "today" for an IST learner.
    late = datetime(2026, 10, 24, 20, 0)
    assert streaks([late], NOW, 0)["studied_today"] is False
    assert streaks([late], NOW, 330)["studied_today"] is True
    # Two sessions 20 hours apart in UTC can land on the same IST day.
    assert streaks([datetime(2026, 10, 24, 20, 0), datetime(2026, 10, 25, 3, 0)], NOW, 330)["day_streak"] == 1


# ---- iCalendar writer ---------------------------------------------------------
def test_escape_and_fold_follow_the_rfc():
    assert ical.escape_text("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    long_line = "SUMMARY:" + "é" * 100
    pieces = ical.fold(long_line)
    assert all(len(p.encode("utf-8")) <= 75 for p in pieces)
    assert all(p.startswith(" ") for p in pieces[1:])
    assert "".join([pieces[0]] + [p[1:] for p in pieces[1:]]) == long_line      # unfolding restores it


def test_event_has_the_required_fields_and_an_alarm():
    text = "\r\n".join(ical.event("u@x", "Study, hard", NOW, start=datetime(2026, 11, 1, 9, 0)))
    for needed in ("UID:u@x", "DTSTAMP:20261025T100000Z", "DTSTART:20261101T090000Z",
                   "DTEND:20261101T093000Z", "SUMMARY:Study\\, hard", "TRIGGER:-PT15M"):
        assert needed in text


def test_all_day_event_uses_date_values_and_no_alarm():
    text = "\r\n".join(ical.event("d@x", "Deadline", NOW, all_day=date(2026, 12, 31)))
    assert "DTSTART;VALUE=DATE:20261231" in text and "DTEND;VALUE=DATE:20270101" in text and "VALARM" not in text


# ---- the export endpoint --------------------------------------------------------
@pytest.fixture
def app_env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(lfs, "SessionLocal", Session)
    db = Session()
    db.add_all([Goal(goal_id="g1", goal_name="ML Engineer"), Goal(goal_id="g2", goal_name="Done Goal"),
                User(user_id="u1", username="one", email="1@x.test"), User(user_id="u2", username="two", email="2@x.test")])
    db.flush()
    db.add_all([
        StudyReminder(user_id="u1", title="Revise SQL", due_at=datetime(2026, 11, 2, 8, 0)),
        StudyReminder(user_id="u1", title="Finished one", due_at=datetime(2026, 11, 3, 8, 0), completed=True),
        StudyReminder(user_id="u2", title="Someone else's", due_at=datetime(2026, 11, 4, 8, 0)),
        Roadmap(user_id="u1", goal_id="g1", goal_name="ML Engineer", data=json.dumps({"phases": [], "deadline": "2026-12-15"}), is_complete=False),
        Roadmap(user_id="u1", goal_id="g2", goal_name="Done Goal", data=json.dumps({"phases": [], "deadline": "2026-11-20"}), is_complete=True),
    ])
    db.commit(); db.close()
    app = FastAPI()
    app.include_router(learning_routes.router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    return TestClient(app)


def test_export_contains_open_reminders_and_open_deadlines_only(app_env):
    response = app_env.get("/learning/calendar.ics")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/calendar")
    body = response.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Revise SQL" in body
    assert "Finished one" not in body and "Someone else" not in body          # completed and other users' items excluded
    assert "SUMMARY:Deadline: ML Engineer" in body and "DTSTART;VALUE=DATE:20261215" in body
    assert "Done Goal" not in body                                             # completed path: no deadline event
    assert body.count("BEGIN:VEVENT") == body.count("END:VEVENT") == 2
    assert body.count("DTSTAMP:") == 2
