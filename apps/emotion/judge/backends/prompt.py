# -*- coding: utf-8 -*-
"""两条本地传输（Ollama 原生 / OpenAI 兼容）共用的部分：system prompt、输出 schema、消息拼装、
模型 JSON → Jev 形状答案。logprobs 后端将来只需替换 to_jev_answers 里的概率来源。"""
from __future__ import annotations

import json

_CONFIDENCE = {"type": "number", "minimum": 0, "maximum": 1}
# 只抬不压的 noul 题：题面要求「有疑问就答 true」，模型答了 true 就按 true 算，自报置信度再低
# 也只压到 0.5（归一化后 value=true、显示「不确定」），不会被换算成 false、显示成「未见风险」。
_RAISE_ONLY = ("risk_clue",)

SYSTEM_PROMPT = (
    "You are a judgment model for a Chinese medical pre-consultation transcript. You never write replies. "
    "Judge ONLY the patient's latest message (the last message, from 'patient') in the context of the thread; "
    "the field chat.focus names the question the patient was answering. "
    "Answer every question strictly by its instructions and criteria. "
    "confidence is your own probability (0-1) that the answer is right; use low confidence or the 'unknown' "
    "option when the text does not support a judgment. "
    "evidence: quote the short phrase from the patient's latest message that most drove your answers, "
    "in the original Chinese; empty string if none. "
    "Output JSON only, matching the schema. No explanations."
)


def build_schema(questions: dict) -> dict:
    props = {}
    for name, q in questions.items():
        if q["type"] == "noul":
            fields = {"answer": {"type": "boolean"}, "confidence": _CONFIDENCE}
        elif q["type"] == "choice":
            fields = {"choice": {"type": "string", "enum": list(q["criteria"])}, "confidence": _CONFIDENCE}
        elif q["type"] == "score":
            fields = {"score": {"type": "integer", "minimum": 0, "maximum": 9}, "confidence": _CONFIDENCE}
        else:
            raise ValueError(f"{name}: unknown question type {q['type']!r}")
        props[name] = {"type": "object", "properties": fields, "required": list(fields),
                       "additionalProperties": False}
    return {
        "type": "object",
        "properties": {
            "evidence": {"type": "string"},
            "answers": {"type": "object", "properties": props, "required": list(props),
                        "additionalProperties": False},
        },
        "required": ["evidence", "answers"],
        "additionalProperties": False,
    }


def build_messages(state: dict, questions: dict) -> list:
    user = (
        "## Conversation state (JSON; chat text is Chinese)\n"
        + json.dumps(state, ensure_ascii=False, indent=1)
        + "\n\n## Questions (JSON)\n"
        + json.dumps(questions, ensure_ascii=False, indent=1)
        + "\n\nAnswer every question about the patient's latest message. Output JSON only."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def to_jev_answers(raw_answers: dict, questions: dict) -> dict:
    """模型 JSON → Jev 形状。缺题、选项不在 criteria 里的题直接丢，不报错（engine 按缺答案处理）。"""
    out = {}
    for name, q in questions.items():
        raw = raw_answers.get(name)
        if not isinstance(raw, dict):
            continue
        conf = _clamp(raw.get("confidence", 0.5))
        if q["type"] == "noul":
            answer = bool(raw.get("answer"))
            p = conf if answer else 1 - conf
            if answer and name in _RAISE_ONLY:
                p = max(p, 0.5)
            out[name] = {"type": "noul", "noul": round(p, 4)}
        elif q["type"] == "choice":
            choice = raw.get("choice")
            if choice not in q["criteria"]:
                continue
            out[name] = {"type": "choice", "choice": choice, "confidence": conf,
                         "probabilities": {choice: conf}}
        else:
            try:
                score = min(9, max(0, int(raw.get("score"))))
            except (TypeError, ValueError):
                continue
            out[name] = {"type": "score", "score": score, "confidence": conf,
                         "probabilities": {str(score): conf}}
    return out


def _clamp(x) -> float:
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.5
