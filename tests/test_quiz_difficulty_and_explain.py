"""BKT-aware quiz difficulty and the tutor's 'explain this answer' (no network)."""
import json
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ChatMessage, Goal, IssuedQuiz, User
from app.routes import chat_routes
from app.routes.auth_routes import get_current_user
from app.services import chat_service as chat_module
from app.services.adaptive_service import AdaptiveService, MIN_BKT_EVIDENCE
from app.services.llm_service import LLMError
from app.utils.time import utcnow_naive

step = AdaptiveService.difficulty_step


# ---- difficulty_step ---------------------------------------------------------
def test_no_evidence_keeps_the_profile_level():
    assert step(None, None, 0) == (0, "Based on your profile")


def test_mastery_is_ignored_until_there_is_enough_evidence():
    assert step(None, 95, MIN_BKT_EVIDENCE - 1)[0] == 0
    assert step(None, 10, MIN_BKT_EVIDENCE - 1)[0] == 0


def test_confident_high_mastery_makes_the_quiz_harder():
    s, reason = step(None, 90, MIN_BKT_EVIDENCE)
    assert s == 1 and "harder" in reason and "90%" in reason


def test_confident_low_mastery_makes_the_quiz_lighter():
    assert step(None, 25, 8)[0] == -1


def test_agreeing_signals_move_one_step_not_two():
    assert step(95, 90, 10)[0] == 1
    assert step(20, 20, 10)[0] == -1


def test_disagreeing_signals_cancel():
    s, reason = step(20, 90, 10)
    assert s == 0 and "different directions" in reason
    assert step(95, 20, 10)[0] == 0


def test_score_alone_still_works_like_before():
    assert step(30, None, 0)[0] == -1
    assert step(90, None, 0)[0] == 1
    assert step(70, None, 0)[0] == 0


# ---- explain_answer ----------------------------------------------------------
@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(chat_module, "SessionLocal", Session)
    db = Session()
    db.add_all([Goal(goal_id="g", goal_name="Goal"),
                User(user_id="u1", username="one", email="1@x.test"),
                User(user_id="u2", username="two", email="2@x.test")])
    questions = [{"question_id": "q1", "question": "What is 2+2?", "options": ["3", "4", "5", "6"],
                  "correct_index": 1, "explanation": "Basic addition.", "skill": "Math"}]
    now = utcnow_naive()
    db.add(IssuedQuiz(quiz_id="done", user_id="u1", goal_id="g", phase_index=0, questions_json=json.dumps(questions),
                      expires_at=now + timedelta(hours=1), submitted_at=now))
    db.add(IssuedQuiz(quiz_id="open", user_id="u1", goal_id="g", phase_index=0, questions_json=json.dumps(questions),
                      expires_at=now + timedelta(hours=1), submitted_at=None))
    db.commit(); db.close()

    sent = {}

    def fake_chat(system_prompt, history, message):
        sent.update(system=system_prompt, message=message)
        return "Because 2+2 is 4."

    monkeypatch.setattr(chat_module.llm_service, "chat", fake_chat)
    monkeypatch.setattr(chat_module.chat_service, "_build_context", lambda uid, gid=None: {"goal_id": "g"})
    monkeypatch.setattr(chat_module.chat_service, "_build_system_prompt", lambda ctx: "SYSTEM")
    return Session, sent


def test_explain_sends_full_context_but_saves_a_short_message(env):
    Session, sent = env
    out = chat_module.chat_service.explain_answer("u1", "done", "q1", 0)
    assert out == {"reply": "Because 2+2 is 4.", "goal_id": "g"}
    m = sent["message"]
    assert "The learner chose: A. 3" in m and "The correct answer is: B. 4" in m and "Basic addition." in m
    assert "why the learner's choice is wrong" in m
    db = Session()
    rows = db.query(ChatMessage).order_by(ChatMessage.id).all()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "Explain this quiz question: What is 2+2?"
    db.close()


def test_explain_for_a_correct_answer_asks_for_confirmation_not_a_correction(env):
    _, sent = env
    chat_module.chat_service.explain_answer("u1", "done", "q1", 1)
    assert "The learner was right" in sent["message"] and "is wrong" not in sent["message"]


@pytest.mark.parametrize("user,quiz,question,idx", [
    ("u1", "open", "q1", 0),      # not submitted yet: the key must not leak
    ("u2", "done", "q1", 0),      # someone else's quiz
    ("u1", "nope", "q1", 0),
    ("u1", "done", "zzz", 0),
    ("u1", "done", "q1", 3 + 1),  # out of range for 4 options
])
def test_explain_rejects_unsubmitted_foreign_or_bad_requests(env, user, quiz, question, idx):
    with pytest.raises(ValueError):
        chat_module.chat_service.explain_answer(user, quiz, question, idx)


def test_llm_failure_saves_nothing_and_route_returns_its_status(env, monkeypatch):
    Session, _ = env

    def down(*a, **k):
        raise LLMError("rate_limit")

    monkeypatch.setattr(chat_module.llm_service, "chat", down)
    app = FastAPI()
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    r = TestClient(app).post("/chat/explain-answer", json={"quiz_id": "done", "question_id": "q1", "selected_index": 0})
    assert r.status_code == 429
    db = Session()
    assert db.query(ChatMessage).count() == 0
    db.close()


def test_route_validation_and_bad_quiz(env):
    app = FastAPI()
    app.include_router(chat_routes.router)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    c = TestClient(app)
    assert c.post("/chat/explain-answer", json={"quiz_id": "open", "question_id": "q1", "selected_index": 0}).status_code == 400
    assert c.post("/chat/explain-answer", json={"quiz_id": "done", "question_id": "q1", "selected_index": 9}).status_code == 422
    ok = c.post("/chat/explain-answer", json={"quiz_id": "done", "question_id": "q1", "selected_index": 0})
    assert ok.status_code == 200 and ok.json()["reply"]


def test_explain_route_is_rate_limited_with_the_chat_group():
    from app.utils.rate_limit import LIMITS
    assert any(name == "chat" and rx.match("/chat/explain-answer") for name, rx, *_ in LIMITS)
