"""Tests for curriculum source-of-truth and the cleaned seeded skill graph."""
import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "dataset"


def read_csv(name):
    with (DATASET / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_graph():
    rows = read_csv("skill_dependencies.csv")
    return [(str(row["skill_id"]), str(row["prerequisite_skill_id"])) for row in rows]


def test_goal_skill_csv_matches_curriculum_without_duplicates():
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))
    goals = {row["goal_id"] for row in read_csv("goals.csv")}
    mappings = read_csv("goal_skills.csv")

    assert set(curricula) == goals
    mapped = defaultdict(list)
    for row in mappings:
        mapped[row["goal_id"]].append(row["skill_id"])

    for goal_id, definition in curricula.items():
        expected = []
        for phase in definition["phases"]:
            expected.extend(str(skill_id) for skill_id in phase["skill_ids"])
        expected_unique = list(dict.fromkeys(expected))
        assert mapped[goal_id] == expected_unique
        assert len(mapped[goal_id]) == len(set(mapped[goal_id]))


def test_all_curated_skill_ids_exist_and_are_not_repeated_within_a_curriculum():
    skills = {row["skill_id"] for row in read_csv("skills.csv")}
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))

    for goal_id, definition in curricula.items():
        seen = set()
        for phase in definition["phases"]:
            assert phase["skill_ids"], (goal_id, phase["title"])
            for raw_id in phase["skill_ids"]:
                skill_id = str(raw_id)
                assert skill_id in skills, (goal_id, phase["title"], skill_id)
                assert skill_id not in seen, (goal_id, skill_id)
                seen.add(skill_id)


def test_dependency_graph_references_known_skills_and_is_acyclic():
    skills = {row["skill_id"] for row in read_csv("skills.csv")}
    edges = load_graph()
    prereq_map = defaultdict(list)

    for child, prerequisite in edges:
        assert child in skills
        assert prerequisite in skills
        assert child != prerequisite
        prereq_map[child].append(prerequisite)

    state = {}

    def visit(node):
        current = state.get(node, 0)
        assert current != 1, f"Dependency cycle includes skill {node}"
        if current == 2:
            return
        state[node] = 1
        for prerequisite in prereq_map.get(node, []):
            visit(prerequisite)
        state[node] = 2

    for skill_id in skills:
        visit(skill_id)


def test_known_bad_cross_domain_edges_are_removed():
    edges = set(load_graph())
    # skill_dependencies.csv uses (dependent skill, prerequisite skill).
    forbidden = {
        ("68", "15"),   # JavaScript Fundamentals <- Database Programming
        ("67", "17"),   # Responsive Web Design <- Compiler Design
        ("71", "11"),   # Node.js & Express <- Regular Expressions
        ("80", "1"),    # Frontend Performance <- Python Basics
        ("48", "44"),   # Decision Trees <- Business Intelligence
        ("57", "25"),   # Transfer Learning <- TypeScript
    }
    assert not (edges & forbidden)
    # JavaScript is a language foundation; HTML/CSS should not be forced as
    # a prerequisite for backend JavaScript/Node work.
    assert not any(child == "68" for child, _ in edges)
    assert ("69", "68") in edges
    assert ("71", "68") in edges
    assert ("72", "69") in edges
    assert ("72", "71") in edges


def test_goal_six_curriculum_is_full_stack_and_domain_coherent():
    skills = {row["skill_id"]: row["skill_name"] for row in read_csv("skills.csv")}
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))
    phases = curricula["6"]["phases"]
    names = [[skills[str(sid)] for sid in phase["skill_ids"]] for phase in phases]
    all_names = [name for phase in names for name in phase]

    assert len(phases) >= 5
    for required in (
        "HTML & CSS Fundamentals",
        "JavaScript Fundamentals",
        "TypeScript",
        "React.js",
        "Node.js & Express",
        "Next.js",
        "RESTful API Development",
        "Database Programming",
        "Authentication & Authorization",
        "CI/CD Pipelines",
    ):
        assert required in all_names
    for unrelated in ("Python Basics", "Compiler Design", "Regular Expressions", "Java Programming"):
        assert unrelated not in all_names


def test_curriculum_does_not_duplicate_combinatorics_or_use_duplicate_cloud_security_skill():
    skills = {row["skill_id"]: row["skill_name"] for row in read_csv("skills.csv")}
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))
    math_ids = [str(sid) for phase in curricula["19"]["phases"] for sid in phase["skill_ids"]]
    security_names = [
        skills[str(sid)]
        for phase in curricula["13"]["phases"]
        for sid in phase["skill_ids"]
    ]
    assert math_ids.count("145") == 1
    assert "Cloud Security2" not in security_names
    assert "Cloud Security" in security_names


def test_ml_engineer_phases_are_focused_and_transfer_learning_is_not_in_mlops():
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))
    skills = {row["skill_id"]: row["skill_name"] for row in read_csv("skills.csv")}
    phases = curricula["11"]["phases"]
    by_title = {p["title"]: [skills[str(i)] for i in p["skill_ids"]] for p in phases}
    assert "Transfer Learning" not in by_title["Production ML and MLOps"]
    assert by_title["Production ML and MLOps"] == ["MLOps", "Containerization with Docker", "CI/CD Pipelines"]
    assert "Transfer Learning" in by_title["Neural Networks, Deep Learning and Transfer Learning"]


MAX_ROADMAP_PHASES = 6


def test_no_curriculum_has_more_than_six_phases_or_an_overloaded_phase():
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))
    hours = {row["skill_id"]: float(row["estimated_learning_hours"] or 0) for row in read_csv("skills.csv")}
    for goal_id, definition in curricula.items():
        phases = definition["phases"]
        assert len(phases) <= MAX_ROADMAP_PHASES, (goal_id, len(phases))
        for phase in phases:
            assert len(phase["skill_ids"]) <= 6, (goal_id, phase["title"])


def test_full_stack_curated_skill_scope_includes_nextjs():
    """The Full Stack curriculum explicitly covers the major web stack skills."""
    curricula = json.loads((DATASET / "goal_curricula.json").read_text(encoding="utf-8"))
    skills = {row["skill_id"]: row["skill_name"] for row in read_csv("skills.csv")}
    phases = curricula["6"]["phases"]
    names = [skills[str(skill_id)] for phase in phases for skill_id in phase["skill_ids"]]
    for required in (
        "HTML & CSS Fundamentals",
        "JavaScript Fundamentals",
        "React.js",
        "Node.js & Express",
        "Next.js",
        "RESTful API Development",
        "Database Programming",
    ):
        assert required in names


def test_curriculum_service_get_skill_ids_uses_full_scope():
    from app.services.curriculum_service import CurriculumService

    service = CurriculumService(str(DATASET / "goal_curricula.json"))
    full_stack_ids = service.get_skill_ids("6")
    skill_names = {row["skill_id"]: row["skill_name"] for row in read_csv("skills.csv")}
    names = [skill_names[skill_id] for skill_id in full_stack_ids]
    for required in (
        "HTML & CSS Fundamentals",
        "JavaScript Fundamentals",
        "React.js",
        "Node.js & Express",
        "Next.js",
    ):
        assert required in names
