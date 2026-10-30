"""Regression tests for goal-specific curricula and roadmap skill boundaries."""
from types import SimpleNamespace

import pandas as pd

from app.services.curriculum_service import curriculum_service
from app.services.llm_service import LLMService


def test_every_seeded_goal_has_a_curriculum():
    goal_ids = set(curriculum_service._load())
    assert goal_ids == {str(i) for i in range(1, 26)}


def test_curriculum_skill_ids_exist_in_seeded_catalogue():
    from pathlib import Path
    from app.utils.config import settings

    known_ids = set(
        pd.read_csv(Path(settings.DATASET_DIR) / "skills.csv", dtype=str)["skill_id"].astype(str)
    )
    for goal_id, curriculum in curriculum_service._load().items():
        for phase in curriculum["phases"]:
            assert set(phase["skill_ids"]).issubset(known_ids), (goal_id, phase["title"])


def test_full_stack_curriculum_is_relevant_and_avoids_legacy_bad_prerequisites():
    catalogue = pd.read_csv(
        __import__("pathlib").Path(__import__("app.utils.config", fromlist=["settings"]).settings.DATASET_DIR) / "skills.csv",
        dtype=str,
    )
    skill_lookup = {
        str(row["skill_id"]): SimpleNamespace(skill_name=row["skill_name"])
        for _, row in catalogue.iterrows()
    }
    plan = curriculum_service.build_plan("6", skill_lookup, set())
    names = [skill["name"] for phase in plan for skill in phase["skills"]]

    assert "JavaScript Fundamentals" in names
    assert "React.js" in names
    assert "Node.js & Express" in names
    assert "RESTful API Development" in names
    assert "Database Programming" in names
    assert "Python Basics" not in names
    assert "Compiler Design" not in names
    assert "Regular Expressions" not in names
    assert len(plan) >= 5


def test_curriculum_removes_possessed_skills_and_empty_phases():
    lookup = {
        "66": SimpleNamespace(skill_name="HTML & CSS Fundamentals"),
        "67": SimpleNamespace(skill_name="Responsive Web Design"),
        "83": SimpleNamespace(skill_name="Browser DevTools"),
        "68": SimpleNamespace(skill_name="JavaScript Fundamentals"),
        "25": SimpleNamespace(skill_name="TypeScript"),
        "69": SimpleNamespace(skill_name="React.js"),
        "81": SimpleNamespace(skill_name="CSS Frameworks (Tailwind)"),
        "82": SimpleNamespace(skill_name="Testing Frontend Apps"),
        "71": SimpleNamespace(skill_name="Node.js & Express"),
        "74": SimpleNamespace(skill_name="RESTful API Development"),
        "14": SimpleNamespace(skill_name="API Design"),
        "15": SimpleNamespace(skill_name="Database Programming"),
        "36": SimpleNamespace(skill_name="NoSQL Databases"),
        "78": SimpleNamespace(skill_name="Authentication & Authorization"),
        "79": SimpleNamespace(skill_name="Web Security"),
        "75": SimpleNamespace(skill_name="Web Accessibility (a11y)"),
        "19": SimpleNamespace(skill_name="Software Architecture"),
        "93": SimpleNamespace(skill_name="CI/CD Pipelines"),
        "86": SimpleNamespace(skill_name="Cloud Fundamentals"),
        "104": SimpleNamespace(skill_name="Cloud Storage & CDN"),
        "80": SimpleNamespace(skill_name="Frontend Performance"),
    }
    plan = curriculum_service.build_plan("6", lookup, {"66", "67", "83"})
    assert plan[0]["title"] == "Modern JavaScript and TypeScript"
    assert all(skill["id"] not in {"66", "67", "83"} for p in plan for skill in p["skills"])
    assert all(p["skills"] for p in plan)


def test_merge_keeps_curated_phase_titles_and_skills():
    fixed = [
        {"index": 0, "title": "Web Foundations", "skills": [
            {"id": "66", "name": "HTML & CSS Fundamentals", "action": "learn"}
        ]}
    ]
    generated = {"phases": [{"index": 0, "title": "Compiler Design", "skills": ["Compiler Design"]}]}
    merged = LLMService.merge_elaboration_with_plan(fixed, generated)
    assert merged["phases"][0]["title"] == "Web Foundations"
    assert merged["phases"][0]["skills"] == ["HTML & CSS Fundamentals"]
