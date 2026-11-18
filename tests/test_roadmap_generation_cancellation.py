"""Tests for authenticated and cooperative cancellation of roadmap jobs."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db import models
from app.services import roadmap_service as roadmap_module
from app.services.roadmap_service import RoadmapGenerationCancelled


@pytest.fixture()
def cancellation_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(roadmap_module, "SessionLocal", Session)
    monkeypatch.setattr(
        roadmap_module.auth_service,
        "get_user_by_id",
        lambda user_id: {
            "user_id": str(user_id),
            "goal_id": "goal-python",
            "experience_level": "beginner",
            "available_hours_per_week": 8,
            "learning_style": "visual",
        },
    )
    db = Session()
    db.add(models.Goal(goal_id="goal-python", goal_name="Python Developer"))
    db.add(models.User(user_id="user-1", username="learner", goal_id="goal-python"))
    db.add(models.User(user_id="user-2", username="other", goal_id="goal-python"))
    db.commit()
    db.close()
    yield Session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_queued_job_can_be_cancelled_immediately(cancellation_db, monkeypatch):
    job = roadmap_module.roadmap_service.create_generation_job("user-1")
    result = roadmap_module.roadmap_service.request_cancel_generation(job["job_id"], "user-1")
    assert result["status"] == "cancelled"

    calls = []
    monkeypatch.setattr(
        roadmap_module.roadmap_service,
        "generate_personalized_roadmap",
        lambda user_id, job_id=None: calls.append((user_id, job_id)),
    )
    roadmap_module.roadmap_service.run_generation_job(job["job_id"], "user-1")
    assert calls == []

    db = cancellation_db()
    saved = db.query(models.RoadmapGenerationJob).filter_by(job_id=job["job_id"]).one()
    assert saved.status == "cancelled"
    db.close()


def test_running_job_moves_to_cancel_requested_and_remains_unique(cancellation_db):
    job = roadmap_module.roadmap_service.create_generation_job("user-1")
    db = cancellation_db()
    db.query(models.RoadmapGenerationJob).filter_by(job_id=job["job_id"]).update({"status": "running"})
    db.commit()
    db.close()

    result = roadmap_module.roadmap_service.request_cancel_generation(job["job_id"], "user-1")
    assert result["status"] == "cancel_requested"

    reused = roadmap_module.roadmap_service.create_generation_job("user-1")
    assert reused["job_id"] == job["job_id"]
    assert reused["status"] == "cancel_requested"
    assert reused["reused"] is True


def test_cancel_request_is_scoped_to_owning_user(cancellation_db):
    job = roadmap_module.roadmap_service.create_generation_job("user-1")
    assert roadmap_module.roadmap_service.request_cancel_generation(job["job_id"], "user-2") is None
    current = roadmap_module.roadmap_service.get_generation_job(job["job_id"], "user-1")
    assert current["status"] == "queued"


def test_worker_acknowledges_running_cancellation_and_does_not_save(cancellation_db, monkeypatch):
    job = roadmap_module.roadmap_service.create_generation_job("user-1")

    def cancel_during_generation(user_id, job_id=None):
        response = roadmap_module.roadmap_service.request_cancel_generation(job_id, user_id)
        assert response["status"] == "cancel_requested"
        raise RoadmapGenerationCancelled("cancelled by test")

    monkeypatch.setattr(
        roadmap_module.roadmap_service,
        "generate_personalized_roadmap",
        cancel_during_generation,
    )
    roadmap_module.roadmap_service.run_generation_job(job["job_id"], "user-1")

    db = cancellation_db()
    saved = db.query(models.RoadmapGenerationJob).filter_by(job_id=job["job_id"]).one()
    assert saved.status == "cancelled"
    assert db.query(models.Roadmap).filter_by(user_id="user-1", goal_id="goal-python").count() == 0
    db.close()


def test_cancellation_helper_raises_at_safe_checkpoint(cancellation_db):
    job = roadmap_module.roadmap_service.create_generation_job("user-1")
    roadmap_module.roadmap_service.request_cancel_generation(job["job_id"], "user-1")
    with pytest.raises(RoadmapGenerationCancelled):
        roadmap_module.roadmap_service._raise_if_generation_cancelled(job["job_id"], "user-1")
