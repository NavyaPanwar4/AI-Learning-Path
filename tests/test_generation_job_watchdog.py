"""Regression tests for stale roadmap generation job recovery."""
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db import models
from app.services import roadmap_service as roadmap_module


def _make_session(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(roadmap_module, "SessionLocal", Session)
    db = Session()
    db.add(models.Goal(goal_id="goal-python", goal_name="Python Developer"))
    db.add(models.User(user_id="user-1", username="learner", goal_id="goal-python"))
    db.commit()
    db.close()
    return engine, Session


def _insert_job(Session, status: str, age_seconds: int):
    now = datetime.utcnow()
    db = Session()
    job = models.RoadmapGenerationJob(
        job_id=f"job-{status}",
        user_id="user-1",
        goal_id="goal-python",
        status=status,
        created_at=now - timedelta(seconds=age_seconds),
        updated_at=now - timedelta(seconds=age_seconds),
    )
    db.add(job)
    db.commit()
    db.close()
    return job.job_id


def test_queued_job_stale_after_five_minutes_becomes_failed(monkeypatch):
    engine, Session = _make_session(monkeypatch)
    try:
        job_id = _insert_job(Session, "queued", 301)
        result = roadmap_module.roadmap_service.get_generation_job(job_id, "user-1")
        assert result["status"] == "failed"
        assert "did not start" in result["error"]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_running_job_under_twenty_minutes_remains_running(monkeypatch):
    engine, Session = _make_session(monkeypatch)
    try:
        job_id = _insert_job(Session, "running", 19 * 60)
        result = roadmap_module.roadmap_service.get_generation_job(job_id, "user-1")
        assert result["status"] == "running"
        assert result["error"] is None
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_running_job_over_twenty_minutes_becomes_failed(monkeypatch):
    engine, Session = _make_session(monkeypatch)
    try:
        job_id = _insert_job(Session, "running", 20 * 60 + 1)
        result = roadmap_module.roadmap_service.get_generation_job(job_id, "user-1")
        assert result["status"] == "failed"
        assert "20-minute safety limit" in result["error"]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_unacknowledged_cancellation_becomes_cancelled(monkeypatch):
    engine, Session = _make_session(monkeypatch)
    try:
        job_id = _insert_job(Session, "cancel_requested", 5 * 60 + 1)
        result = roadmap_module.roadmap_service.get_generation_job(job_id, "user-1")
        assert result["status"] == "cancelled"
        assert "watchdog" in result["error"]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_status_query_is_user_scoped(monkeypatch):
    engine, Session = _make_session(monkeypatch)
    try:
        job_id = _insert_job(Session, "running", 30)
        assert roadmap_module.roadmap_service.get_generation_job(job_id, "other-user") is None
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
