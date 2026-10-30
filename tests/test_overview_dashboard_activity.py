from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ActivityLog, QuizAttempt, Roadmap, User
import app.services.dashboard_activity_service as activity_module


@pytest.fixture

def activity_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(activity_module, "SessionLocal", Session)
    session = Session()
    session.add_all([
        User(user_id="overview-user", username="overview-user", email="overview@example.test"),
        User(user_id="other-user", username="other-user", email="other@example.test"),
    ])
    session.commit()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        yield session, now
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_weekly_summary_counts_only_authenticated_users_activity(activity_db):
    session, now = activity_db
    session.add_all([
        ActivityLog(user_id="overview-user", activity_type="session", duration_minutes=24, created_at=now - timedelta(days=1)),
        ActivityLog(user_id="overview-user", activity_type="roadmap_generated", created_at=now - timedelta(days=2)),
        ActivityLog(user_id="overview-user", activity_type="quiz_attempt", created_at=now - timedelta(days=1)),
        ActivityLog(user_id="other-user", activity_type="session", duration_minutes=90, created_at=now - timedelta(days=1)),
        QuizAttempt(user_id="overview-user", goal_id="goal-1", phase_index=0, total_questions=4, correct_answers=3, score_pct=75, created_at=now - timedelta(days=1)),
        Roadmap(user_id="overview-user", goal_id="goal-1", goal_name="ML Engineer Path", data="{}", is_complete=False, created_at=now - timedelta(days=3)),
    ])
    session.commit()

    result = activity_module.dashboard_activity_service.get_summary("overview-user")

    assert len(result["weekly_activity"]) == 7
    assert result["weekly_totals"] == {
        "minutes": 24,
        "sessions": 1,
        "quizzes": 1,
        "activity_count": 3,
    }
    assert any(item["goal_name"] == "ML Engineer Path" for item in result["recent_activity"])
    assert all(item.get("goal_name") != "other-user" for item in result["recent_activity"])


def test_recent_activity_can_show_items_older_than_the_weekly_chart(activity_db):
    session, now = activity_db
    session.add(ActivityLog(
        user_id="overview-user",
        activity_type="roadmap_generated",
        created_at=now - timedelta(days=12),
    ))
    session.commit()

    result = activity_module.dashboard_activity_service.get_summary("overview-user")

    assert result["weekly_totals"]["activity_count"] == 0
    assert len(result["recent_activity"]) == 1
    assert result["recent_activity"][0]["title"] == "Learning path created"
