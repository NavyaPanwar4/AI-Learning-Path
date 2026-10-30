"""Tests for the plan-then-elaborate helpers (no network, no LLM)."""
from app.services.llm_service import LLMService

PLAN = [
    {"index": 0, "skills": [{"id": "1", "name": "Python Basics", "action": "learn"},
                            {"id": "2", "name": "Statistics", "action": "review"}]},
    {"index": 1, "skills": [{"id": "3", "name": "Machine Learning", "action": "learn"}]},
]


def test_merge_enforces_plan_even_if_llm_reorders_or_invents():
    llm = {"phases": [
        {"index": 1, "title": "ML", "duration": "3 weeks",
         "skills": [{"id": "3", "name": "Machine Learning"}, {"id": "99", "name": "Invented"}]},
        {"index": 0, "title": "Foundations", "duration": "2 weeks",
         "skills": [{"id": "2", "name": "Statistics"}, {"id": "1", "name": "Python Basics"}]},
    ]}
    out = LLMService.merge_elaboration_with_plan(PLAN, llm)
    assert [p["skills"] for p in out["phases"]] == [["Python Basics", "Statistics"], ["Machine Learning"]]
    assert [p["skill_ids"] for p in out["phases"]] == [["1", "2"], ["3"]]
    assert out["phases"][0]["title"] == "Foundations"
    assert out["adherence"] == 0.0           # both phases deviated


def test_merge_full_adherence_and_titles():
    llm = {"phases": [
        {"index": 0, "title": "A", "duration": "1 week", "skills": ["Python Basics", "Statistics"]},
        {"index": 1, "title": "B", "duration": "2 weeks", "skills": [{"id": "3"}]},
    ]}
    out = LLMService.merge_elaboration_with_plan(PLAN, llm)
    assert out["adherence"] == 1.0


def test_merge_handles_garbage():
    for bad in (None, {}, {"phases": "x"}, {"phases": [1, 2]}):
        out = LLMService.merge_elaboration_with_plan(PLAN, bad)
        assert len(out["phases"]) == 2
        assert out["phases"][0]["title"] == "Phase 1"
        assert out["adherence"] == 0.0


def test_prompt_mentions_fixed_plan_and_phase_count():
    prompt = LLMService.build_plan_elaboration_prompt(PLAN, goal_name="ML Engineer", include_extras=False)
    assert "Return exactly 2 phases" in prompt and "FIXED PLAN" in prompt
    assert "VERIFIED RESOURCE LIST" not in prompt


def test_generic_roadmap_scope_guard_removes_invented_skills_and_restores_missing_ones():
    allowed = ["JavaScript Fundamentals", "TypeScript", "React.js", "Node.js & Express"]
    generated = [
        {"title": "Random Python Phase", "skills": ["Python Basics", "React JS"]},
        {"title": "Backend", "skills": ["Node.js", "Compiler Design"]},
    ]
    phases = LLMService._enforce_generated_skill_scope(generated, allowed)
    assert [skill for phase in phases for skill in phase["skills"]] == allowed
    assert len(phases) == 2
    assert all("Compiler Design" not in phase["skills"] for phase in phases)
    assert all("Random Python Phase" not in phase["title"] for phase in phases)


def test_generic_roadmap_scope_guard_does_not_force_five_phases():
    phases = LLMService._enforce_generated_skill_scope([], ["React.js", "Node.js & Express"])
    assert len(phases) == 1
    assert phases[0]["skills"] == ["React.js", "Node.js & Express"]
