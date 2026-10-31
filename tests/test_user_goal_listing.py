"""Regression tests for user-facing learning-goal choices."""
from types import SimpleNamespace

from app.services.auth_service import AuthService
import app.services.auth_service as auth_service_module


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def query(self, model):
        return _FakeQuery(self.rows)

    def close(self):
        self.closed = True


def test_user_goal_list_excludes_only_internal_llm_first_algorithm_test_goal(monkeypatch):
    rows = [
        SimpleNamespace(goal_id=2, goal_name="Master Algorithms"),
        SimpleNamespace(goal_id=26, goal_name="__TEST__ LLM-First Roadmap - Algorithms"),
        SimpleNamespace(goal_id=7, goal_name="Competitive Programming Preparation"),
    ]
    db = _FakeSession(rows)
    monkeypatch.setattr(auth_service_module, "SessionLocal", lambda: db)

    result = AuthService().get_all_goals()

    assert result == [
        {"goal_id": 2, "goal_name": "Master Algorithms"},
        {"goal_id": 7, "goal_name": "Competitive Programming Preparation"},
    ]
    assert db.closed is True


def test_test_goal_match_is_case_and_separator_insensitive():
    assert AuthService._is_internal_test_goal("__TEST__ LLM-First Roadmap - Algorithms")
    assert AuthService._is_internal_test_goal("test llm first roadmap algorithms")


def test_legitimate_algorithm_goal_is_not_hidden():
    assert not AuthService._is_internal_test_goal("Master Algorithms")
