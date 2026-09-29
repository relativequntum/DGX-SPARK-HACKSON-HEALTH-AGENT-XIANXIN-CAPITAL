# -*- coding: utf-8 -*-
import json

import pytest

from apps.emotion.judge.sources import load_session


def _write_jsonl(path, events, tail=""):
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n" + tail, encoding="utf-8")


def test_consult_record_maps_user_to_patient_and_assistant_to_agent(tmp_path):
    # 阶段二数字人 consult_recorder 的落盘格式：每行一个事件，文件顺序即时间顺序
    path = tmp_path / "aebe41c6.jsonl"
    _write_jsonl(path, [
        {"t": 1.0, "kind": "user", "text": "你好"},
        {"t": 2.0, "kind": "assistant", "text": "您好，今天哪里不舒服？", "provider": "openclaw"},
        {"t": 3.0, "kind": "user", "text": "胃疼两天了"},
    ])
    session = load_session(path)
    assert session["session_id"] == "aebe41c6"
    assert session["source"] == "consult_recorder"
    assert [(t["role"], t["text"]) for t in session["turns"]] == [
        ("patient", "你好"), ("agent", "您好，今天哪里不舒服？"), ("patient", "胃疼两天了")]


def test_consult_record_skips_summary_empty_text_and_bad_lines(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [
        {"t": 1.0, "kind": "assistant", "text": "请说说症状。"},
        {"t": 2.0, "kind": "summary", "doctor": "## 医生参考版 ...", "patient": "..."},
        {"t": 3.0, "kind": "assistant", "text": "   "},
        {"t": 4.0, "kind": "user", "text": "头晕"},
    ], tail="not json\n\n[1, 2]\n")
    assert [(t["role"], t["text"]) for t in load_session(path)["turns"]] == [
        ("agent", "请说说症状。"), ("patient", "头晕")]


def test_json_session_and_bare_turn_list_still_load(tmp_path):
    full = tmp_path / "a.json"
    full.write_text(json.dumps({"session_id": "x1", "turns": [{"role": "patient", "text": "嗯"}]},
                               ensure_ascii=False), encoding="utf-8")
    bare = tmp_path / "b.json"
    bare.write_text(json.dumps([{"role": "patient", "text": "嗯"}], ensure_ascii=False), encoding="utf-8")
    assert load_session(full)["session_id"] == "x1"
    assert load_session(bare)["session_id"] == "b" and load_session(bare)["turns"][0]["text"] == "嗯"


def test_consult_record_keeps_event_time_for_matching_back_to_the_console(tmp_path):
    path = tmp_path / "s.jsonl"
    _write_jsonl(path, [{"t": 1.5, "kind": "assistant", "text": "哪里不舒服？"},
                        {"t": 2.25, "kind": "user", "text": "胃疼"}])
    assert [t["t"] for t in load_session(path)["turns"]] == [1.5, 2.25]


def test_consult_record_with_half_written_utf8_line_still_loads(tmp_path):
    # 数字人写了半行就被读到：最后一行断在汉字中间，不能抛 UnicodeDecodeError（#12 M1）
    path = tmp_path / "s.jsonl"
    good = json.dumps({"t": 1.0, "kind": "user", "text": "胃疼两天了"}, ensure_ascii=False) + "\n"
    half = json.dumps({"t": 2.0, "kind": "user", "text": "还有点头晕"}, ensure_ascii=False).encode("utf-8")[:-3]
    path.write_bytes(good.encode("utf-8") + half)
    with pytest.raises(UnicodeDecodeError):
        path.read_text(encoding="utf-8")  # 确认确实断在多字节字符中间
    assert [(t["role"], t["text"]) for t in load_session(path)["turns"]] == [("patient", "胃疼两天了")]
