# -*- coding: utf-8 -*-
import json

import pytest

from apps.emotion.judge.backends.base import JudgeError
from apps.emotion.judge.backends.ollama_native import OllamaNativeBackend
from apps.emotion.judge.questions_emotion import QUESTIONS as EMOTION
from apps.emotion.judge.state import build_state

STATE = build_state([{"role": "agent", "text": "最近睡眠怎么样？", "question_id": "sleep"},
                     {"role": "patient", "text": "还行吧……其实经常半夜醒。"}], focus=1)

MODEL_JSON = {"evidence": "经常半夜醒",
              "answers": {"answer_adequacy": {"choice": "minimal", "confidence": 0.7},
                          "literal_answer": {"answer": False, "confidence": 0.8},
                          "tension_level": {"score": 3, "confidence": 0.6},
                          "inconsistency": {"answer": False, "confidence": 0.9},
                          "wants_from_agent": {"choice": "none", "confidence": 0.7},
                          "worth_flagging": {"answer": True, "confidence": 0.75}}}


class FakePost:
    """替代 HTTP：记下 body，返回 Ollama /api/chat 形状的响应。"""

    def __init__(self, content=None, exc=None, done_reason="stop"):
        self.content = json.dumps(MODEL_JSON, ensure_ascii=False) if content is None else content
        self.exc, self.done_reason, self.calls = exc, done_reason, []

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        if self.exc:
            raise self.exc
        return {"message": {"role": "assistant", "content": self.content, "thinking": ""},
                "done_reason": self.done_reason, "prompt_eval_count": 900, "eval_count": 150}


def test_native_call_disables_thinking_and_constrains_format():
    post = FakePost()
    backend = OllamaNativeBackend(model="qwen3-vl:8b", post=post, num_ctx=8192)
    got = backend.ask(STATE, EMOTION)
    url, body = post.calls[0]
    assert url.endswith("/api/chat")
    assert body["think"] is False and body["stream"] is False
    assert body["format"]["properties"]["answers"]["required"] == list(EMOTION)
    assert body["options"]["num_ctx"] == 8192 and body["options"]["temperature"] == 0
    assert body["messages"][-1]["content"].count("还行吧……其实经常半夜醒。") == 1
    assert got["source"] == "local:qwen3-vl:8b"
    assert got["answers"]["worth_flagging"] == {"type": "noul", "noul": 0.75}
    assert got["answers"]["answer_adequacy"]["choice"] == "minimal"
    assert got["usage"] == {"input_tokens": 900, "output_tokens": 150}
    assert got["evidence"] == "经常半夜醒"


def test_truncated_output_is_reported_as_judge_error():
    backend = OllamaNativeBackend(model="m", post=FakePost(content="", done_reason="length"))
    with pytest.raises(JudgeError) as info:
        backend.ask(STATE, EMOTION)
    assert "length" in str(info.value)


def test_transport_failure_becomes_judge_error():
    backend = OllamaNativeBackend(model="m", post=FakePost(exc=OSError("connection refused")))
    with pytest.raises(JudgeError):
        backend.ask(STATE, EMOTION)
