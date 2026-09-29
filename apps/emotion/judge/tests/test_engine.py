# -*- coding: utf-8 -*-
from apps.emotion.judge.backends.base import JudgeError
from apps.emotion.judge.engine import SCHEMA_VERSION, analyze_session

SESSION = {
    "session_id": "demo-1",
    "turns": [
        {"role": "agent", "text": "最近睡眠怎么样？", "question_id": "sleep"},
        {"role": "patient", "text": "还行吧。"},
        {"role": "agent", "text": "有没有在吃什么药？", "question_id": "medication"},
        {"role": "patient", "text": "吃了点助眠的，名字忘了。"},
        {"role": "agent", "text": "最近心情怎么样？", "question_id": "mood"},
        {"role": "patient", "text": "有时候觉得活着没什么意思。"},
    ],
}


class ScriptedBackend:
    """按「患者回答文本」给答案的假后端；记录每次调用的 state / questions。"""
    source = "scripted"

    def __init__(self, script, fail_on=None):
        self.script, self.fail_on, self.calls = script, fail_on, []

    def ask(self, state, questions):
        text = state["chat"]["messages"][-1]["text"]
        self.calls.append((text, tuple(questions)))
        if text == self.fail_on:
            raise JudgeError("scripted failure")
        group = "medical" if "risk_clue" in questions else "emotion"
        return {"answers": self.script[text][group], "usage": {"input_tokens": 1}, "source": self.source}


def _noul(p):
    return {"type": "noul", "noul": p}


def _choice(k, c=0.9):
    return {"type": "choice", "choice": k, "confidence": c}


def _score(s, c=0.9):
    return {"type": "score", "score": s, "confidence": c}


SCRIPT = {
    "还行吧。": {
        "emotion": {"answer_adequacy": _choice("minimal"), "worth_flagging": _noul(0.3)},
        "medical": {"contains_key_info": _noul(0.1), "urgency": _score(1), "risk_clue": _noul(0.0)},
    },
    "吃了点助眠的，名字忘了。": {
        "emotion": {"answer_adequacy": _choice("full"), "worth_flagging": _noul(0.2)},
        "medical": {"contains_key_info": _noul(0.95), "info_category": _choice("medication"),
                    "urgency": _score(4), "risk_clue": _noul(0.0), "needs_followup": _noul(0.9)},
    },
    "有时候觉得活着没什么意思。": {
        "emotion": {"answer_adequacy": _choice("full"), "tension_level": _score(6), "worth_flagging": _noul(0.85)},
        "medical": {"contains_key_info": _noul(0.9), "info_category": _choice("risk_clue"),
                    "urgency": _score(9), "risk_clue": _noul(0.95)},
    },
}


def test_judges_every_patient_turn_once_per_group():
    backend = ScriptedBackend(SCRIPT)
    analyze_session(SESSION, backend)
    texts = [t for t, _ in backend.calls]
    assert texts.count("还行吧。") == 2 and len(backend.calls) == 6
    assert all("最近" not in t for t in texts)  # agent 轮不判


def test_result_carries_schema_version_and_session_id():
    result = analyze_session(SESSION, ScriptedBackend(SCRIPT))
    assert result["schema_version"] == SCHEMA_VERSION and result["session_id"] == "demo-1"


def test_hits_are_ranked_with_risk_first_and_carry_context():
    result = analyze_session(SESSION, ScriptedBackend(SCRIPT))
    hits = result["hits"]
    assert hits[0]["turn_index"] == 5 and hits[0]["risk"] is True and hits[0]["group"] == "medical"
    assert hits[0]["question_id"] == "mood" and hits[0]["text"] == "有时候觉得活着没什么意思。"
    assert hits[0]["source"] == "scripted"
    # 然后 emotion 0.85，再是用药那条 0.95*(0.4+0.6*4/9)≈0.63
    assert [(h["turn_index"], h["group"]) for h in hits[1:]] == [(5, "emotion"), (3, "medical")]


def test_low_importance_turns_are_not_hits_but_still_reported():
    result = analyze_session(SESSION, ScriptedBackend(SCRIPT))
    assert all(h["turn_index"] != 1 for h in result["hits"])
    turn1 = result["turns"][1]
    assert turn1["role"] == "patient" and set(turn1["judgments"]) == {"emotion", "medical"}
    assert turn1["judgments"]["emotion"]["answers"]["answer_adequacy"]["value"] == "minimal"


def test_hits_carry_chinese_labels():
    result = analyze_session(SESSION, ScriptedBackend(SCRIPT))
    med = next(h for h in result["hits"] if h["turn_index"] == 3 and h["group"] == "medical")
    assert med["labels"]["info_category"] == "用药"
    assert med["labels"]["needs_followup"] == "信息不完整，需追问"
    assert med["labels"]["urgency"] == "紧急程度 4/9"


def test_backend_failure_on_one_turn_does_not_abort_session():
    backend = ScriptedBackend(SCRIPT, fail_on="吃了点助眠的，名字忘了。")
    result = analyze_session(SESSION, backend)
    assert "scripted failure" in result["turns"][3]["judgments"]["emotion"]["error"]
    assert result["hits"][0]["turn_index"] == 5  # 其他轮照常
    assert result["errors"] == 2


def test_hits_carry_backend_evidence_when_given():
    class WithEvidence(ScriptedBackend):
        def ask(self, state, questions):
            got = super().ask(state, questions)
            got["evidence"] = "活着没什么意思"
            return got

    result = analyze_session(SESSION, WithEvidence(SCRIPT))
    assert result["hits"][0]["evidence"] == "活着没什么意思"
    assert result["turns"][5]["judgments"]["medical"]["evidence"] == "活着没什么意思"


def test_turns_and_hits_carry_record_time_when_present():
    timed = {"session_id": "timed", "turns": [dict(t, t=100.0 + i) for i, t in enumerate(SESSION["turns"])]}
    result = analyze_session(timed, ScriptedBackend(SCRIPT))
    assert result["turns"][5]["t"] == 105.0
    assert {h["t"] for h in result["hits"]} == {103.0, 105.0}
    untimed = analyze_session(SESSION, ScriptedBackend(SCRIPT))
    assert all(h["t"] is None for h in untimed["hits"])
