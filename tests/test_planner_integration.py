"""_build_plan against a throw-away SQLite DB (no LLM)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db import models as m
from app.services import roadmap_service as rs


@pytest.fixture()
def session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(rs, "SessionLocal", Session)
    return Session


def seed(Session, mastery):
    db = Session()
    db.add(m.Goal(goal_id="g", goal_name="Goal"))
    db.add(m.User(user_id="u", username="u"))
    for sid in ("a", "b", "c"):
        db.add(m.Skill(skill_id=sid, skill_name=sid.upper()))
    db.flush()
    db.add(m.SkillDependency(skill_id="b", prerequisite_id="a"))
    db.add(m.SkillDependency(skill_id="c", prerequisite_id="b"))
    db.add(m.GoalSkill(goal_id="g", skill_id="c"))
    for sid, p in mastery.items():
        # Mastery is goal-scoped: the planner reads GoalUserSkill for this goal.
        db.add(m.GoalUserSkill(user_id="u", goal_id="g", skill_id=sid, proficiency=1, mastery_probability=p))
    db.commit(); db.close()


def test_build_plan_orders_and_filters(session_factory):
    seed(session_factory, {"a": 0.9, "b": 0.2})
    plan, phases = rs.roadmap_service._build_plan("u", "g")
    assert plan.skill_ids() == ["b", "c"] and plan.skipped == ["a"]
    assert phases[0]["skills"][0] == {"id": "b", "name": "B", "action": "learn"}


def test_build_plan_none_when_everything_mastered(session_factory):
    seed(session_factory, {"a": 0.95, "b": 0.95, "c": 0.95})
    assert rs.roadmap_service._build_plan("u", "g") is None


def test_build_plan_none_without_goal_skills(session_factory):
    db = session_factory(); db.add(m.Goal(goal_id="g", goal_name="G")); db.commit(); db.close()
    assert rs.roadmap_service._build_plan("u", "g") is None
