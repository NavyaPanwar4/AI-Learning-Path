"""Database-backed tests for mastery verification quiz lifecycle."""
import json
from types import SimpleNamespace
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import Goal, GoalSkill, GoalUserSkill, Skill, User
verification_module = importlib.import_module("app.services.mastery_verification_service")
MasteryVerificationService = verification_module.MasteryVerificationService


@pytest.fixture

def verification_context(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    db.add(Goal(goal_id="goal-1", goal_name="Python Developer"))
    db.add(User(user_id="user-1", username="learner", email="learner@example.com", goal_id="goal-1"))
    db.add(Skill(skill_id="skill-python", skill_name="Python", category="Programming"))
    db.flush()
    db.add(GoalSkill(goal_id="goal-1", skill_id="skill-python", importance=1))
    db.add(GoalUserSkill(
        user_id="user-1", goal_id="goal-1", skill_id="skill-python",
        mastery_probability=0.92, proficiency=5, bkt_observations=6,
        verification_status="unverified",
    ))
    db.commit()
    db.close()

    monkeypatch.setattr(verification_module, "SessionLocal", TestingSession)
    questions = [
        {
            "question": f"Question on {aspect}?",
            "options": ["A", "B", "C", "D"],
            "correct_index": 1,
            "explanation": "Because B is correct.",
            "skill": "Python",
            "aspect": aspect,
        }
        for aspect in ("core_concepts", "practical_application", "debugging", "edge_cases", "best_practices")
    ]
    monkeypatch.setattr(verification_module, "llm_service", SimpleNamespace(
        generate_skill_verification_quiz=lambda name: questions
    ))
    yield TestingSession
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _answers(quiz, correct_count):
    result = []
    for index, question in enumerate(quiz["questions"]):
        selected = 1 if index < correct_count else 0
        result.append(SimpleNamespace(question_id=question["question_id"], selected_index=selected))
    return result


def test_high_bkt_skill_is_pending_until_passed(verification_context):
    service = MasteryVerificationService()
    pending = service.list_pending("user-1", "goal-1")["pending_skills"]
    assert [item["skill_id"] for item in pending] == ["skill-python"]

    quiz = service.issue_quiz("user-1", "goal-1", "skill-python")
    assert len(quiz["questions"]) == 5
    assert {question["aspect"] for question in quiz["questions"]} == {
        "core_concepts", "practical_application", "debugging", "edge_cases", "best_practices"
    }
    assert all("correct_index" not in question for question in quiz["questions"])

    result = service.submit_quiz(
        "user-1", "goal-1", "skill-python", quiz["quiz_id"], _answers(quiz, 4)
    )
    assert result["passed"] is True
    assert result["score_pct"] == 80
    assert result["verification_status"] == "verified"
    assert service.list_pending("user-1", "goal-1")["pending_skills"] == []

    db = verification_context()
    state = db.query(GoalUserSkill).filter_by(user_id="user-1", goal_id="goal-1", skill_id="skill-python").one()
    assert state.verification_attempts == 1
    assert state.bkt_observations == 6  # Passing verification preserves the existing BKT estimate.
    assert state.mastery_probability == pytest.approx(0.92)
    assert result["bkt_updates"] == []
    assert state.verified_at is not None
    db.close()


def test_failed_verification_updates_bkt_and_does_not_mark_verified(verification_context):
    service = MasteryVerificationService()
    quiz = service.issue_quiz("user-1", "goal-1", "skill-python")
    result = service.submit_quiz(
        "user-1", "goal-1", "skill-python", quiz["quiz_id"], _answers(quiz, 2)
    )
    assert result["passed"] is False
    assert result["score_pct"] == 40
    assert result["verification_status"] == "failed"
    assert len(result["bkt_updates"]) == 1
    assert result["bkt_updates"][0]["observations_applied"] == 5
    assert service.list_pending("user-1", "goal-1")["pending_skills"] == []

    db = verification_context()
    state = db.query(GoalUserSkill).filter_by(user_id="user-1", goal_id="goal-1", skill_id="skill-python").one()
    assert state.bkt_observations == 11
    assert state.verification_status == "failed"
    assert state.last_verification_score == 40
    assert state.verified_at is None
    db.close()


def test_verification_scope_is_bound_to_active_goal(verification_context):
    service = MasteryVerificationService()
    from app.services.mastery_verification_service import MasteryVerificationError
    with pytest.raises(MasteryVerificationError) as exc:
        service.list_pending("user-1", "another-users-goal")
    assert exc.value.status_code == 404
