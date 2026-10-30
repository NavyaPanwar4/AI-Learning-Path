"""Tests for the LLM-first roadmap validation and repair layer."""
import pytest

from app.services.path_planner import SkillGraph, SkillNode
from app.services.roadmap_validator import validate_llm_roadmap_proposal


@pytest.fixture

def graph():
    return SkillGraph(
        [
            SkillNode("a", "Python Fundamentals"),
            SkillNode("b", "NumPy"),
            SkillNode("c", "Machine Learning"),
            SkillNode("x", "Unrelated Cloud Security"),
        ],
        [("a", "b"), ("b", "c")],
    )


def test_valid_proposal_keeps_llm_phase_structure(graph):
    result = validate_llm_roadmap_proposal(
        {
            "phases": [
                {"index": 0, "title": "Foundations", "skills": [
                    {"id": "a", "name": "Python Fundamentals", "action": "learn"},
                ]},
                {"index": 1, "title": "ML Basics", "skills": [
                    {"id": "b", "name": "NumPy", "action": "review"},
                    {"id": "c", "name": "Machine Learning", "action": "learn"},
                ]},
            ]
        },
        graph,
        ["c"],
        {"a": 0.2, "b": 0.6, "c": 0.1},
    )
    assert result["repaired"] is False
    assert [s["id"] for p in result["plan_phases"] for s in p["skills"]] == ["a", "b", "c"]
    assert [p["title"] for p in result["plan_phases"]] == ["Foundations", "ML Basics"]
    actions = {s["id"]: s["action"] for p in result["plan_phases"] for s in p["skills"]}
    assert actions == {"a": "learn", "b": "review", "c": "learn"}


def test_missing_prerequisite_is_inserted_before_dependent(graph):
    result = validate_llm_roadmap_proposal(
        {"phases": [{"index": 0, "title": "Machine Learning", "skills": [
            {"id": "c", "name": "Machine Learning", "action": "learn"},
        ]}]},
        graph,
        ["c"],
        {},
    )
    assert result["repaired"] is True
    assert [s["id"] for p in result["plan_phases"] for s in p["skills"]] == ["a", "b", "c"]
    assert any("Inserted missing required skills" in issue for issue in result["issues"])


def test_out_of_scope_and_mastered_skills_are_removed(graph):
    result = validate_llm_roadmap_proposal(
        {"phases": [{"index": 0, "title": "Proposed", "skills": [
            {"id": "x", "name": "Unrelated Cloud Security", "action": "learn"},
            {"id": "a", "name": "Python Fundamentals", "action": "learn"},
            {"id": "a", "name": "Python Fundamentals", "action": "learn"},
            {"id": "c", "name": "Machine Learning", "action": "learn"},
        ]}]},
        graph,
        ["c"],
        {"a": 0.95, "b": 0.1, "c": 0.1},
    )
    flat = [s["id"] for p in result["plan_phases"] for s in p["skills"]]
    assert result["repaired"] is True
    assert "x" not in flat
    assert "a" not in flat
    assert flat == ["b", "c"]
    assert len(flat) == len(set(flat))


def test_name_only_response_is_normalized_to_catalogue_id(graph):
    result = validate_llm_roadmap_proposal(
        {"phases": [{"index": 0, "title": "Sequence", "skills": [
            {"name": "Python Fundamentals", "action": "learn"},
            {"name": "NumPy", "action": "learn"},
            {"name": "Machine Learning", "action": "learn"},
        ]}]},
        graph,
        ["c"],
        {},
    )
    assert [s["id"] for p in result["plan_phases"] for s in p["skills"]] == ["a", "b", "c"]

def test_one_based_phase_indices_are_normalized_without_structural_repair(graph):
    result = validate_llm_roadmap_proposal(
        {"phases": [
            {"index": 1, "title": "Foundations", "skills": [
                {"id": "a", "name": "Python Fundamentals", "action": "learn"},
            ]},
            {"index": 2, "title": "Data Preparation", "skills": [
                {"id": "b", "name": "NumPy", "action": "learn"},
            ]},
            {"index": 3, "title": "Model Building", "skills": [
                {"id": "c", "name": "Machine Learning", "action": "learn"},
            ]},
        ]},
        graph,
        ["c"],
        {},
    )

    assert result["repaired"] is False
    assert [phase["index"] for phase in result["plan_phases"]] == [0, 1, 2]
    assert [phase["title"] for phase in result["plan_phases"]] == [
        "Foundations", "Data Preparation", "Model Building"
    ]
    assert any("Normalized non-sequential phase index" in issue for issue in result["issues"])
