"""Strict JSON schemas, token/effort settings and the schema fallback (no network)."""
import json

import pytest
import requests

from app.services import llm_service as ls
from app.services.llm_service import LLMError, LLMService
from app.utils.config import settings


class Resp:
    def __init__(self, status=200, content='{"ok": true}', finish="stop", text=""):
        self.status_code, self.ok, self.text = status, 200 <= status < 300, text
        self._p = {"choices": [{"message": {"content": content}, "finish_reason": finish}]}

    def json(self):
        return self._p


def svc():
    s = LLMService()
    s.groq_api_key = "k"
    return s


def capture(monkeypatch, responses):
    calls = []
    it = iter(responses)

    def post(url, **kw):
        calls.append(kw["json"])
        return next(it)

    monkeypatch.setattr(requests, "post", post)
    return calls


def strict_ok(node):
    """Every object must list all its properties as required and forbid extras."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
        for v in node.values():
            strict_ok(v)
    elif isinstance(node, list):
        for v in node:
            strict_ok(v)


@pytest.mark.parametrize("name", ["SKILLS_SCHEMA", "PLAN_ELABORATION_SCHEMA", "REMEDIAL_SCHEMA",
                                  "STUDY_NOTES_SCHEMA", "SUMMARY_SCHEMA", "QUIZ_SCHEMA"])
def test_every_schema_is_strict_compatible(name):
    strict_ok(getattr(ls, name))


def test_schema_is_sent_as_strict_json_schema(monkeypatch):
    calls = capture(monkeypatch, [Resp()])
    svc()._generate_json("p", schema=ls.SUMMARY_SCHEMA, schema_name="learner_summary")
    rf = calls[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "learner_summary"


def test_rejected_schema_falls_back_to_plain_json_once(monkeypatch):
    calls = capture(monkeypatch, [Resp(400, text="bad schema"), Resp(content='{"summary": "hi"}')])
    out = svc()._generate_json("p", schema=ls.SUMMARY_SCHEMA, schema_name="s")
    assert out == {"summary": "hi"}
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_truncated_json_is_a_clear_error_not_a_silent_empty(monkeypatch):
    capture(monkeypatch, [Resp(content='{"phases": [', finish="length")] * 2)
    with pytest.raises(LLMError) as e:
        svc()._generate_json("p", retries=0)
    assert e.value.kind == "bad_response"


def test_truncated_then_repaired(monkeypatch):
    capture(monkeypatch, [Resp(content='{"a": [', finish="length"), Resp(content='{"a": 1}')])
    assert svc()._generate_json("p", retries=1) == {"a": 1}


def test_token_and_effort_defaults_and_overrides(monkeypatch):
    assert settings.GROQ_MAX_COMPLETION_TOKENS >= 16384
    assert settings.GROQ_ROADMAP_REASONING_EFFORT == "high"
    calls = capture(monkeypatch, [Resp(), Resp()])
    s = svc()
    s._generate_json("p")
    s._generate_json("p", max_tokens=123, reasoning_effort="low")
    assert calls[0]["max_completion_tokens"] == settings.GROQ_MAX_COMPLETION_TOKENS
    assert calls[1]["max_completion_tokens"] == 123 and calls[1]["reasoning_effort"] == "low"


def test_plan_elaboration_uses_schema_and_roadmap_effort():
    s, seen = svc(), {}

    def fake(prompt, **kw):
        seen.update(kw)
        return {"phases": []}

    s._generate_json = fake
    s.generate_roadmap_from_plan({"goal_skill_name": "G"}, [{"index": 0, "title": "P", "skills": []}])
    assert seen["schema"] is ls.PLAN_ELABORATION_SCHEMA
    assert seen["reasoning_effort"] == settings.GROQ_ROADMAP_REASONING_EFFORT


def test_quiz_uses_schema_and_quiz_token_limit():
    s, seen = svc(), {}

    def fake(prompt, **kw):
        seen.update(kw)
        return {"questions": [{"question": "q", "options": list("abcd"), "correct_index": 1,
                               "explanation": "e", "skill": "S"}]}

    s._generate_json = fake
    assert s.generate_quiz("P", ["S"], "beginner")
    assert seen["schema"] is ls.QUIZ_SCHEMA
    assert seen["max_tokens"] == settings.GROQ_QUIZ_MAX_COMPLETION_TOKENS


def test_tutor_stream_uses_settings_not_hardcoded_values(monkeypatch):
    sent = {}

    class R:
        ok, status_code, text, encoding = True, 200, "", None

        def iter_lines(self, decode_unicode=True):
            yield 'data: {"choices":[{"delta":{"content":"hi"}}]}'
            yield "data: [DONE]"

        def close(self):
            pass

    def post(url, **kw):
        sent.update(kw["json"])
        return R()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(settings, "GROQ_CHAT_MAX_COMPLETION_TOKENS", 7777)
    monkeypatch.setattr(settings, "GROQ_REASONING_EFFORT", "high")
    assert "".join(svc().chat_stream("sys", [], "q")) == "hi"
    assert sent["max_completion_tokens"] == 7777 and sent["reasoning_effort"] == "high"


def test_no_hugging_face_fallback_remains():
    assert not hasattr(LLMService, "_call_huggingface")
    assert not hasattr(settings, "ENABLE_HF_FALLBACK") and not hasattr(settings, "HF_FALLBACK_MODEL")
