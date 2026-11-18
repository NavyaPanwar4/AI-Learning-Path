"""Regression coverage for profile-only skills and goal-scoped mastery."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db import models as m
from app.services import mastery_verification_service as verification_module
from app.services import gap_analysis as gap_module
from app.services.mastery_verification_service import MasteryVerificationService
from app.services.gap_analysis import GapAnalysisService


@pytest.fixture
def mastery_prior_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    db = Session()
    db.add(m.Goal(goal_id="prior-goal", goal_name="Prior Goal"))
    db.add(m.User(user_id="prior-user", username="prior-user", goal_id="prior-goal"))
    db.add(m.Skill(skill_id="skill-a", skill_name="Python"))
    db.add(m.Skill(skill_id="skill-b", skill_name="Git"))
    db.flush()
    db.add(m.GoalSkill(goal_id="prior-goal", skill_id="skill-a", importance=1))
    db.add(m.GoalSkill(goal_id="prior-goal", skill_id="skill-b", importance=1))
    # Profile membership only: this is not a goal-scoped BKT observation.
    db.add(m.UserSkill(
        user_id="prior-user", skill_id="skill-a", proficiency=1,
        mastery_probability=None, bkt_observations=0,
    ))
    db.commit()
    db.close()

    monkeypatch.setattr(verification_module, "SessionLocal", Session)
    monkeypatch.setattr(verification_module.curriculum_service, "has_curriculum", lambda _goal: False)
    monkeypatch.setattr(gap_module, "SessionLocal", Session)
    monkeypatch.setattr(gap_module.curriculum_service, "has_curriculum", lambda _goal: False)
    yield Session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_profile_skill_without_goal_bkt_state_is_not_verification_pending(mastery_prior_db):
    pending = MasteryVerificationService().list_pending("prior-user", "prior-goal")["pending_skills"]
    assert pending == []


def test_only_high_unverified_goal_scoped_bkt_state_requires_verification(mastery_prior_db):
    db = mastery_prior_db()
    db.add(m.GoalUserSkill(
        user_id="prior-user", goal_id="prior-goal", skill_id="skill-a",
        proficiency=1, mastery_probability=0.20, bkt_observations=0,
        verification_status="unverified",
    ))
    db.commit()
    service = MasteryVerificationService()
    assert service.list_pending("prior-user", "prior-goal")["pending_skills"] == []

    state = db.query(m.GoalUserSkill).filter_by(skill_id="skill-a").one()
    state.mastery_probability = 0.92
    state.bkt_observations = 6
    db.commit()
    pending = service.list_pending("prior-user", "prior-goal")["pending_skills"]
    assert [item["skill_id"] for item in pending] == ["skill-a"]
    assert pending[0]["mastery_pct"] == 92
    db.close()


def test_profile_only_skill_remains_in_gap_analysis_fallback(mastery_prior_db):
    items = GapAnalysisService()._get_ordered_missing_skill_records("prior-user")
    assert {item["id"] for item in items} == {"skill-a", "skill-b"}


def test_gap_analysis_skips_only_verified_high_mastery_skill(mastery_prior_db):
    db = mastery_prior_db()
    db.add(m.GoalUserSkill(
        user_id="prior-user", goal_id="prior-goal", skill_id="skill-a",
        proficiency=5, mastery_probability=0.95, bkt_observations=8,
        verification_status="unverified",
    ))
    db.commit()
    items = GapAnalysisService()._get_ordered_missing_skill_records("prior-user")
    assert "skill-a" in {item["id"] for item in items}

    state = db.query(m.GoalUserSkill).filter_by(skill_id="skill-a").one()
    state.verification_status = "verified"
    db.commit()
    items = GapAnalysisService()._get_ordered_missing_skill_records("prior-user")
    assert "skill-a" not in {item["id"] for item in items}
    db.close()


def test_curated_plan_omits_only_verified_high_mastery_skills(mastery_prior_db, monkeypatch):
    captured = {}
    monkeypatch.setattr(gap_module.curriculum_service, "build_plan", lambda goal_id, skills, mastered: captured.update({"mastered": set(mastered)}) or [])
    gap = GapAnalysisService()
    assert gap.get_curated_plan("prior-user") == []
    assert captured["mastered"] == set()

    db = mastery_prior_db()
    db.add(m.GoalUserSkill(
        user_id="prior-user", goal_id="prior-goal", skill_id="skill-a",
        proficiency=5, mastery_probability=0.95, bkt_observations=8,
        verification_status="verified",
    ))
    db.commit()
    db.close()
    gap.get_curated_plan("prior-user")
    assert captured["mastered"] == {"skill-a"}
