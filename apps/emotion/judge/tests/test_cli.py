# -*- coding: utf-8 -*-
import json

from apps.emotion.judge.__main__ import main, make_backend
from apps.emotion.judge.backends.base import FallbackBackend
from apps.emotion.judge.backends.jev_cloud import JevCloudBackend
from apps.emotion.judge.backends.local_openai import LocalOpenAIBackend
from apps.emotion.judge.backends.ollama_native import OllamaNativeBackend

SESSION = {"session_id": "cli-1", "turns": [
    {"role": "agent", "text": "最近睡眠怎么样？", "question_id": "sleep"},
    {"role": "patient", "text": "还行吧。"},
]}


class StubBackend:
    source = "stub"

    def ask(self, state, questions):
        answers = {}
        for name, q in questions.items():
            if q["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 0.9}
            elif q["type"] == "choice":
                answers[name] = {"type": "choice", "choice": list(q["criteria"])[0], "confidence": 0.9}
            else:
                answers[name] = {"type": "score", "score": 3, "confidence": 0.9}
        return {"answers": answers, "usage": {}, "source": self.source, "evidence": "还行吧"}


def test_main_writes_json_and_html_next_to_each_other(tmp_path, capsys):
    src = tmp_path / "s.json"
    src.write_text(json.dumps(SESSION, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    code = main(["run", str(src), "--out-dir", str(out)], backend=StubBackend())
    assert code == 0
    result = json.loads((out / "cli-1.judge.json").read_text(encoding="utf-8"))
    assert result["schema_version"] == "judge-0.1" and result["hits"]
    html = (out / "cli-1.judge.html").read_text(encoding="utf-8")
    assert "待医务人员确认" in html and "还行吧" in html
    assert "cli-1.judge.html" in capsys.readouterr().out


def test_default_backend_is_local_ollama(monkeypatch):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert isinstance(make_backend(["run", "x.json"]), OllamaNativeBackend)
    assert isinstance(make_backend(["run", "x.json", "--backend", "openai", "--base-url", "http://h/v1"]),
                      LocalOpenAIBackend)


def test_cloud_flag_without_key_stays_local(monkeypatch, capsys):
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    backend = make_backend(["run", "x.json", "--cloud"])
    assert isinstance(backend, OllamaNativeBackend)
    assert "JEV_API_KEY" in capsys.readouterr().err


def test_cloud_flag_with_key_puts_cloud_first_and_local_as_fallback(monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "k-1234567890")
    backend = make_backend(["run", "x.json", "--cloud"])
    assert isinstance(backend, FallbackBackend)
    assert isinstance(backend.primary, JevCloudBackend) and isinstance(backend.secondary, OllamaNativeBackend)
