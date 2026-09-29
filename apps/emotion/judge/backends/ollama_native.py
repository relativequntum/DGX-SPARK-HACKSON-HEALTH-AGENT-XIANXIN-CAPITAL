# -*- coding: utf-8 -*-
"""Ollama 原生传输：POST /api/chat。本机开发用。

为什么不走 Ollama 的 /v1（OpenAI 兼容）：实测（2026-09-24，Ollama 0.34.2，qwen3-vl:8b）/v1 不认 think:false，
模型照样推理、默认 4096 上下文被推理吃光，正文为空。原生端点 think:false + format=schema + num_ctx 8192
后 1.6 秒出完整 JSON。Ollama 有个怪癖：关思考后 qwen3-vl 的正文落在 message.thinking 里，content 为空，
所以这里取「content 为空就用 thinking」。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import JudgeError, redact_secrets
from .prompt import build_messages, build_schema, to_jev_answers

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3-vl:8b"


class OllamaNativeBackend:
    def __init__(self, host: str | None = None, model: str | None = None, timeout: float = 300,
                 num_ctx: int = 8192, num_predict: int = 1024, think: bool = False, post=None) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self.model = model or os.environ.get("LOCAL_LLM_MODEL") or DEFAULT_MODEL
        self.timeout, self.num_ctx, self.num_predict, self.think = timeout, num_ctx, num_predict, think
        self.source = f"local:{self.model}"
        self._post = post or _http_post

    def ask(self, state: dict, questions: dict) -> dict:
        body = {
            "model": self.model,
            "messages": build_messages(state, questions),
            "stream": False,
            "think": self.think,
            "format": build_schema(questions),
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": self.num_predict},
        }
        try:
            data = self._post(self.host + "/api/chat", body, self.timeout)
        except JudgeError:
            raise
        except Exception as exc:
            raise JudgeError(f"Ollama 请求失败: {redact_secrets(exc)}"[:400]) from None
        msg = data.get("message") or {}
        content = (msg.get("content") or "").strip() or (msg.get("thinking") or "").strip()
        if not content:
            reason = data.get("done_reason")
            raise JudgeError(f"Ollama 没有返回正文（done_reason={reason}）"
                             + ("；输出被截断，调大 num_predict / num_ctx" if reason == "length" else ""))
        try:
            parsed = json.loads(content)
        except ValueError:
            raise JudgeError(f"Ollama 输出不是 JSON: {redact_secrets(content)[:200]}") from None
        if not isinstance(parsed, dict):
            raise JudgeError("Ollama 输出不是 JSON 对象")
        return {
            "answers": to_jev_answers(parsed.get("answers") or {}, questions),
            "usage": {"input_tokens": int(data.get("prompt_eval_count") or 0),
                      "output_tokens": int(data.get("eval_count") or 0)},
            "source": self.source,
            "evidence": str(parsed.get("evidence") or "").strip(),
        }


def _http_post(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = redact_secrets(exc.read().decode("utf-8", errors="replace"))[:300]
        raise JudgeError(f"Ollama HTTP {exc.code}: {detail}", exc.code) from None
