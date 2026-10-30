"""Reminder emails (atomic claim, opt-in, age cutoff) and the public share page. No network."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ActivityLog, Goal, GoalUserSkill, QuizAttempt, Roadmap, ShareLink, Skill, StudyReminder, User
from app.routes import learning_routes, share_routes
from app.routes.auth_routes import get_current_user
from app.services import activity_service as act_mod
from app.services import reminder_email_service as res
from app.services import share_service as share_mod
from app.utils.config import settings

NOW = datetime(2026, 10, 26, 12, 0)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    for mod in (res, share_mod, act_mod, learning_routes):
        monkeypatch.setattr(mod, "SessionLocal", Session)
    db = Session()
    db.add_all([
        Goal(goal_id="g1", goal_name="ML Engineer"),
        User(user_id="u1", username="navya", email="n@x.test", email_reminders=True),
        User(user_id="u2", username="off", email="o@x.test"),                       # not opted in
        User(user_id="u3", username="noemail", email_reminders=True),                # no address
    ])
    db.flush()
    db.add(Skill(skill_id="s1", skill_name="Python"))
    db.flush()
    db.add_all([
        Roadmap(user_id="u1", goal_id="g1", goal_name="ML Engineer",
                data=json.dumps({"phases": [{"title": "Basics", "completed": True}, {"title": "Models", "completed": False}]})),
        GoalUserSkill(user_id="u1", goal_id="g1", skill_id="s1", mastery_probability=0.9, bkt_observations=5),
        QuizAttempt(user_id="u1", goal_id="g1", phase_index=0, total_questions=5, correct_answers=4, score_pct=80),
    ])
    db.commit()
    app = FastAPI()
    app.include_router(learning_routes.router)
    app.include_router(share_routes.router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    yield Session, TestClient(app)
    db.close()


def add_reminder(Session, user, due, **kw):
    db = Session()
    row = StudyReminder(user_id=user, title=kw.pop("title", "Revise"), due_at=due, **kw)
    db.add(row); db.commit(); rid = row.id; db.close()
    return rid


# ---- reminder emails ----------------------------------------------------------
def test_sends_due_reminder_once_only(env):
    Session, _ = env
    add_reminder(Session, "u1", NOW - timedelta(minutes=5), goal_id="g1")
    calls = []
    send = lambda to, title, due, goal: calls.append((to, title, goal)) or True
    assert res.send_due_reminders(NOW, send) == 1
    assert calls == [("n@x.test", "Revise", "ML Engineer")]
    assert res.send_due_reminders(NOW + timedelta(minutes=5), send) == 0      # already emailed


def test_skips_future_completed_old_and_non_opted_in(env):
    Session, _ = env
    add_reminder(Session, "u1", NOW + timedelta(hours=1))                       # not due yet
    add_reminder(Session, "u1", NOW - timedelta(minutes=1), completed=True)     # done
    add_reminder(Session, "u1", NOW - timedelta(hours=48))                      # too old (downtime)
    add_reminder(Session, "u2", NOW - timedelta(minutes=1))                     # not opted in
    add_reminder(Session, "u3", NOW - timedelta(minutes=1))                     # no email address
    assert res.send_due_reminders(NOW, lambda *a: True) == 0


def test_failed_send_releases_claim_so_it_retries(env):
    Session, _ = env
    rid = add_reminder(Session, "u1", NOW - timedelta(minutes=1))
    assert res.send_due_reminders(NOW, lambda *a: False) == 0
    assert res.send_due_reminders(NOW, lambda *a: (_ for _ in ()).throw(RuntimeError("smtp down"))) == 0
    db = Session(); assert db.get(StudyReminder, rid).emailed_at is None; db.close()
    assert res.send_due_reminders(NOW, lambda *a: True) == 1


def test_claim_is_atomic_when_another_worker_wins(env):
    Session, _ = env
    rid = add_reminder(Session, "u1", NOW - timedelta(minutes=1))
    db = Session()
    def other_worker_sends_first(*a):
        return True
    # Simulate the race: the row is already claimed before our UPDATE runs.
    row = db.get(StudyReminder, rid); row.emailed_at = NOW; db.commit(); db.close()
    assert res.send_due_reminders(NOW, other_worker_sends_first) == 0


def test_poller_is_off_without_flag_or_smtp(monkeypatch):
    p = res.ReminderEmailPoller()
    monkeypatch.setattr(settings, "REMINDER_EMAILS_ENABLED", True)
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert p.start() is False
    monkeypatch.setattr(settings, "REMINDER_EMAILS_ENABLED", False)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.x.test")
    assert p.start() is False


def test_email_preference_endpoints(env):
    Session, client = env
    assert client.get("/learning/email-preferences").json()["email_reminders"] is True
    assert client.put("/learning/email-preferences", json={"email_reminders": False}).json() == {"email_reminders": False}
    db = Session(); db.get(User, "u1").email = None; db.commit(); db.close()
    assert client.put("/learning/email-preferences", json={"email_reminders": True}).status_code == 400


# ---- sharing --------------------------------------------------------------------
def test_share_lifecycle_and_public_payload_is_safe(env):
    Session, client = env
    assert client.get("/learning/g1/share").json() == {"token": None}
    token = client.post("/learning/g1/share").json()["token"]
    assert client.post("/learning/g1/share").json()["token"] == token           # idempotent
    body = client.get(f"/share/{token}")
    assert body.status_code == 200 and body.headers["x-robots-tag"] == "noindex"
    data = body.json()
    assert data["learner"] == "navya" and data["goal_name"] == "ML Engineer"
    assert (data["phases_completed"], data["phases_total"], data["progress_pct"]) == (1, 2, 50)
    assert data["skills_mastered"] == 1 and data["quizzes_taken"] == 1 and data["average_quiz_score"] == 80
    flat = json.dumps(data)
    assert "n@x.test" not in flat and "u1" not in flat and "g1" not in flat      # no email or ids

    assert client.delete("/learning/g1/share").json() == {"revoked": True}
    assert client.get(f"/share/{token}").status_code == 404
    new = client.post("/learning/g1/share").json()["token"]
    assert new != token and client.get(f"/share/{new}").status_code == 200


def test_unknown_token_404_and_no_roadmap_404(env):
    _, client = env
    assert client.get("/share/not-a-real-token").status_code == 404
    assert client.post("/learning/nope/share").status_code == 404


def test_other_users_cannot_revoke(env):
    Session, client = env
    token = client.post("/learning/g1/share").json()["token"]
    client.app.dependency_overrides[get_current_user] = lambda: "u2"
    assert client.delete("/learning/g1/share").json() == {"revoked": False}
    assert client.get(f"/share/{token}").status_code == 200
