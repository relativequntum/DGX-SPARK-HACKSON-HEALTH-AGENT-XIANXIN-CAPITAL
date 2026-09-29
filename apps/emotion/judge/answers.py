# -*- coding: utf-8 -*-
"""答案归一化与两条派生量：重要度、风险。

后端（本地或 Jev 云端）都返回 Jev 形状的答案：
  noul   {"type": "noul", "noul": p}                      p = 为 true 的概率
  choice {"type": "choice", "choice": k, "confidence": c, "probabilities": {...}}
  score  {"type": "score", "score": s, "confidence": c, "probabilities": {...}}
normalize() 把它们统一成 {"type", "value", "confidence", "unknown", ...}，unknown 的口径：
  noul   概率贴近 0.5（|p-0.5| < UNKNOWN_MARGIN）
  choice 选了 unknown，或 confidence < MIN_CONFIDENCE
  score  没给分，或 confidence < MIN_CONFIDENCE
概率只当置信度显示，不当情绪标签（设计决策第 5 条）。
"""
from __future__ import annotations

UNKNOWN_MARGIN = 0.15
MIN_CONFIDENCE = 0.6


def normalize(raw: dict, unknown_margin: float = UNKNOWN_MARGIN,
              min_confidence: float = MIN_CONFIDENCE) -> dict:
    kind = raw.get("type")
    if kind == "noul":
        p = _clamp(raw.get("noul", 0.5))
        return {"type": "noul", "value": p >= 0.5, "confidence": max(p, 1 - p),
                "unknown": abs(p - 0.5) < unknown_margin, "noul": p}
    if kind == "choice":
        choice = raw.get("choice")
        conf = _clamp(raw.get("confidence", 0.0))
        return {"type": "choice", "value": choice, "confidence": conf,
                "unknown": choice == "unknown" or choice is None or conf < min_confidence,
                "probabilities": dict(raw.get("probabilities") or {})}
    if kind == "score":
        score = raw.get("score")
        conf = _clamp(raw.get("confidence", 0.0))
        value = None if score is None else int(round(float(score)))
        return {"type": "score", "value": value, "confidence": conf,
                "unknown": value is None or conf < min_confidence,
                "probabilities": dict(raw.get("probabilities") or {})}
    raise ValueError(f"unknown answer type {kind!r}")


def importance(group: str, answers: dict) -> float:
    """0~1。emotion = P(worth_flagging)；medical = P(contains_key_info) × (0.4 + 0.6 × urgency/9)。"""
    if group == "emotion":
        flag = answers.get("worth_flagging")
        return round(float(flag["noul"]), 4) if flag else 0.0
    if group == "medical":
        key = answers.get("contains_key_info")
        if not key:
            return 0.0
        urgency = answers.get("urgency")
        u = (urgency["value"] or 0) / 9 if urgency and urgency["value"] is not None else 0.0
        return round(float(key["noul"]) * (0.4 + 0.6 * u), 4)
    raise ValueError(f"unknown group {group!r}")


def is_risk(answers: dict) -> bool:
    """只抬不压：任何一路说有风险就算有，不看 unknown。"""
    clue = answers.get("risk_clue")
    if clue and clue["noul"] >= 0.5:
        return True
    category = answers.get("info_category")
    if category and category["value"] == "risk_clue":
        return True
    urgency = answers.get("urgency")
    if urgency and urgency["value"] is not None and urgency["value"] >= 8:
        return True
    tension = answers.get("tension_level")  # 第 9 档的 criteria 写明按风险线索处理
    if tension and tension["value"] is not None and tension["value"] >= 9:
        return True
    return False


def _clamp(x) -> float:
    try:
        return min(1.0, max(0.0, float(x)))
    except (TypeError, ValueError):
        return 0.0
