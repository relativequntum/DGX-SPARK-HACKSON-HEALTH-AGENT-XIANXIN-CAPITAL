# -*- coding: utf-8 -*-
import pytest

from apps.emotion.judge.backends.base import FallbackBackend, JudgeError


class _Ok:
    source = "ok"

    def ask(self, state, questions):
        return {"answers": {"q": {"type": "noul", "noul": 0.9}}, "usage": {}, "source": self.source}


class _Boom:
    source = "boom"

    def ask(self, state, questions):
        raise JudgeError("down")


def test_fallback_uses_primary_when_it_works():
    got = FallbackBackend(_Ok(), _Boom()).ask({}, {})
    assert got["source"] == "ok"


def test_fallback_switches_to_secondary_on_judge_error():
    got = FallbackBackend(_Boom(), _Ok()).ask({}, {})
    assert got["source"] == "ok" and got["answers"]["q"]["noul"] == 0.9


def test_fallback_raises_when_both_fail():
    with pytest.raises(JudgeError):
        FallbackBackend(_Boom(), _Boom()).ask({}, {})


def test_redact_covers_key_file_contents(tmp_path, monkeypatch):
    from apps.emotion.judge.backends.base import redact_secrets

    key_file = tmp_path / "model-api-key"
    key_file.write_text("sk-file-secret-abcdef\n", encoding="utf-8")
    monkeypatch.setenv("LOCAL_LLM_KEY_FILE", str(key_file))
    assert redact_secrets("boom sk-file-secret-abcdef") == "boom [REDACTED]"
