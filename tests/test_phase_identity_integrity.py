from types import SimpleNamespace

from app.services.phase_identity import (
    backfill_attempt_phase_ids,
    ensure_phase_ids,
    preserve_phase_identity,
    reconcile_attempts_to_phase_order,
    shift_attempt_indices_after_insertion,
)


def test_same_title_with_different_skills_does_not_inherit_state():
    previous = {"phases": [{"title": "Foundations", "skills": ["Python"], "completed": True, "ai_notes": {"overview": "old"}}]}
    generated = {"phases": [{"title": "Foundations", "skills": ["SQL"], "completed": False}]}
    result = preserve_phase_identity(previous, generated)
    assert result["phases"][0]["completed"] is False
    assert "ai_notes" not in result["phases"][0]
    assert result["phases"][0]["phase_id"] != previous["phases"][0]["phase_id"]


def test_reordered_phases_keep_ids_completion_and_notes_by_skill_identity():
    previous = {"phases": [
        {"title": "Basics", "skills": ["Python", "Variables"], "completed": True, "ai_notes": {"overview": "python notes"}},
        {"title": "Data", "skills": ["SQL", "Joins"], "completed": False},
    ]}
    ensure_phase_ids(previous)
    python_id = previous["phases"][0]["phase_id"]
    generated = {"phases": [
        {"title": "Data", "skills": ["SQL", "Joins"], "completed": False},
        {"title": "Python Foundations", "skills": ["Variables", "Python"], "completed": False},
    ]}
    result = preserve_phase_identity(previous, generated)
    assert result["phases"][1]["phase_id"] == python_id
    assert result["phases"][1]["completed"] is True
    assert result["phases"][1]["ai_notes"] == {"overview": "python notes"}


def test_duplicate_titles_are_matched_one_to_one_by_skills():
    previous = {"phases": [
        {"title": "Practice", "skills": ["Git"], "completed": True},
        {"title": "Practice", "skills": ["Shell"], "completed": False},
    ]}
    ensure_phase_ids(previous)
    ids = [p["phase_id"] for p in previous["phases"]]
    generated = {"phases": [
        {"title": "Practice", "skills": ["Shell"]},
        {"title": "Practice", "skills": ["Git"]},
    ]}
    result = preserve_phase_identity(previous, generated)
    assert result["phases"][0]["phase_id"] == ids[1]
    assert result["phases"][1]["phase_id"] == ids[0]


def test_remedial_insertion_shifts_indices_but_keeps_attempt_identity_and_history_attachment():
    phases = [{"phase_id": "a"}, {"phase_id": "b"}, {"phase_id": "c"}]
    attempts = [
        SimpleNamespace(id=1, phase_index=0, phase_id=None),
        SimpleNamespace(id=2, phase_index=2, phase_id=None),
    ]
    # QuizQuestionHistory references attempt_id, not phase_index: no history row needs re-keying.
    history = [{"attempt_id": 2, "question_index": 0, "is_correct": True}]
    review_schedule = SimpleNamespace(user_id="u", goal_id="g", skill_name="SQL", due_at="2030-01-01")
    original_due_at = review_schedule.due_at
    backfill_attempt_phase_ids(attempts, phases)
    phases.insert(2, {"phase_id": "remedial"})
    shift_attempt_indices_after_insertion(attempts, 1)
    assert attempts[0].phase_id == "a" and attempts[0].phase_index == 0
    assert attempts[1].phase_id == "c" and attempts[1].phase_index == 3
    assert history[0]["attempt_id"] == attempts[1].id
    # ReviewSchedule is skill-scoped, so phase insertion must leave it untouched.
    assert (review_schedule.user_id, review_schedule.goal_id, review_schedule.skill_name, review_schedule.due_at) == ("u", "g", "SQL", original_due_at)


def test_regeneration_reindexes_attempts_by_identity():
    previous = [{"phase_id": "a"}, {"phase_id": "b"}]
    generated = [{"phase_id": "b"}, {"phase_id": "a"}]
    attempts = [SimpleNamespace(phase_index=0, phase_id=None), SimpleNamespace(phase_index=1, phase_id=None)]
    reconcile_attempts_to_phase_order(attempts, previous, generated)
    assert [(a.phase_id, a.phase_index) for a in attempts] == [("a", 1), ("b", 0)]


def test_phase_id_survives_pydantic_roadmap_round_trip():
    from app.models.schemas import RoadmapResponse

    payload = {"goal_id": "g", "phases": [{"title": "Python", "phase_id": "stable-id-1", "skills": ["Python"]}]}
    dumped = RoadmapResponse.model_validate(payload).model_dump(exclude_none=True)
    assert dumped["phases"][0]["phase_id"] == "stable-id-1"
