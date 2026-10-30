"""Integration-facing tests for LLM proposal generation and safe merging."""
from app.services.llm_service import LLMService, ROADMAP_PROPOSAL_SCHEMA


def test_proposal_generation_uses_structured_output(monkeypatch):
    service = LLMService()
    called = {}
    result = {"phases": [{
        "index": 0,
        "title": "Foundations",
        "duration": "1 week",
        "skills": [{"id": "py", "name": "Python", "action": "learn"}],
        "projects": [{"title": "Script", "description": "Build a small script"}],
    }]}

    def fake_generate_json(prompt, **kwargs):
        called["prompt"] = prompt
        called.update(kwargs)
        return result

    monkeypatch.setattr(service, "_generate_json", fake_generate_json)
    proposal = service.generate_roadmap_proposal(
        goal_name="Data Analyst",
        learner={"experience_level": "beginner", "available_hours_per_week": 6},
        target_skill_ids=["py"],
        candidate_skills=[{"id": "py", "name": "Python"}],
        prerequisite_edges=[],
        mastery_by_skill={"py": 0.1},
    )
    assert proposal == result
    assert called["schema"] == ROADMAP_PROPOSAL_SCHEMA
    assert called["schema_name"] == "roadmap_proposal"
    assert "propose the roadmap" in called["prompt"].lower()
    assert "MASTERY BY SKILL ID" in called["prompt"]


def test_merge_uses_validated_skills_and_preserves_proposal_metadata():
    proposal = {"phases": [{
        "index": 0,
        "title": "Foundation",
        "duration": "2 weeks",
        "skills": [{"id": "invented", "name": "Invented skill", "action": "learn"}],
        "projects": [{"title": "Project", "description": "Use Python"}],
    }]}
    validated = [{"index": 0, "title": "Foundation", "skills": [
        {"id": "py", "name": "Python", "action": "learn"},
    ]}]
    merged = LLMService.merge_proposal_with_validated_plan(proposal, validated)
    phase = merged["phases"][0]
    assert phase["skills"] == ["Python"]
    assert phase["skill_ids"] == ["py"]
    assert phase["duration"] == "2 weeks"
    assert phase["projects"][0]["title"] == "Project"
    assert "resources" not in phase

def test_merge_preserves_projects_when_validation_normalizes_one_based_indices():
    proposal = {"phases": [
        {"index": 1, "title": "Foundations", "duration": "1 week",
         "skills": [{"id": "a", "name": "Python"}],
         "projects": [{"title": "CLI Calculator", "description": "Use Python basics"}]},
        {"index": 2, "title": "Data Preparation", "duration": "2 weeks",
         "skills": [{"id": "b", "name": "NumPy"}],
         "projects": [{"title": "Array Analyzer", "description": "Analyze a dataset"}]},
    ]}
    validated = [
        {"index": 0, "title": "Foundations", "skills": [
            {"id": "a", "name": "Python", "action": "learn"},
        ]},
        {"index": 1, "title": "Data Preparation", "skills": [
            {"id": "b", "name": "NumPy", "action": "learn"},
        ]},
    ]

    merged = LLMService.merge_proposal_with_validated_plan(proposal, validated)

    assert merged["phases"][0]["projects"][0]["title"] == "CLI Calculator"
    assert merged["phases"][1]["projects"][0]["title"] == "Array Analyzer"
    assert merged["phases"][0]["duration"] == "1 week"
    assert merged["phases"][1]["duration"] == "2 weeks"
