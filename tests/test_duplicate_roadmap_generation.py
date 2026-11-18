"""Regression tests for duplicate roadmap generation protection."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db import models
from app.services import roadmap_service as roadmap_module
from app.services.roadmap_service import RoadmapAlreadyExistsError
from app.routes import roadmap_routes
from fastapi import BackgroundTasks, HTTPException


@pytest.fixture()
def duplicate_guard_db(monkeypatch):
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
    db.commit()
    db.close()
    yield Session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_existing_saved_roadmap_blocks_new_generation(duplicate_guard_db):
    db = duplicate_guard_db()
    db.add(models.Roadmap(
        user_id="user-1",
        goal_id="goal-python",
        goal_name="Python Developer",
        data='{"phases": []}',
        is_complete=False,
    ))
    db.commit()
    db.close()

    with pytest.raises(RoadmapAlreadyExistsError) as raised:
        roadmap_module.roadmap_service.create_generation_job("user-1")

    assert raised.value.goal_id == "goal-python"
    assert raised.value.as_detail()["code"] == "ROADMAP_ALREADY_EXISTS"


def test_duplicate_request_reuses_existing_queued_job(duplicate_guard_db):
    first = roadmap_module.roadmap_service.create_generation_job("user-1")
    second = roadmap_module.roadmap_service.create_generation_job("user-1")

    assert first["status"] == "queued"
    assert first["reused"] is False
    assert second["job_id"] == first["job_id"]
    assert second["reused"] is True

    db = duplicate_guard_db()
    assert db.query(models.RoadmapGenerationJob).filter_by(user_id="user-1", goal_id="goal-python").count() == 1
    db.close()


def test_deleted_roadmap_allows_generation_again(duplicate_guard_db):
    db = duplicate_guard_db()
    db.add(models.Roadmap(
        user_id="user-1",
        goal_id="goal-python",
        goal_name="Python Developer",
        data='{"phases": []}',
        is_complete=False,
    ))
    db.commit()
    db.close()

    assert roadmap_module.roadmap_service.delete_roadmap("user-1", "goal-python") is True
    new_job = roadmap_module.roadmap_service.create_generation_job("user-1")
    assert new_job["status"] == "queued"
    assert new_job["goal_id"] == "goal-python"
    assert new_job["reused"] is False


def test_generation_job_is_claimed_and_executed_only_once(duplicate_guard_db, monkeypatch):
    db = duplicate_guard_db()
    db.add(models.RoadmapGenerationJob(
        job_id="queued-job",
        user_id="user-1",
        goal_id="goal-python",
        status="queued",
    ))
    db.commit()
    db.close()

    calls = []
    def fake_generate(user_id, job_id=None):
        calls.append(user_id)
        db = duplicate_guard_db()
        db.add(models.Roadmap(
            user_id=str(user_id),
            goal_id="goal-python",
            goal_name="Python Developer",
            data='{"phases": []}',
            is_complete=False,
        ))
        db.commit()
        db.close()
        return {"goal_id": "goal-python"}

    monkeypatch.setattr(
        roadmap_module.roadmap_service,
        "generate_personalized_roadmap",
        fake_generate,
    )
    roadmap_module.roadmap_service.run_generation_job("queued-job", "user-1")
    roadmap_module.roadmap_service.run_generation_job("queued-job", "user-1")

    db = duplicate_guard_db()
    job = db.query(models.RoadmapGenerationJob).filter_by(job_id="queued-job").one()
    assert calls == ["user-1"]
    assert job.status == "completed"
    assert job.goal_id == "goal-python"
    db.close()


def test_failed_or_completed_job_does_not_block_retry(duplicate_guard_db):
    db = duplicate_guard_db()
    db.add(models.RoadmapGenerationJob(
        job_id="old-job",
        user_id="user-1",
        goal_id="goal-python",
        status="failed",
    ))
    db.commit()
    db.close()

    new_job = roadmap_module.roadmap_service.create_generation_job("user-1")
    assert new_job["job_id"] != "old-job"
    assert new_job["reused"] is False


def _allow_route_mastery_gate(monkeypatch):
    verifier = getattr(roadmap_routes, "mastery_verification_service", None)
    if verifier is not None:
        monkeypatch.setattr(verifier, "pending_for_active_goal", lambda _user_id: {"pending_skills": []})


def test_route_returns_conflict_for_existing_saved_roadmap(monkeypatch):
    def raise_existing(_user_id):
        raise RoadmapAlreadyExistsError("goal-python", "Python Developer")

    _allow_route_mastery_gate(monkeypatch)
    monkeypatch.setattr(roadmap_routes.roadmap_service, "get_existing_roadmap_for_active_goal", lambda _user_id: None)
    monkeypatch.setattr(roadmap_routes.roadmap_service, "create_generation_job", raise_existing)
    with pytest.raises(HTTPException) as raised:
        roadmap_routes._queue_roadmap_generation(BackgroundTasks(), "user-1")

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "ROADMAP_ALREADY_EXISTS"
    assert raised.value.detail["goal_id"] == "goal-python"


def test_saved_roadmap_notice_precedes_mastery_verification(monkeypatch):
    class FakeService:
        @staticmethod
        def get_existing_roadmap_for_active_goal(_user_id):
            return {"goal_id": "goal-python", "goal_name": "Python Developer"}

        @staticmethod
        def create_generation_job(_user_id):
            raise AssertionError("A saved roadmap must be detected before creating a job.")

    verifier = getattr(roadmap_routes, "mastery_verification_service", None)
    if verifier is not None:
        monkeypatch.setattr(
            verifier,
            "pending_for_active_goal",
            lambda _user_id: (_ for _ in ()).throw(AssertionError("Duplicate check must run first.")),
        )
    monkeypatch.setattr(roadmap_routes, "roadmap_service", FakeService)
    with pytest.raises(HTTPException) as raised:
        roadmap_routes._queue_roadmap_generation(BackgroundTasks(), "user-1")
    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "ROADMAP_ALREADY_EXISTS"


def test_running_job_is_not_scheduled_twice(monkeypatch):
    scheduled = []
    class FakeService:
        @staticmethod
        def get_existing_roadmap_for_active_goal(_user_id):
            return None

        @staticmethod
        def create_generation_job(_user_id):
            return {"job_id": "active-job", "status": "running", "goal_id": "goal-python", "reused": True}

        @staticmethod
        def run_generation_job(*args):
            pass

    _allow_route_mastery_gate(monkeypatch)
    monkeypatch.setattr(roadmap_routes, "roadmap_service", FakeService)
    tasks = BackgroundTasks()
    roadmap_routes._queue_roadmap_generation(tasks, "user-1")
    assert scheduled == []
    assert tasks.tasks == []
