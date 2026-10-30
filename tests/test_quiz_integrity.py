import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import GoalUserSkill, IssuedQuiz, QuizAttempt, QuizQuestionHistory, User, UserSkill
from app.models.schemas import QuizAnswerSubmission
from app.services import quiz_service as quiz_service_module
from app.services.activity_service import activity_service
from app.services.quiz_service import QuizService, QuizSubmissionError


@pytest.fixture
def quiz_test_environment(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(quiz_service_module, "SessionLocal", TestSession)
    # Post-commit side effects are unrelated to answer-key integrity.
    monkeypatch.setattr(activity_service, "_post_quiz_side_effects", lambda *args, **kwargs: None)

    db = TestSession()
    db.add_all([
        User(user_id="user-1", username="learner1", email="learner1@example.test"),
        User(user_id="user-2", username="learner2", email="learner2@example.test"),
    ])
    db.commit()
    db.close()
    try:
        yield TestSession
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def sample_questions():
    return [
        {
            "question": "Which option is correct?",
            "options": ["Wrong A", "Wrong B", "Right C", "Wrong D"],
            "correct_index": 2,
            "explanation": "The third option is supported by the concept.",
            "skill": "Python Basics",
        },
        {
            "question": "Which option is also correct?",
            "options": ["Right A", "Wrong B", "Wrong C", "Wrong D"],
            "correct_index": 0,
            "explanation": "The first option is the right answer.",
            "skill": "Python Basics",
        },
    ]


def test_issued_quiz_does_not_return_answer_key(quiz_test_environment):
    service = QuizService()
    issued = service.create_session("user-1", "goal-1", 0, "beginner", sample_questions())

    assert issued["quiz_id"]
    assert len(issued["questions"]) == 2
    for question in issued["questions"]:
        assert "correct_index" not in question
        assert "explanation" not in question
        assert "question_id" in question

    db = quiz_test_environment()
    try:
        stored = db.query(IssuedQuiz).filter_by(quiz_id=issued["quiz_id"]).one()
        saved_questions = json.loads(stored.questions_json)
        assert saved_questions[0]["correct_index"] == 2
        assert saved_questions[1]["correct_index"] == 0
    finally:
        db.close()


def test_grade_is_computed_from_server_key_and_bkt_uses_verified_results(quiz_test_environment):
    service = QuizService()
    issued = service.create_session("user-1", "goal-1", 0, "beginner", sample_questions())
    questions = issued["questions"]

    # First answer is wrong and second is correct. No score or correctness flag
    # is supplied by the client.
    result = service.grade_submission(
        "user-1", "goal-1", 0, issued["quiz_id"],
        [
            QuizAnswerSubmission(question_id=questions[0]["question_id"], selected_index=0),
            QuizAnswerSubmission(question_id=questions[1]["question_id"], selected_index=0),
        ],
    )

    assert result["total_questions"] == 2
    assert result["correct_answers"] == 1
    assert result["score_pct"] == 50
    assert [q["is_correct"] for q in result["graded_questions"]] == [False, True]
    assert [q["correct_index"] for q in result["graded_questions"]] == [2, 0]

    db = quiz_test_environment()
    try:
        attempt = db.query(QuizAttempt).filter_by(user_id="user-1", goal_id="goal-1").one()
        assert attempt.correct_answers == 1
        assert attempt.total_questions == 2
        history = db.query(QuizQuestionHistory).filter_by(attempt_id=attempt.id).order_by(QuizQuestionHistory.question_index).all()
        assert [item.is_correct for item in history] == [False, True]
        # BKT evidence is stored per goal, not on the global profile row.
        goal_skill = db.query(GoalUserSkill).filter_by(user_id="user-1", goal_id="goal-1").one()
        assert goal_skill.bkt_observations == 2
        assert db.query(UserSkill).filter_by(user_id="user-1").one().bkt_observations == 0
    finally:
        db.close()


def test_quiz_cannot_be_submitted_twice(quiz_test_environment):
    service = QuizService()
    issued = service.create_session("user-1", "goal-1", 0, "beginner", sample_questions())
    answers = [
        QuizAnswerSubmission(question_id=issued["questions"][0]["question_id"], selected_index=2),
        QuizAnswerSubmission(question_id=issued["questions"][1]["question_id"], selected_index=0),
    ]

    first = service.grade_submission("user-1", "goal-1", 0, issued["quiz_id"], answers)
    assert first["correct_answers"] == 2
    with pytest.raises(QuizSubmissionError) as exc:
        service.grade_submission("user-1", "goal-1", 0, issued["quiz_id"], answers)
    assert exc.value.status_code == 409

    db = quiz_test_environment()
    try:
        assert db.query(QuizAttempt).filter_by(user_id="user-1", goal_id="goal-1").count() == 1
    finally:
        db.close()


def test_quiz_session_is_bound_to_its_user(quiz_test_environment):
    service = QuizService()
    issued = service.create_session("user-1", "goal-1", 0, "beginner", sample_questions())
    answers = [
        type("Answer", (), {"question_id": q["question_id"], "selected_index": 0})()
        for q in issued["questions"]
    ]

    with pytest.raises(QuizSubmissionError) as exc:
        service.grade_submission("user-2", "goal-1", 0, issued["quiz_id"], answers)
    assert exc.value.status_code == 404


def test_submit_requires_exact_question_set(quiz_test_environment):
    service = QuizService()
    issued = service.create_session("user-1", "goal-1", 0, "beginner", sample_questions())
    first_question = issued["questions"][0]
    answer = QuizAnswerSubmission(question_id=first_question["question_id"], selected_index=0)

    with pytest.raises(QuizSubmissionError) as exc:
        service.grade_submission("user-1", "goal-1", 0, issued["quiz_id"], [answer])
    assert exc.value.status_code == 422

    # Invalid attempts don't consume a quiz; learner may submit the complete set.
    answers = [
        QuizAnswerSubmission(question_id=issued["questions"][0]["question_id"], selected_index=2),
        QuizAnswerSubmission(question_id=issued["questions"][1]["question_id"], selected_index=0),
    ]
    result = service.grade_submission("user-1", "goal-1", 0, issued["quiz_id"], answers)
    assert result["correct_answers"] == 2
