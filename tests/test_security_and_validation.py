from pydantic import ValidationError
import pytest

from app.models.schemas import FeedbackRequest, QuizSubmission, SessionLogRequest
from app.services.link_validator import _is_reachable
from app.services.skill_extraction import skill_extraction_service


def test_quiz_submission_rejects_client_supplied_grading_fields():
    # Scores/results must be derived from a server-issued quiz, never accepted
    # from client-provided correct_answers or question_results.
    with pytest.raises(ValidationError):
        QuizSubmission(
            quiz_id="issued-id",
            answers=[{"question_id": "q1", "selected_index": 0}],
            total_questions=4,
            correct_answers=4,
            question_results=[{"is_correct": True}],
        )


def test_quiz_submission_rejects_duplicate_question_ids():
    with pytest.raises(ValidationError):
        QuizSubmission(
            quiz_id="issued-id",
            answers=[
                {"question_id": "q1", "selected_index": 0},
                {"question_id": "q1", "selected_index": 1},
            ],
        )


def test_feedback_rating_is_bounded():
    with pytest.raises(ValidationError):
        FeedbackRequest(content_id="resource", content_type="resource", rating=6)


def test_session_duration_is_bounded():
    with pytest.raises(ValidationError):
        SessionLogRequest(duration_minutes=721)


def test_private_urls_are_rejected():
    assert _is_reachable("http://127.0.0.1:8000") is False


def test_bkt_correct_response_increases_mastery():
    assert skill_extraction_service.bkt_update(0.2, True) > 0.2


def test_bkt_incorrect_response_decreases_mastery():
    assert skill_extraction_service.bkt_update(0.2, False) < 0.2
