"""API-level smoke tests for auth, quizzes, adaptive logic, and tutor streaming."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes.auth_routes import get_current_user


@pytest.fixture

def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture

def authenticated_client():
    app.dependency_overrides[get_current_user] = lambda: "api-test-user"
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_protected_roadmap_api_requires_auth(client):
    response = client.get("/roadmap/saved")
    assert response.status_code == 401


def test_login_api_returns_auth_cookie(monkeypatch, client):
    from app.models.schemas import Token
    from app.routes import auth_routes

    monkeypatch.setattr(
        auth_routes.auth_service,
        "authenticate_user",
        lambda _payload: Token(access_token="test-token", token_type="bearer"),
    )
    response = client.post("/auth/login", json={"username": "tester", "password": "not-a-real-password"})
    assert response.status_code == 200
    assert response.json()["access_token"] == "test-token"
    assert "access_token" in response.cookies



def test_roadmap_generation_api_queues_background_job(monkeypatch, authenticated_client):
    from app.routes import roadmap_routes

    started = []
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "create_generation_job",
        lambda user_id: {"job_id": "job-test", "status": "queued", "user_id": user_id},
    )
    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "run_generation_job",
        lambda job_id, user_id: started.append((job_id, user_id)),
    )
    response = authenticated_client.post("/roadmap/generate-roadmap")
    assert response.status_code == 202
    assert response.json()["job_id"] == "job-test"
    assert started == [("job-test", "api-test-user")]

def test_quiz_generation_api_returns_questions(monkeypatch, authenticated_client):
    from app.routes import roadmap_routes

    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "get_saved_roadmap",
        lambda _user, _goal: {"goal_id": "goal-test", "phases": [{"title": "Python basics", "skills": ["Python"]}]},
    )
    monkeypatch.setattr(
        roadmap_routes.adaptive_service,
        "get_quiz_difficulty",
        lambda *_args: {"difficulty": "beginner", "reason": "initial mastery"},
    )
    monkeypatch.setattr(
        roadmap_routes.llm_service,
        "generate_quiz",
        lambda *_args, **_kwargs: [{"question": "What is Python?", "options": ["A", "B"]}],
    )
    # The hardened quiz-session service is present in newer project versions;
    # older compatible versions return generated questions directly.
    if hasattr(roadmap_routes, "quiz_service"):
        monkeypatch.setattr(
            roadmap_routes.quiz_service,
            "create_session",
            lambda _user, _goal, _phase, _difficulty, questions: {"quiz_id": "quiz-test", "questions": questions},
        )
    response = authenticated_client.post("/roadmap/goal-test/phase/0/quiz")
    assert response.status_code == 200
    assert response.json()["questions"][0]["question"] == "What is Python?"
    assert response.json()["difficulty"] == "beginner"



def test_quiz_api_rejects_unknown_phase(monkeypatch, authenticated_client):
    from app.routes import roadmap_routes

    monkeypatch.setattr(
        roadmap_routes.roadmap_service,
        "get_saved_roadmap",
        lambda _user, _goal: {"goal_id": "goal-test", "phases": [{"title": "Python basics", "skills": ["Python"]}]},
    )
    response = authenticated_client.post("/roadmap/goal-test/phase/7/quiz")
    assert response.status_code == 404
    assert response.json()["detail"] == "Phase not found"

def test_adaptive_recommendation_api_delegates_to_service(monkeypatch, authenticated_client):
    from app.routes import roadmap_routes

    monkeypatch.setattr(
        roadmap_routes.adaptive_service,
        "get_recommendation",
        lambda user_id, goal_id: {"user_id": user_id, "goal_id": goal_id, "action": "review"},
    )
    response = authenticated_client.get("/roadmap/goal-test/recommendation")
    assert response.status_code == 200
    assert response.json()["action"] == "review"
    assert response.json()["goal_id"] == "goal-test"


def test_streaming_chat_api_emits_sse_deltas(monkeypatch, authenticated_client):
    from app.routes import chat_routes

    monkeypatch.setattr(
        chat_routes.chat_service,
        "stream_message",
        lambda *_args: iter([
            {"type": "delta", "content": "Hello"},
            {"type": "delta", "content": " learner"},
            {"type": "done", "goal_id": "goal-test"},
        ]),
    )
    response = authenticated_client.post("/chat/stream", json={"message": "Hi", "goal_id": "goal-test"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"content": "Hello"' in response.text
    assert '"content": " learner"' in response.text
    assert '"type": "done"' in response.text

def test_startup_does_not_create_schema_automatically():
    from pathlib import Path
    import app.main as main_module

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    assert "Base.metadata.create_all" not in source

