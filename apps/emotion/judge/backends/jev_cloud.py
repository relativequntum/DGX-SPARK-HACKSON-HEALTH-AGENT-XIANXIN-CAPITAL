# -*- coding: utf-8 -*-
# 来源与许可：本文件改编自 rezoch340/jev-chat-JARVIS-windows 的 core/jev_client.py
#   https://github.com/rezoch340/jev-chat-JARVIS-windows ，上游以 MIT License 发布。
# 本项目（spark-Hackson）做了删改（只保留 OpenRouter 一条路径、接入 judge 的错误与脱敏约定等）。
# 按 MIT 许可要求，保留上游版权声明与许可声明如下：
#
#   MIT License
#
#   Copyright (c) 2026 rezoch340 and the jev-chat contributors
#   Portions Copyright (c) 2026 Finderchangchang and the jev-chat contributors
#   (Jev 聊天助手, https://github.com/jev-chat/jev-chat-jarvis)
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#   SOFTWARE.
"""Jev 云端后端（可选，默认关）：OpenRouter 的 /api/alpha/decisions，模型 typesafe/jev-1.13。
改自参照项目 jev-chat-JARVIS-windows 的 core/jev_client.py，只留 OpenRouter 一条路。

设计决策第 9 条：
- 只有 cloud_enabled(flag) 为真才该构造并使用本后端：显式开关 + 环境变量 JEV_API_KEY；
- 只发 state.chat（最近 N 轮文字），不发 channels、不发任何身份信息；
- key 只从环境变量读，绝不进日志；429/529/超时退避重试，其余 HTTP 错误直接抛 JudgeError；
- 真实录音的转写稿绝不走这里（设计决策第 13 条，由调用方保证）。
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
from time import sleep
from urllib.request import Request, urlopen

from .base import JudgeError, redact_secrets

OPENROUTER_DECISIONS = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"
JEV_ENV = "JEV_API_KEY"
MAX_RETRIES = 3


def cloud_enabled(flag: bool) -> bool:
    return bool(flag) and bool((os.environ.get(JEV_ENV) or "").strip())


class JevCloudBackend:
    def __init__(self, model: str = DEFAULT_MODEL, timeout: float = 30) -> None:
        self.model, self.timeout = model, timeout
        self.source = f"jev-cloud:{model}"

    def ask(self, state: dict, questions: dict) -> dict:
        key = (os.environ.get(JEV_ENV) or "").strip()
        if not key:
            raise JudgeError(f"{JEV_ENV} 未设置：云端判断需要显式开关加 key，不在任何文件里放 key")
        payload = json.dumps({"model": self.model, "state": {"chat": state.get("chat", {})},
                              "questions": questions}, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json; charset=utf-8",
                   "Accept": "application/json"}
        last = "no attempt"
        for attempt in range(MAX_RETRIES + 1):
            req = Request(OPENROUTER_DECISIONS, data=payload, method="POST", headers=headers)
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                return {"answers": body.get("answers") or {}, "usage": body.get("usage") or {},
                        "source": self.source}
            except urllib.error.HTTPError as exc:
                detail = _error_body(exc)
                if exc.code in (429, 529) and attempt < MAX_RETRIES:
                    last = f"HTTP {exc.code}"
                    sleep(2 ** attempt)
                    continue
                hint = {401: "密钥被拒", 403: "没有权限", 404: "模型或地址不对", 422: "请求被拒",
                        429: "被限流", 529: "服务过载"}.get(exc.code, "")
                raise JudgeError(f"Jev HTTP {exc.code}: {hint or detail[:300]}", exc.code) from None
            except (TimeoutError, socket.timeout):
                last = "timeout"
            except urllib.error.URLError as exc:
                last = redact_secrets(getattr(exc, "reason", exc))
            if attempt < MAX_RETRIES:
                sleep(2 ** attempt)
        raise JudgeError(f"Jev 请求失败（重试 {MAX_RETRIES} 次）: {last}")


def _error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return redact_secrets(exc.read().decode("utf-8", errors="replace"))
    except Exception:
        return ""
