"""No-network tests for the Groq-backed LLM provider."""

import json

from app.services.llm_service import LLMService


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_gpt_oss_json_generation_uses_local_json_validation(monkeypatch):
    service = LLMService()
    service.groq_api_key = "unit-test-key"
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({"choices": [{"message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr("app.services.llm_service.requests.post", fake_post)

    result = service._call_groq(
        "Return an object.",
        model="openai/gpt-oss-120b",
        json_mode=True,
        temperature=0.1,
        seed=17,
    )

    assert result == '{"ok": true}'
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key"
    assert captured["json"]["model"] == "openai/gpt-oss-120b"
    # GPT-OSS responses are JSON-validated by the application locally. Avoid
    # Groq's server-side JSON-object validator, which returned json_validate_failed.
    assert "response_format" not in captured["json"]
    assert captured["json"]["include_reasoning"] is False
    assert "exactly one syntactically valid JSON object" in captured["json"]["messages"][0]["content"]
    assert captured["json"]["seed"] == 17
    assert captured["json"]["temperature"] == 0.1


def test_json_generation_keeps_dictionary_return_contract(monkeypatch):
    service = LLMService()
    calls = []

    def fake_groq(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return '{"phases": []}'

    monkeypatch.setattr(service, "_call_groq", fake_groq)

    result = service._generate_json("Create a roadmap.", retries=1)

    assert result == {"phases": []}
    assert len(calls) == 1
    assert calls[0][1]["json_mode"] is True


def test_chat_uses_the_configured_groq_model_and_preserves_history(monkeypatch):
    service = LLMService()
    service.model = "openai/gpt-oss-120b"
    captured = {}

    def fake_groq(prompt, **kwargs):
        captured["prompt"] = prompt
        captured.update(kwargs)
        return "Tutor response"

    monkeypatch.setattr(service, "_call_groq", fake_groq)

    result = service.chat(
        "You are a tutor.",
        [{"role": "user", "content": "Earlier question"}],
        "New question",
    )

    assert result == "Tutor response"
    assert captured["prompt"] == "New question"
    assert captured["system_prompt"] == "You are a tutor."
    assert captured["history"] == [{"role": "user", "content": "Earlier question"}]
    assert captured["model"] == "openai/gpt-oss-120b"
    assert captured["json_mode"] is False
