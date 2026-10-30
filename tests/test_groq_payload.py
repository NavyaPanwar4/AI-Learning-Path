"""The Groq payload must send reasoning_effort only to reasoning (gpt-oss) models."""
from unittest.mock import patch

from app.services.llm_service import LLMService


class _Resp:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}


def _payload_for(model):
    svc = LLMService()
    svc.groq_api_key = "test-key"
    with patch("app.services.llm_service.requests.post", return_value=_Resp()) as post:
        svc._call_groq("hi", model=model, json_mode=True, seed=1, max_tokens=100)
    return post.call_args.kwargs["json"]


def test_reasoning_effort_sent_for_gpt_oss():
    assert "reasoning_effort" in _payload_for("openai/gpt-oss-20b")


def test_reasoning_effort_not_sent_for_llama():
    p = _payload_for("llama-3.3-70b-versatile")
    assert "reasoning_effort" not in p
    assert p["response_format"] == {"type": "json_object"}
    assert p["seed"] == 1
