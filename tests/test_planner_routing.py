"""Which plan an uncurated goal gets: planner first, possession-based fallback as backup."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db import models as m
from app.services import roadmap_service as rs
from app.services.roadmap_service import RoadmapService
from app.utils.config import settings


@pytest.fixture()
def session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(rs, "SessionLocal", Session)
    return Session


def seed(Session, goal_mastery=None, recorded=()):
    db = Session()
    db.add(m.Goal(goal_id="g", goal_name="Goal"))
    db.add(m.User(user_id="u", username="u"))
    for sid in ("a", "b", "c"):
        db.add(m.Skill(skill_id=sid, skill_name=sid.upper()))
    db.flush()
    db.add(m.SkillDependency(skill_id="b", prerequisite_id="a"))
    db.add(m.SkillDependency(skill_id="c", prerequisite_id="b"))
    db.add(m.GoalSkill(goal_id="g", skill_id="c"))
    for sid in recorded:
        db.add(m.UserSkill(user_id="u", skill_id=sid, proficiency=1, mastery_probability=None))
    for sid, p in (goal_mastery or {}).items():
        db.add(m.GoalUserSkill(user_id="u", goal_id="g", skill_id=sid, proficiency=1, mastery_probability=p))
    db.commit(); db.close()


def test_recorded_skill_without_goal_state_counts_as_mastered(session_factory):
    seed(session_factory, recorded=["a"])
    plan, _ = rs.roadmap_service._build_plan("u", "g")
    assert plan.skill_ids() == ["b", "c"] and plan.skipped == ["a"]


def test_goal_scoped_mastery_overrides_recorded_skill(session_factory):
    # Recorded as known, but quiz evidence for this goal says it is weak.
    seed(session_factory, goal_mastery={"a": 0.3}, recorded=["a"])
    plan, phases = rs.roadmap_service._build_plan("u", "g")
    assert plan.skill_ids()[0] == "a"
    assert phases[0]["skills"][0]["action"] == "learn"


def test_weak_but_not_mastered_skill_is_review(session_factory):
    seed(session_factory, goal_mastery={"a": 0.9, "b": 0.6})
    plan, _ = rs.roadmap_service._build_plan("u", "g")
    actions = {i.skill_id: i.action for i in plan.items}
    assert actions == {"b": "review", "c": "learn"}


def test_prerequisite_depths_are_longest_chain():
    d = RoadmapService._prerequisite_depths(["a", "b", "c", "d"], [("a", "b"), ("b", "c"), ("a", "c")])
    assert d == {"a": 0, "b": 1, "c": 2, "d": 0}


def test_prerequisite_depths_tolerate_cycle():
    d = RoadmapService._prerequisite_depths(["a", "b"], [("a", "b"), ("b", "a")])
    assert d == {"a": 0, "b": 0}


def test_planner_used_by_default_for_uncurated_goal(session_factory, monkeypatch):
    seed(session_factory)
    monkeypatch.setattr(settings, "USE_PATH_PLANNER", True)
    planned, fallback, names = rs.roadmap_service._plan_for_uncurated_goal("u", "g")
    assert planned is not None and fallback is None and names == ["A", "B", "C"]


def test_fallback_used_when_planner_disabled(session_factory, monkeypatch):
    seed(session_factory)
    monkeypatch.setattr(settings, "USE_PATH_PLANNER", False)
    sentinel = [{"index": 0, "title": "T", "skills": [{"id": "a", "name": "A", "action": "learn"}]}]
    monkeypatch.setattr(rs.gap_analysis_service, "get_fallback_plan", lambda user_id: sentinel)
    planned, fallback, names = rs.roadmap_service._plan_for_uncurated_goal("u", "g")
    assert planned is None and fallback == sentinel and names == ["A"]


def test_fallback_used_when_planner_raises(session_factory, monkeypatch):
    seed(session_factory)
    monkeypatch.setattr(settings, "USE_PATH_PLANNER", True)
    monkeypatch.setattr(rs.roadmap_service, "_build_plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    sentinel = [{"index": 0, "title": "T", "skills": [{"id": "b", "name": "B", "action": "learn"}]}]
    monkeypatch.setattr(rs.gap_analysis_service, "get_fallback_plan", lambda user_id: sentinel)
    planned, fallback, names = rs.roadmap_service._plan_for_uncurated_goal("u", "g")
    assert planned is None and fallback == sentinel and names == ["B"]


def test_error_when_neither_plan_exists(session_factory, monkeypatch):
    seed(session_factory, recorded=["a", "b", "c"])
    monkeypatch.setattr(settings, "USE_PATH_PLANNER", True)
    monkeypatch.setattr(rs.gap_analysis_service, "get_fallback_plan", lambda user_id: None)
    with pytest.raises(ValueError):
        rs.roadmap_service._plan_for_uncurated_goal("u", "g")


def test_llm_first_proposal_is_validated_and_repairs_missing_prerequisites(session_factory, monkeypatch):
    seed(session_factory)
    monkeypatch.setattr(settings, "USE_LLM_FIRST_VALIDATED_ROADMAP", True)
    proposal = {"phases": [{"index": 0, "title": "Goal Skills", "duration": "1 week", "skills": [
        {"id": "c", "name": "C", "action": "learn"},
    ], "projects": []}]}
    monkeypatch.setattr(rs.llm_service, "generate_roadmap_proposal", lambda **kwargs: proposal)

    result = rs.roadmap_service._build_llm_first_plan("u", "g", "Goal", {"experience_level": "beginner"})

    assert result is not None
    assert result["repaired"] is True
    assert [skill["id"] for phase in result["plan_phases"] for skill in phase["skills"]] == ["a", "b", "c"]
    assert any("Inserted missing required skills" in issue for issue in result["issues"])


def test_curated_goal_llm_first_scope_does_not_import_external_prerequisites(session_factory, monkeypatch):
    """Curated goals use LLM-first phase design without legacy cross-domain expansion."""
    seed(session_factory)
    monkeypatch.setattr(settings, "USE_LLM_FIRST_VALIDATED_ROADMAP", True)
    captured = {}

    def fake_proposal(**kwargs):
        captured.update(kwargs)
        return {"phases": [{
            "index": 0,
            "title": "Goal Skill",
            "duration": "1 week",
            "skills": [{"id": "c", "name": "C", "action": "learn"}],
            "projects": [{"title": "C project", "description": "Practice C"}],
        }]}

    monkeypatch.setattr(rs.llm_service, "generate_roadmap_proposal", fake_proposal)
    monkeypatch.setattr(rs.curriculum_service, "get_skill_ids", lambda goal_id: ["c"])

    result = rs.roadmap_service._build_llm_first_plan(
        "u", "g", "Goal", {"experience_level": "beginner"},
        restrict_to_goal_skills=True,
    )

    assert result is not None
    assert [item["id"] for item in captured["candidate_skills"]] == ["c"]
    assert captured["prerequisite_edges"] == []
    assert [skill["id"] for phase in result["plan_phases"] for skill in phase["skills"]] == ["c"]


def test_curated_llm_first_uses_complete_curriculum_not_stale_goal_skill_mappings(session_factory, monkeypatch):
    """A stale GoalSkill table must not hide reviewed curriculum skills."""
    seed(session_factory)  # Only skill c is mapped in GoalSkill; a and b are missing there.
    captured = {}
    curated_plan = [{"index": 0, "title": "Foundations", "skills": [
        {"id": "a", "name": "A", "action": "learn"},
        {"id": "b", "name": "B", "action": "learn"},
        {"id": "c", "name": "C", "action": "learn"},
    ]}]

    def fake_proposal(**kwargs):
        captured.update(kwargs)
        return {"phases": [{"index": 0, "title": "Full curriculum", "duration": "1 week",
            "skills": [{"id": "c", "name": "C", "action": "learn"}], "projects": []}]}

    monkeypatch.setattr(rs.llm_service, "generate_roadmap_proposal", fake_proposal)
    monkeypatch.setattr(rs.curriculum_service, "get_skill_ids", lambda goal_id: ["a", "b", "c"])
    result = rs.roadmap_service._build_llm_first_plan(
        "u", "g", "Goal", {"experience_level": "beginner"},
        restrict_to_goal_skills=True,
    )

    assert result is not None
    assert captured["target_skill_ids"] == ["a", "b", "c"]
    assert {item["id"] for item in captured["candidate_skills"]} == {"a", "b", "c"}
    assert [item["id"] for phase in result["plan_phases"] for item in phase["skills"]] == ["a", "b", "c"]


def test_uncurated_goal_llm_first_scope_keeps_prerequisite_closure(session_factory, monkeypatch):
    seed(session_factory)
    captured = {}

    def fake_proposal(**kwargs):
        captured.update(kwargs)
        return {"phases": [{
            "index": 0,
            "title": "Foundations",
            "duration": "1 week",
            "skills": [
                {"id": "a", "name": "A", "action": "learn"},
                {"id": "b", "name": "B", "action": "learn"},
                {"id": "c", "name": "C", "action": "learn"},
            ],
            "projects": [],
        }]}

    monkeypatch.setattr(rs.llm_service, "generate_roadmap_proposal", fake_proposal)
    result = rs.roadmap_service._build_llm_first_plan(
        "u", "g", "Goal", {"experience_level": "beginner"},
        restrict_to_goal_skills=False,
    )

    assert result is not None
    assert {item["id"] for item in captured["candidate_skills"]} == {"a", "b", "c"}
    assert [skill["id"] for phase in result["plan_phases"] for skill in phase["skills"]] == ["a", "b", "c"]


def test_curated_goal_uses_llm_first_path_when_enabled(session_factory, monkeypatch):
    """The new generation route applies to curated goals too, without widening scope."""
    seed(session_factory)
    monkeypatch.setattr(settings, "USE_LLM_FIRST_VALIDATED_ROADMAP", True)
    monkeypatch.setattr(
        rs.auth_service,
        "get_user_by_id",
        lambda user_id: {
            "goal_id": "g",
            "experience_level": "beginner",
            "available_hours_per_week": 6,
            "learning_style": "visual",
        },
    )
    curated_plan = [{
        "index": 0,
        "title": "Reviewed phase",
        "skills": [{"id": "c", "name": "C", "action": "learn"}],
    }]
    monkeypatch.setattr(rs.gap_analysis_service, "get_curated_plan", lambda user_id: curated_plan)
    monkeypatch.setattr(rs.curriculum_service, "get_skill_ids", lambda goal_id: ["c"])
    captured = {}

    def fake_proposal(**kwargs):
        captured.update(kwargs)
        return {"phases": [{
            "index": 0,
            "title": "LLM-first phase",
            "duration": "1 week",
            "skills": [{"id": "c", "name": "C", "action": "learn"}],
            "projects": [{"title": "C mini-project", "description": "Practice C"}],
        }]}

    monkeypatch.setattr(rs.llm_service, "generate_roadmap_proposal", fake_proposal)
    monkeypatch.setattr(rs.web_search_service, "search_courses_for_plan", lambda plan: {})
    monkeypatch.setattr(rs.activity_service, "log_activity", lambda *args, **kwargs: None)

    roadmap = rs.roadmap_service.generate_personalized_roadmap("u")

    assert captured["target_skill_ids"] == ["c"]
    assert [entry["id"] for entry in captured["candidate_skills"]] == ["c"]
    assert roadmap["phases"][0]["title"] == "LLM-first phase"
    assert roadmap["phases"][0]["projects"][0]["title"] == "C mini-project"
