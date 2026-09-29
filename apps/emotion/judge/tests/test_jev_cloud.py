# -*- coding: utf-8 -*-
import io
import json
import urllib.error

import pytest

from apps.emotion.judge.backends import jev_cloud
from apps.emotion.judge.backends.base import JudgeError
from apps.emotion.judge.backends.jev_cloud import JevCloudBackend, cloud_enabled
from apps.emotion.judge.questions_emotion import QUESTIONS as EMOTION
from apps.emotion.judge.state import build_state

STATE = build_state([{"role": "agent", "text": "最近睡眠怎么样？", "question_id": "sleep"},
                     {"role": "patient", "text": "还行吧。"}], focus=1)
STATE["channels"] = {"voice": "语速偏慢"}  # 决赛才会有的字段，云端不该收到

REPLY = {"answers": {"literal_answer": {"type": "noul", "noul": 0.3}},
         "usage": {"input_tokens": 5, "output_tokens": 2}}


class FakeUrlopen:
    def __init__(self, statuses=(200,)):
        self.statuses, self.requests = list(statuses), []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        status = self.statuses.pop(0)
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(b'{"error":"x"}'))
        return _Resp(json.dumps(REPLY).encode("utf-8"))


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_cloud_disabled_without_flag_or_key(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert cloud_enabled(True) is False
    monkeypatch.setenv("JEV_API_KEY", "k")
    assert cloud_enabled(False) is False
    assert cloud_enabled(True) is True


def test_ask_without_key_raises_before_any_network(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    fake = FakeUrlopen()
    monkeypatch.setattr(jev_cloud, "urlopen", fake)
    with pytest.raises(JudgeError):
        JevCloudBackend().ask(STATE, EMOTION)
    assert fake.requests == []


def test_ask_posts_only_chat_and_questions(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key-1234567")
    fake = FakeUrlopen()
    monkeypatch.setattr(jev_cloud, "urlopen", fake)
    got = JevCloudBackend().ask(STATE, EMOTION)
    req = fake.requests[0]
    body = json.loads(req.data.decode("utf-8"))
    assert req.full_url == jev_cloud.OPENROUTER_DECISIONS
    assert req.headers["Authorization"] == "Bearer test-key-1234567"
    assert body["model"] == jev_cloud.DEFAULT_MODEL
    assert set(body["state"]) == {"chat"}  # channels 不上云
    assert body["questions"] == EMOTION
    assert got["answers"] == REPLY["answers"] and got["usage"] == REPLY["usage"]
    assert got["source"] == f"jev-cloud:{jev_cloud.DEFAULT_MODEL}"


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key-1234567")
    fake = FakeUrlopen(statuses=(429, 429, 200))
    monkeypatch.setattr(jev_cloud, "urlopen", fake)
    monkeypatch.setattr(jev_cloud, "sleep", lambda s: None)
    JevCloudBackend().ask(STATE, EMOTION)
    assert len(fake.requests) == 3


def test_non_retryable_http_error_is_judge_error_with_status(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "test-key-1234567")
    monkeypatch.setattr(jev_cloud, "urlopen", FakeUrlopen(statuses=(401,)))
    with pytest.raises(JudgeError) as info:
        JevCloudBackend().ask(STATE, EMOTION)
    assert info.value.status == 401 and "test-key-1234567" not in str(info.value)
