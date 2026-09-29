# -*- coding: utf-8 -*-
import json

from apps.emotion.face_body import __main__ as cli
from apps.emotion.face_body.annotate import find_font

REPORT = {"schema_version": "face_body-0.1", "video": "clip.mp4", "duration_s": 1.0, "frames_total": 0,
          "process_fps": None, "face_detect_ratio": 0.0, "pose_detect_ratio": 0.0, "windows": []}


def test_analyze_writes_report_json(tmp_path, monkeypatch, capsys):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"")
    seen = {}

    def fake_analyze(path, model_dir, window, stride):
        seen.update(path=path, model_dir=model_dir, window=window, stride=stride)
        return dict(REPORT)

    monkeypatch.setattr(cli, "analyze_video", fake_analyze)
    code = cli.main(["analyze", str(video), "--out-dir", str(tmp_path / "out"), "--window", "3",
                     "--stride", "2", "--models", str(tmp_path)])
    assert code == 0
    out = json.loads((tmp_path / "out" / "clip.face_body.json").read_text(encoding="utf-8"))
    assert out["schema_version"] == "face_body-0.1"
    assert seen == {"path": video, "model_dir": tmp_path, "window": 3.0, "stride": 2}
    assert "clip.face_body.json" in capsys.readouterr().out


def test_fetch_models_subcommand_passes_dir_and_proxy(tmp_path, monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "fetch_models", lambda d, proxy=None: got.update(d=d, proxy=proxy) or {})
    assert cli.main(["fetch-models", "--models", str(tmp_path), "--proxy", "http://p:1"]) == 0
    assert got == {"d": tmp_path, "proxy": "http://p:1"}


def test_find_font_prefers_env_then_first_existing_candidate(tmp_path, monkeypatch):
    first, second = tmp_path / "a.ttc", tmp_path / "b.ttc"
    second.write_bytes(b"x")
    monkeypatch.delenv("FACE_BODY_FONT", raising=False)
    assert find_font([str(first), str(second)]) == str(second)
    env_font = tmp_path / "env.ttf"
    env_font.write_bytes(b"x")
    monkeypatch.setenv("FACE_BODY_FONT", str(env_font))
    assert find_font([str(second)]) == str(env_font)
    monkeypatch.delenv("FACE_BODY_FONT")
    assert find_font([str(first)]) is None
