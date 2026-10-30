"""LLMError mapping and the no-canned-quiz rule (no network)."""
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.llm_service import LLMError, LLMService


class Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self.ok = status, 200 <= status < 300
        self._payload, self.text = payload, text

    def json(self):
        return self._payload


def svc(key="k"):
    s = LLMService()
    s.groq_api_key = key
    return s


def test_missing_key_raises_not_configured():
    with pytest.raises(LLMError) as e:
        svc("")._call_groq("hi")
    assert e.value.kind == "not_configured" and e.value.status_code == 503


@pytest.mark.parametrize("status,kind,http", [
    (401, "auth", 503), (403, "auth", 503), (429, "rate_limit", 429),
    (500, "upstream", 502), (504, "timeout", 504), (400, "bad_request", 502),
])
def test_http_status_mapping_never_401_and_hides_body(monkeypatch, status, kind, http):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(status, text="SECRET-BODY gsk_x"))
    with pytest.raises(LLMError) as e:
        svc()._call_groq("hi")
    assert (e.value.kind, e.value.status_code) == (kind, http)
    assert "SECRET" not in str(e.value) and e.value.status_code != 401


def test_timeout_and_connection(monkeypatch):
    def boom(exc):
        def f(*a, **k):
            raise exc
        return f
    monkeypatch.setattr(requests, "post", boom(requests.exceptions.Timeout("t")))
    with pytest.raises(LLMError) as e:
        svc()._call_groq("hi")
    assert e.value.kind == "timeout"
    monkeypatch.setattr(requests, "post", boom(requests.exceptions.ConnectionError("c")))
    with pytest.raises(LLMError) as e:
        svc()._call_groq("hi")
    assert e.value.kind == "connection"


def test_empty_completion_is_bad_response(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(200, {"choices": [{"message": {"content": ""}}]}))
    with pytest.raises(LLMError) as e:
        svc()._call_groq("hi")
    assert e.value.kind == "bad_response"


def test_chat_stream_without_key_raises_instead_of_canned_text():
    with pytest.raises(LLMError):
        list(svc("").chat_stream("sys", [], "hello"))


def test_quiz_propagates_llm_error_and_never_returns_canned(monkeypatch):
    s = svc()

    def down(*a, **k):
        raise LLMError("rate_limit")

    s._generate_json = down
    with pytest.raises(LLMError) as e:
        s.generate_quiz("Phase", ["Python"], difficulty="beginner")
    assert e.value.kind == "rate_limit"

    s._generate_json = lambda *a, **k: {"questions": [{"question": "q", "options": ["a"], "correct_index": 0}]}
    with pytest.raises(LLMError) as e:
        s.generate_quiz("Phase", ["Python"], difficulty="beginner")
    assert e.value.kind == "bad_response"
    assert not hasattr(s, "_fallback_quiz")


def test_plan_elaboration_degrades_only_on_bad_response():
    s = svc()
    plan = [{"index": 0, "title": "P1", "skills": [{"id": "a", "name": "A", "action": "learn"}]}]
    ctx = {"goal_skill_name": "G"}

    s._generate_json = lambda *a, **k: (_ for _ in ()).throw(LLMError("bad_response"))
    assert s.generate_roadmap_from_plan(ctx, plan)["phases"]

    s._generate_json = lambda *a, **k: (_ for _ in ()).throw(LLMError("auth"))
    with pytest.raises(LLMError):
        s.generate_roadmap_from_plan(ctx, plan)


def test_remedial_phase_degrades_on_llm_error():
    s = svc()
    s._generate_json = lambda *a, **k: (_ for _ in ()).throw(LLMError("timeout"))
    out = s.generate_remedial_phase({"weak_skills": ["SQL"]})
    assert out["skills"] == ["SQL"]


def test_global_handler_returns_status_and_safe_detail():
    from app.main import llm_error_handler

    app = FastAPI()
    app.add_exception_handler(LLMError, llm_error_handler)

    @app.get("/x")
    def x():
        raise LLMError("rate_limit")

    r = TestClient(app).get("/x")
    assert r.status_code == 429 and "rate-limited" in r.json()["detail"]
