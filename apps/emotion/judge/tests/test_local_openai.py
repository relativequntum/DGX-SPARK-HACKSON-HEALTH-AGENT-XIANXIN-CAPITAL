# -*- coding: utf-8 -*-
import json
import types

import pytest

from apps.emotion.judge import questions_medical
from apps.emotion.judge.answers import is_risk, normalize
from apps.emotion.judge.backends.base import JudgeError
from apps.emotion.judge.backends.local_openai import LocalOpenAIBackend, build_schema
from apps.emotion.judge.backends.prompt import to_jev_answers
from apps.emotion.judge.engine import analyze_session, make_labels
from apps.emotion.judge.questions_medical import QUESTIONS as MEDICAL
from apps.emotion.judge.state import build_state

TURNS = [
    {"role": "agent", "text": "有没有在吃什么药？", "question_id": "medication"},
    {"role": "patient", "text": "吃了三天奥美拉唑，没什么用。"},
]
STATE = build_state(TURNS, focus=1)

MODEL_JSON = {
    "evidence": "吃了三天奥美拉唑",
    "answers": {
        "contains_key_info": {"answer": True, "confidence": 0.9},
        "info_category": {"choice": "medication", "confidence": 0.85},
        "risk_clue": {"answer": False, "confidence": 0.95},
        "urgency": {"score": 4, "confidence": 0.7},
        "specificity": {"choice": "specific", "confidence": 0.8},
        "needs_followup": {"answer": True, "confidence": 0.6},
    },
}


class FakeClient:
    """假 openai 客户端：记下请求，返回固定 JSON。"""

    def __init__(self, content=None, exc=None):
        self.content = json.dumps(MODEL_JSON, ensure_ascii=False) if content is None else content
        self.exc, self.kwargs = exc, None
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        msg = types.SimpleNamespace(content=self.content)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=msg)],
            usage=types.SimpleNamespace(prompt_tokens=120, completion_tokens=40))


def test_converts_model_json_into_jev_shaped_answers():
    backend = LocalOpenAIBackend(model="qwen3-vl:8b", client=FakeClient())
    got = backend.ask(STATE, MEDICAL)
    assert got["source"] == "local:qwen3-vl:8b"
    assert got["answers"]["contains_key_info"] == {"type": "noul", "noul": 0.9}
    assert got["answers"]["risk_clue"] == {"type": "noul", "noul": pytest.approx(0.05)}
    assert got["answers"]["info_category"] == {"type": "choice", "choice": "medication", "confidence": 0.85,
                                               "probabilities": {"medication": 0.85}}
    assert got["answers"]["urgency"] == {"type": "score", "score": 4, "confidence": 0.7,
                                         "probabilities": {"4": 0.7}}
    assert got["usage"] == {"input_tokens": 120, "output_tokens": 40}
    assert got["evidence"] == "吃了三天奥美拉唑"


def test_request_is_schema_constrained_and_carries_state_and_questions():
    client = FakeClient()
    LocalOpenAIBackend(model="m", client=client).ask(STATE, MEDICAL)
    kw = client.kwargs
    assert kw["model"] == "m" and kw["temperature"] == 0
    schema = kw["response_format"]["json_schema"]["schema"]
    props = schema["properties"]["answers"]["properties"]
    assert props["info_category"]["properties"]["choice"]["enum"] == list(MEDICAL["info_category"]["criteria"])
    assert props["urgency"]["properties"]["score"] == {"type": "integer", "minimum": 0, "maximum": 9}
    assert props["risk_clue"]["properties"]["answer"] == {"type": "boolean"}
    user_text = kw["messages"][-1]["content"]
    assert "吃了三天奥美拉唑，没什么用。" in user_text
    assert MEDICAL["risk_clue"]["instructions"][:40] in user_text


def test_schema_requires_every_question():
    schema = build_schema(MEDICAL)
    assert set(schema["properties"]["answers"]["required"]) == set(MEDICAL)
    assert schema["required"] == ["evidence", "answers"]


def test_malformed_json_raises_judge_error():
    backend = LocalOpenAIBackend(model="m", client=FakeClient(content="not json"))
    with pytest.raises(JudgeError):
        backend.ask(STATE, MEDICAL)


def test_missing_question_in_output_is_dropped_not_fatal():
    partial = {"evidence": "", "answers": {"risk_clue": {"answer": True, "confidence": 0.7}}}
    backend = LocalOpenAIBackend(model="m", client=FakeClient(content=json.dumps(partial)))
    got = backend.ask(STATE, MEDICAL)
    assert list(got["answers"]) == ["risk_clue"]


def test_client_exception_becomes_redacted_judge_error(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "sk-secret-value-123")
    backend = LocalOpenAIBackend(model="m", client=FakeClient(exc=RuntimeError("bad key sk-secret-value-123")))
    with pytest.raises(JudgeError) as info:
        backend.ask(STATE, MEDICAL)
    assert "sk-secret-value-123" not in str(info.value) and "[REDACTED]" in str(info.value)


def test_api_key_prefers_explicit_then_env_then_key_file(tmp_path, monkeypatch):
    from apps.emotion.judge.backends.local_openai import resolve_api_key

    key_file = tmp_path / "model-api-key"
    key_file.write_text("sk-from-file-123456\n", encoding="utf-8")
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_LLM_KEY_FILE", str(key_file))
    assert resolve_api_key() == "sk-from-file-123456"  # Spark 上阶段二 llama-server 的约定：key 放文件
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "sk-from-env-654321")
    assert resolve_api_key() == "sk-from-env-654321"
    assert resolve_api_key("explicit-key") == "explicit-key"


def test_api_key_falls_back_to_placeholder_when_nothing_configured(tmp_path, monkeypatch):
    from apps.emotion.judge.backends.local_openai import resolve_api_key

    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_LLM_KEY_FILE", str(tmp_path / "missing"))
    assert resolve_api_key() == "local"


# ---- #12 M3：risk_clue 只抬不压，答了 true 就算风险，不看自报置信度 ----

def test_risk_clue_true_with_low_confidence_still_counts_as_risk():
    raw = dict(MODEL_JSON["answers"], risk_clue={"answer": True, "confidence": 0.4})
    a = normalize(to_jev_answers(raw, MEDICAL)["risk_clue"])
    assert is_risk({"risk_clue": a}) is True
    label = make_labels(questions_medical, {"risk_clue": a})["risk_clue"]
    assert label.startswith("疑似风险线索") and "未见风险" not in label and "不确定" in label


def test_raise_only_does_not_touch_false_risk_or_other_questions():
    raw = dict(MODEL_JSON["answers"], risk_clue={"answer": False, "confidence": 0.9},
               contains_key_info={"answer": True, "confidence": 0.4})
    got = to_jev_answers(raw, MEDICAL)
    assert got["risk_clue"]["noul"] == pytest.approx(0.1)  # 答 false 照旧
    assert got["contains_key_info"]["noul"] == pytest.approx(0.4)  # 其他 noul 题照旧
    high = to_jev_answers(dict(raw, risk_clue={"answer": True, "confidence": 0.9}), MEDICAL)
    assert high["risk_clue"]["noul"] == pytest.approx(0.9)  # 高置信度不变


def test_low_confidence_risk_clue_is_a_top_ranked_risk_hit_end_to_end():
    model_json = {"evidence": "胸口有点闷", "answers": dict(
        MODEL_JSON["answers"], contains_key_info={"answer": False, "confidence": 0.9},
        risk_clue={"answer": True, "confidence": 0.4})}
    backend = LocalOpenAIBackend(model="qwen3-vl:8b", client=FakeClient(json.dumps(model_json, ensure_ascii=False)))
    session = {"session_id": "m3", "turns": [{"role": "agent", "text": "还有哪里不舒服？"},
                                             {"role": "patient", "text": "胸口有点闷，说不上来"}]}
    result = analyze_session(session, backend, groups=("medical",))
    assert result["errors"] == 0 and result["hits"]
    top = result["hits"][0]
    assert top["risk"] is True and top["labels"]["risk_clue"].startswith("疑似风险线索")
