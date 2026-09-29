# -*- coding: utf-8 -*-
"""对话 → 判断用的 state dict。平台无关：本地后端和 Jev 云端吃同一个形状。

turns: [{"role": "agent"|"patient", "text": str, "question_id": str（agent 轮可选）}]
focus: 要判断的那条患者回答在 turns 里的下标。
keep:  连同 focus 在内，最多带最近多少轮上下文。

返回 {"chat": {"messages": [...], "latest_from": "patient", "focus": {...}}, "channels": {}}。
channels 预留给决赛：语音 / 面部观察条目以文字形式塞进去，判断题一起看（设计决策第 7 条）。
"""
from __future__ import annotations

ROLES = ("agent", "patient")


def build_state(turns: list, focus: int, keep: int = 10) -> dict:
    if not 0 <= focus < len(turns):
        raise ValueError(f"focus {focus} out of range for {len(turns)} turns")
    for i, t in enumerate(turns):
        if t.get("role") not in ROLES:
            raise ValueError(f"turn {i}: role must be one of {ROLES}, got {t.get('role')!r}")
    if turns[focus]["role"] != "patient":
        raise ValueError(f"focus {focus} must be a patient turn, got {turns[focus]['role']!r}")

    window = turns[max(0, focus - keep + 1): focus + 1]
    messages = [{"from": t["role"], "text": str(t.get("text", ""))} for t in window]

    question = _question_before(turns, focus)
    return {
        "chat": {
            "messages": messages,
            "latest_from": "patient",
            "focus": question,
        },
        "channels": {},
    }


def _question_before(turns: list, focus: int) -> dict:
    """focus 之前最近的一条 agent 轮就是「当时在答哪一题」；没有就给空。"""
    for t in reversed(turns[:focus]):
        if t["role"] == "agent":
            return {"question_id": t.get("question_id") or "", "question": str(t.get("text", ""))}
    return {"question_id": "", "question": ""}
