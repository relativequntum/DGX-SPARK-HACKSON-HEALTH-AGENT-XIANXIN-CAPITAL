# -*- coding: utf-8 -*-
"""整条链的唯一入口：会话 → 逐条患者回答判两组题 → 归一化 → 重要度 / 风险 → 排序命中。

平台无关：命令行、评测脚本、HTML 渲染都只调 analyze_session()。
预赛口径：会话结束后跑一次（设计决策第 6 条）；每条患者回答带最近 keep 轮上下文，结果挂到
「当时在答哪一题」上。一轮后端出错不中断整段，记 error 继续。
"""
from __future__ import annotations

import datetime as _dt

from . import questions_emotion, questions_medical
from .answers import importance, is_risk, normalize
from .backends.base import JudgeError
from .rank import rank_hits
from .state import build_state

SCHEMA_VERSION = "judge-0.1"
REVIEW_NOTICE = "待医务人员确认：本页只标出值得先看的回答，不构成诊断，不替代确定性红旗规则。"
GROUPS = {"emotion": questions_emotion, "medical": questions_medical}
DEFAULT_GROUPS = ("emotion", "medical")


def analyze_session(session: dict, backend, groups=DEFAULT_GROUPS, keep: int = 10,
                    threshold: float = 0.5) -> dict:
    turns = session["turns"]
    out_turns, hits, errors = [], [], 0
    for i, t in enumerate(turns):
        entry = {"index": i, "role": t["role"], "text": str(t.get("text", "")),
                 "question_id": t.get("question_id")}
        if t.get("t") is not None:
            entry["t"] = t["t"]
        if t["role"] == "patient":
            state = build_state(turns, i, keep)
            entry["judgments"] = {}
            for g in groups:
                judgment = _judge_one(backend, state, g)
                entry["judgments"][g] = judgment
                if "error" in judgment:
                    errors += 1
                    continue
                if judgment["risk"] or judgment["importance"] >= threshold:
                    hits.append({
                        "turn_index": i, "t": t.get("t"), "text": entry["text"],
                        "question_id": state["chat"]["focus"]["question_id"],
                        "question": state["chat"]["focus"]["question"],
                        "group": g, "group_label": GROUPS[g].GROUP_LABEL,
                        "importance": judgment["importance"], "risk": judgment["risk"],
                        "source": judgment["source"], "labels": judgment["labels"],
                        "evidence": judgment["evidence"], "answers": judgment["answers"],
                    })
        out_turns.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session.get("session_id"),
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "review_notice": REVIEW_NOTICE,
        "groups": list(groups),
        "keep": keep,
        "threshold": threshold,
        "turns": out_turns,
        "hits": rank_hits(hits),
        "errors": errors,
    }


def _judge_one(backend, state: dict, group: str) -> dict:
    module = GROUPS[group]
    try:
        res = backend.ask(state, dict(module.QUESTIONS))
    except JudgeError as exc:
        return {"error": str(exc), "answers": {}}
    answers = {name: normalize(raw) for name, raw in (res.get("answers") or {}).items()
               if name in module.QUESTIONS and isinstance(raw, dict)}
    return {
        "answers": answers,
        "labels": make_labels(module, answers),
        "importance": importance(group, answers),
        "risk": is_risk(answers),
        "source": res.get("source") or getattr(backend, "source", ""),
        "usage": res.get("usage") or {},
        "evidence": str(res.get("evidence") or ""),
    }


def make_labels(module, answers: dict) -> dict:
    """归一化答案 → 中文说法，医生视图和评测报告共用。unknown 的 noul/score 加「（不确定）」。"""
    labels = {}
    for name, a in answers.items():
        if a["type"] == "choice":
            labels[name] = module.CHOICE_LABELS.get(name, {}).get(a["value"], "无法判断")
        elif a["type"] == "noul":
            text = module.NOUL_LABELS.get(name, {}).get("true" if a["value"] else "false", name)
            labels[name] = text + ("（不确定）" if a["unknown"] else "")
        else:
            title = module.SCORE_LABELS.get(name, name)
            if a["value"] is None:
                labels[name] = f"{title} 无法判断"
            else:
                labels[name] = f"{title} {a['value']}/9" + ("（不确定）" if a["unknown"] else "")
    return labels
