# -*- coding: utf-8 -*-
"""后端协议：ask(state, questions) -> {"answers": {题名: Jev 形状答案}, "usage": {...}, "source": str}。

engine 不关心答案是本地模型还是 Jev 云端算的，只看 source。所有后端出错一律抛 JudgeError，
错误文本先过 redact_secrets，绝不带 key。
"""
from __future__ import annotations

import os
import pathlib

# 可能存 key 的环境变量：脱敏时一次全过。LOCAL_LLM_API_KEY 是阶段二 llama-server 的 --api-key。
ENV_VARS = ("JEV_API_KEY", "OPENROUTER_API_KEY", "LOCAL_LLM_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")
# 指向 key 文件的环境变量：Spark 上阶段二 llama-server 的 key 放在 LOCAL_LLM_KEY_FILE 指向的文件里（env.sh 约定）。
KEY_FILE_VARS = ("LOCAL_LLM_KEY_FILE",)


class JudgeError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(redact_secrets(message))
        self.status = status


def file_secret(var: str) -> str:
    """读环境变量 var 指向的 key 文件；没设或读不到都返回空串。"""
    path = (os.environ.get(var) or "").strip()
    if not path:
        return ""
    try:
        return pathlib.Path(path).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def redact_secrets(text) -> str:
    text = str(text)
    secrets = [(os.environ.get(env) or "").strip() for env in ENV_VARS]
    secrets += [file_secret(var) for var in KEY_FILE_VARS]
    for key in secrets:
        if len(key) >= 8:
            text = text.replace(key, "[REDACTED]")
    return text


class FallbackBackend:
    """primary 抛 JudgeError 就退到 secondary（设计决策第 9 条：云端失败自动退本地）。"""

    def __init__(self, primary, secondary) -> None:
        self.primary, self.secondary = primary, secondary
        self.source = f"{getattr(primary, 'source', '?')}->{getattr(secondary, 'source', '?')}"

    def ask(self, state: dict, questions: dict) -> dict:
        try:
            return self.primary.ask(state, questions)
        except JudgeError:
            return self.secondary.ask(state, questions)
