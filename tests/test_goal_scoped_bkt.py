"""Integration coverage for no aggregate fallback and goal-isolated mastery."""
import sys
import types

# These services are imported by SkillExtractionService but aren't exercised
# by these database-only tests; allow tests to run in a minimal environment.
try:
    import sentence_transformers  # noqa: F401
except ModuleNotFoundError:
    embeddings_stub = types.ModuleType("app.services.embeddings_service")
    embeddings_stub.embeddings_service = object()
    sys.modules.setdefault("app.services.embeddings_service", embeddings_stub)
try:
    import groq  # noqa: F401
except ModuleNotFoundError:
    # llm_service may use other optional providers; replace only if absent.
    llm_stub = types.ModuleType("app.services.llm_service")
    llm_stub.llm_service = object()
    sys.modules.setdefault("app.services.llm_service", llm_stub)

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import GoalUserSkill, ReviewSchedule, Skill, User
from app.services.skill_extraction import SkillExtractionService


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    session.add(User(user_id="user-1", username="learner", email="learner@example.test", hashed_password="test"))
    session.add(Skill(skill_id="skill-python", skill_name="Python", category="Programming"))
    session.commit()
    return session, engine


def test_aggregate_score_without_question_evidence_does_not_update_mastery():
    db, engine = _session()
    try:
        service = SkillExtractionService()
        result = service.update_proficiency_from_quiz(
            "user-1", ["Python"], score_pct=100, db=db,
            question_results=[], goal_id="goal-a",
        )
        assert result == []
        assert db.query(GoalUserSkill).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_mastery_is_stored_separately_per_goal():
    db, engine = _session()
    try:
        service = SkillExtractionService()
        service.update_proficiency_from_quiz(
            "user-1", ["Python"], score_pct=100, db=db,
            question_results=[{"skill_name": "Python", "is_correct": True}],
            goal_id="goal-a",
        )
        service.update_proficiency_from_quiz(
            "user-1", ["Python"], score_pct=0, db=db,
            question_results=[{"skill_name": "Python", "is_correct": False}],
            goal_id="goal-b",
        )
        db.commit()
        rows = db.query(GoalUserSkill).order_by(GoalUserSkill.goal_id).all()
        assert len(rows) == 2
        assert rows[0].goal_id == "goal-a"
        assert rows[1].goal_id == "goal-b"
        assert rows[0].mastery_probability > rows[1].mastery_probability
        assert rows[0].bkt_observations == 1
        assert rows[1].bkt_observations == 1
    finally:
        db.close()
        engine.dispose()


def test_review_scheduling_uses_goal_mastery_and_never_score_fallback(monkeypatch):
    import app.services.learning_features_service as lfs_module
    from app.services.learning_features_service import learning_features_service

    db, engine = _session()
    try:
        monkeypatch.setattr(lfs_module, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False))
        # A high aggregate score cannot create a schedule without a per-goal
        # BKT state produced by labelled question evidence.
        learning_features_service.schedule_review("user-1", "goal-empty", ["Python"], 100)
        assert db.query(ReviewSchedule).count() == 0

        db.add_all([
            GoalUserSkill(user_id="user-1", goal_id="goal-low", skill_id="skill-python", proficiency=1, mastery_probability=0.2, bkt_observations=1),
            GoalUserSkill(user_id="user-1", goal_id="goal-high", skill_id="skill-python", proficiency=5, mastery_probability=0.9, bkt_observations=1),
        ])
        db.commit()
        learning_features_service.schedule_review("user-1", "goal-low", ["Python"], 50)
        learning_features_service.schedule_review("user-1", "goal-high", ["Python"], 50)

        schedules = {row.goal_id: row for row in db.query(ReviewSchedule).all()}
        assert set(schedules) == {"goal-low", "goal-high"}
        assert schedules["goal-low"].interval_days < schedules["goal-high"].interval_days

        # The queue is goal-scoped too: a due skill under one goal does not
        # inherit another goal's review timestamp or mastery probability.
        old = datetime.utcnow() - timedelta(days=10)
        schedules["goal-low"].created_at = old
        schedules["goal-low"].due_at = old + timedelta(days=schedules["goal-low"].interval_days)
        db.commit()
        db.close()
        queue_low = learning_features_service.review_queue("user-1", "goal-low")
        queue_high = learning_features_service.review_queue("user-1", "goal-high")
        assert [item["goal_id"] for item in queue_low] == ["goal-low"]
        assert queue_high == []
    finally:
        try:
            db.close()
        finally:
            engine.dispose()


def test_complete_roadmap_initializes_prior_without_claiming_mastery(monkeypatch):
    import importlib

    # roadmap_service imports auth_service, whose optional password package is
    # irrelevant to complete_roadmap; isolate that external dependency here.
    if "app.services.auth_service" not in sys.modules:
        auth_stub = types.ModuleType("app.services.auth_service")
        auth_stub.auth_service = object()
        sys.modules["app.services.auth_service"] = auth_stub
    roadmap_module = importlib.import_module("app.services.roadmap_service")
    from app.db.models import Roadmap

    db, engine = _session()
    db.add(Roadmap(
        user_id="user-1",
        goal_id="goal-complete",
        goal_name="Learn Python",
        data='{"phases":[{"title":"Foundations","skills":["Python"],"completed":true}],"is_complete":false}',
        is_complete=False,
    ))
    db.commit()
    db.close()
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(roadmap_module, "SessionLocal", factory)
    monkeypatch.setattr(roadmap_module.activity_service, "log_activity", lambda *_args, **_kwargs: None)
    try:
        result = roadmap_module.roadmap_service.complete_roadmap("user-1", "goal-complete")
        assert result and result["is_complete"] is True
        verify = factory()
        try:
            row = verify.query(GoalUserSkill).filter(
                GoalUserSkill.user_id == "user-1",
                GoalUserSkill.goal_id == "goal-complete",
                GoalUserSkill.skill_id == "skill-python",
            ).one()
            assert row.mastery_probability == 0.2
            assert row.bkt_observations == 0
        finally:
            verify.close()
    finally:
        engine.dispose()
