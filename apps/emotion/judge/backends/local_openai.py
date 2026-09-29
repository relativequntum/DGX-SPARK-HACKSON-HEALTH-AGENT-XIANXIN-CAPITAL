# -*- coding: utf-8 -*-
"""OpenAI 兼容传输：/v1/chat/completions，目标是 Spark 上阶段二的 llama-server（127.0.0.1:8080/v1）。
本机 Ollama 的 /v1 不认 think:false（实测 2026-09-24：推理吃光上下文、正文为空），本机请用 ollama_native。

约束 JSON（response_format = json_schema）+ 模型自报置信度（设计决策第 8 条）。
模型输出形状（每题一个对象）：noul → {"answer": bool, "confidence"}；choice → {"choice": 选项, "confidence"}；
score → {"score": 0~9, "confidence"}；外加一句 evidence（最能支持判断的原话）。
to_jev_answers() 把它们换成 Jev 形状，engine 就不用区分本地还是云端。
logprobs 后端将来只需替换 to_jev_answers 里的概率来源，接口不变。
"""
from __future__ import annotations

import json
import os

from .base import JudgeError, file_secret, redact_secrets
from .prompt import build_messages, build_schema, to_jev_answers  # noqa: F401  (build_schema 供测试与调用方复用)

DEFAULT_BASE_URL = "http://127.0.0.1:8080/v1"  # Spark 上阶段二的 llama-server；本机 Ollama 请用 ollama_native
DEFAULT_MODEL = "qwen3.6-35b-a3b"


def resolve_api_key(explicit: str | None = None) -> str:
    """显式传入 > 环境变量 LOCAL_LLM_API_KEY > LOCAL_LLM_KEY_FILE 指向的文件 > 占位 "local"（Ollama 不验 key）。
    Spark 上 `source ~/livetalking-deploy/env.sh` 后 LOCAL_LLM_KEY_FILE / LOCAL_LLM_BASE_URL / LOCAL_LLM_MODEL 都有了。"""
    return (explicit or (os.environ.get("LOCAL_LLM_API_KEY") or "").strip()
            or file_secret("LOCAL_LLM_KEY_FILE") or "local")


class LocalOpenAIBackend:
    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: float = 120, client=None,
                 think: bool = False) -> None:
        self.base_url = base_url or os.environ.get("LOCAL_LLM_BASE_URL") or DEFAULT_BASE_URL
        self.model = model or os.environ.get("LOCAL_LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.think = think
        self.source = f"local:{self.model}"
        self._api_key = api_key
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI  # 延迟导入：测试注入假客户端时不需要装 openai

            self._client = OpenAI(base_url=self.base_url, api_key=resolve_api_key(self._api_key),
                                  timeout=self.timeout)
        return self._client

    def ask(self, state: dict, questions: dict) -> dict:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=build_messages(state, questions),
                temperature=0,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "judge", "strict": True,
                                                 "schema": build_schema(questions)}},
                # Ollama 认 think；llama-server 的 Qwen3 模板认 chat_template_kwargs。两家都忽略不认识的字段。
                extra_body={"think": self.think,
                            "chat_template_kwargs": {"enable_thinking": self.think}},
            )
        except Exception as exc:  # openai SDK 的异常族很多，统一成 JudgeError
            raise JudgeError(f"本地模型请求失败: {redact_secrets(exc)}"[:400],
                             status=getattr(exc, "status_code", None)) from None
        content = _content_of(resp)
        try:
            data = json.loads(content)
        except (TypeError, ValueError):
            raise JudgeError(f"本地模型输出不是 JSON: {redact_secrets(content)[:200]}") from None
        if not isinstance(data, dict):
            raise JudgeError("本地模型输出不是 JSON 对象")
        return {
            "answers": to_jev_answers(data.get("answers") or {}, questions),
            "usage": _usage_of(resp),
            "source": self.source,
            "evidence": str(data.get("evidence") or "").strip(),
        }


def _content_of(resp) -> str:
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError):
        raise JudgeError("本地模型没有返回内容") from None


def _usage_of(resp) -> dict:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    return {"input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0}
