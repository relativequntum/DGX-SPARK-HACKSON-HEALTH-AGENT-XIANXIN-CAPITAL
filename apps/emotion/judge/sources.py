# -*- coding: utf-8 -*-
"""会话来源 → judge 的 session dict（{"session_id", "turns": [...]}）。

- `.json`：本模块的会话格式，或裸 turns 列表（session_id 取文件名）；
- `.jsonl`：阶段二数字人 consult_recorder 落盘的问诊记录（Spark 上
  `~/livetalking-logs/consultations/<sessionid>.jsonl`），每行一个事件
  `{"t", "kind": "user"|"assistant"|"summary", "text", ...}`。user → patient，assistant → agent；
  summary 等其他事件、空文本、坏行一律跳过。

问诊记录可能是真人说的话：只在 Spark 本机用本地模型判断，结果不入库、不上云（设计决策第 9、13 条）。
"""
from __future__ import annotations

import json
import pathlib

_KIND_TO_ROLE = {"user": "patient", "assistant": "agent"}


def load_session(path) -> dict:
    path = pathlib.Path(path)
    if path.suffix.lower() == ".jsonl":
        return from_consult_record(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"session_id": path.stem, "turns": data}
    data.setdefault("session_id", path.stem)
    return data


def from_consult_record(path) -> dict:
    path = pathlib.Path(path)
    turns = []
    # 与 watch._scan 同一口径：数字人写了半行（断在汉字中间）也不抛，那一行解析不了照常跳过
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        role = _KIND_TO_ROLE.get(event.get("kind"))
        text = str(event.get("text") or "").strip()
        if role and text:
            turn = {"role": role, "text": text}
            if isinstance(event.get("t"), (int, float)):
                turn["t"] = event["t"]  # 事件时间：医生控制台靠它把「重点」对回对话原句
            turns.append(turn)
    return {"session_id": path.stem, "source": "consult_recorder", "turns": turns}
