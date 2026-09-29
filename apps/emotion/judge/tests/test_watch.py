# -*- coding: utf-8 -*-
import json
import os
import time

import pytest

from apps.emotion.judge import watch
from apps.emotion.judge.backends.base import JudgeError
from apps.emotion.judge.watch import (PoliteBackend, describe, main, parse_live_sessions, parse_llama_busy,
                                      pending_sessions, run_once)

NOW = 1_000_000.0
ENDED = [{"t": 1.0, "kind": "assistant", "text": "哪里不舒服？"},
         {"t": 2.0, "kind": "user", "text": "胃疼两天了"},
         {"t": 3.0, "kind": "summary", "doctor": "## 医生参考版 ...", "patient": "..."}]
ONGOING = [{"t": 1.0, "kind": "assistant", "text": "哪里不舒服？"}, {"t": 2.0, "kind": "user", "text": "头晕"}]
NO_PATIENT = [{"t": 1.0, "kind": "assistant", "text": "您好"}]


def _dirs(tmp_path):
    rec, out = tmp_path / "rec", tmp_path / "out"
    rec.mkdir()
    out.mkdir()
    return rec, out


def _write(path, events, mtime=None):
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _write_half(path, events, mtime=None):
    """最后一行只写了一半、断在汉字中间：数字人还没写完就被读到。"""
    data = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode("utf-8")
    half = json.dumps({"t": 9.0, "kind": "user", "text": "还有点头晕"}, ensure_ascii=False).encode("utf-8")[:-3]
    path.write_bytes(data + half)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class AlwaysAnswer:
    source = "local:test"

    def ask(self, state, questions):
        answers = {}
        for name, q in questions.items():
            if q["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 0.9}
            elif q["type"] == "choice":
                answers[name] = {"type": "choice", "choice": list(q["criteria"])[0], "confidence": 0.9}
            else:
                answers[name] = {"type": "score", "score": 5, "confidence": 0.9}
        return {"answers": answers, "usage": {}, "source": self.source}


class Down:
    source = "local:down"

    def ask(self, state, questions):
        raise JudgeError("llama-server 不在线")


def test_pending_takes_ended_or_idle_sessions_that_have_patient_speech(tmp_path):
    rec, out = _dirs(tmp_path)
    _write(rec / "ended.jsonl", ENDED, mtime=NOW - 10)         # 出现 summary：刚结束也判断
    _write(rec / "idle.jsonl", ONGOING, mtime=NOW - 400)       # 没 summary，但 400 秒没动静
    _write(rec / "live.jsonl", ONGOING, mtime=NOW - 20)        # 还在问，不打断
    _write(rec / "silent.jsonl", NO_PATIENT, mtime=NOW - 400)  # 患者没开口，没什么可判断
    assert sorted(sid for sid, _ in pending_sessions(rec, out, now=NOW, idle_s=180)) == ["ended", "idle"]


def test_pending_skips_up_to_date_result_and_rejudges_a_record_that_changed(tmp_path):
    rec, out = _dirs(tmp_path)
    _write(rec / "a.jsonl", ENDED, mtime=NOW - 100)
    (out / "a.judge.json").write_text("{}", encoding="utf-8")
    os.utime(out / "a.judge.json", (NOW - 50, NOW - 50))
    assert pending_sessions(rec, out, now=NOW, idle_s=180) == []
    os.utime(rec / "a.jsonl", (NOW - 10, NOW - 10))  # 判断之后记录又更新了
    assert [sid for sid, _ in pending_sessions(rec, out, now=NOW, idle_s=180)] == ["a"]


def test_run_once_writes_console_readable_result_then_has_nothing_left(tmp_path):
    rec, out = _dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    done = run_once(rec, out, AlwaysAnswer(), now=NOW, idle_s=180)
    assert [(d["session_id"], d["status"]) for d in done] == [("s1", "ok")]
    data = json.loads((out / "s1.judge.json").read_text(encoding="utf-8"))
    assert data["hits"] and data["hits"][0]["t"] == 2.0  # 控制台靠 t 对回原句
    assert (out / "s1.judge.html").is_file()
    assert run_once(rec, out, AlwaysAnswer(), now=NOW + 1, idle_s=180) == []


def test_all_failed_judgement_writes_nothing_and_backs_off(tmp_path):
    rec, out = _dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    failures = {}
    done = run_once(rec, out, Down(), now=NOW, idle_s=180, failures=failures)
    assert done[0]["status"] == "failed" and not (out / "s1.judge.json").exists()
    assert run_once(rec, out, Down(), now=NOW + 60, idle_s=180, failures=failures) == []  # 退避中
    done = run_once(rec, out, AlwaysAnswer(), now=NOW + 700, idle_s=180, failures=failures)
    assert done[0]["status"] == "ok"


def test_record_growing_during_judgement_is_judged_again(tmp_path):
    rec, out = _dirs(tmp_path)
    path = rec / "s1.jsonl"
    _write(path, ENDED, mtime=NOW - 10)

    class Appender(AlwaysAnswer):
        def ask(self, state, questions):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": 9.0, "kind": "user", "text": "还有一点"}, ensure_ascii=False) + "\n")
            return super().ask(state, questions)

    run_once(rec, out, Appender(), now=NOW, idle_s=180)
    assert [sid for sid, _ in pending_sessions(rec, out, now=time.time() + 1, idle_s=180)] == ["s1"]


def test_polite_backend_waits_until_llm_and_avatar_are_idle():
    states = iter([True, True, False])
    slept = []
    inner = AlwaysAnswer()
    got = PoliteBackend(inner, is_busy=lambda: next(states), sleep=slept.append, poll_s=2.0, max_wait_s=60).ask(
        {"chat": {}}, {"q": {"type": "noul"}})
    assert slept == [2.0, 2.0] and got["source"] == "local:test"


def test_polite_backend_stops_waiting_after_max_wait():
    slept = []
    PoliteBackend(AlwaysAnswer(), is_busy=lambda: True, sleep=slept.append, poll_s=5.0, max_wait_s=12).ask(
        {"chat": {}}, {"q": {"type": "noul"}})
    assert sum(slept) >= 12


def test_llama_metrics_busy_when_processing_or_deferred():
    assert parse_llama_busy("llamacpp:requests_processing 1\nllamacpp:requests_deferred 0\n") is True
    assert parse_llama_busy("llamacpp:requests_processing 0\nllamacpp:requests_deferred 2\n") is True
    assert parse_llama_busy("# HELP x\nllamacpp:requests_processing 0\nllamacpp:requests_deferred 0\n") is False
    assert parse_llama_busy("garbage") is False


def test_live_sessions_counted_from_livetalking_admin_payload():
    assert parse_live_sessions({"data": {"sessions": [{"sessionid": "a", "idle": 3}, {"sessionid": "b"}]}}) == 2
    assert parse_live_sessions({}) == 0 and parse_live_sessions(None) == 0 and parse_live_sessions([1]) == 0


def test_cli_once_judges_and_logs_without_patient_words(tmp_path, capsys):
    rec, out = _dirs(tmp_path)
    _write(rec / "abcdef123456.jsonl", ENDED, mtime=NOW - 10)
    assert main(["--once", "--consult-dir", str(rec), "--out-dir", str(out)], backend=AlwaysAnswer()) == 0
    assert (out / "abcdef123456.judge.json").is_file()
    printed = capsys.readouterr().out
    assert "abcdef12" in printed and "胃疼" not in printed  # 日志只写会话编号和数字


# ---- #12 M1：一条会话出错不能让常驻进程退出 ----

def test_half_written_utf8_record_does_not_stop_the_watch(tmp_path):
    rec, out = _dirs(tmp_path)
    _write_half(rec / "a_half.jsonl", ENDED, mtime=NOW - 10)
    _write(rec / "b_good.jsonl", ENDED, mtime=NOW - 10)
    done = run_once(rec, out, AlwaysAnswer(), now=NOW, idle_s=180)
    assert [(d["session_id"], d["status"]) for d in done] == [("a_half", "ok"), ("b_good", "ok")]
    assert (out / "a_half.judge.json").is_file() and (out / "b_good.judge.json").is_file()


def test_session_that_raises_is_backed_off_and_the_rest_are_still_judged(tmp_path, monkeypatch):
    rec, out = _dirs(tmp_path)
    _write_half(rec / "a_half.jsonl", ENDED, mtime=NOW - 10)
    _write(rec / "b_good.jsonl", ENDED, mtime=NOW - 10)

    def strict_reader(path):  # 修复前 sources 的读法：严格 UTF-8，半行就抛
        path.read_text(encoding="utf-8")
        return {"session_id": path.stem, "turns": []}

    real_reader = watch.from_consult_record
    monkeypatch.setattr(watch, "from_consult_record",
                        lambda path: strict_reader(path) if path.stem == "a_half" else real_reader(path))
    failures = {}
    done = run_once(rec, out, AlwaysAnswer(), now=NOW, idle_s=180, failures=failures)
    assert [(d["session_id"], d["status"]) for d in done] == [("a_half", "error"), ("b_good", "ok")]
    assert done[0]["error"] == "UnicodeDecodeError" and "a_half" in failures
    assert (out / "b_good.judge.json").is_file() and not (out / "a_half.judge.json").exists()
    assert run_once(rec, out, AlwaysAnswer(), now=NOW + 60, idle_s=180, failures=failures) == []  # 退避中
    monkeypatch.setattr(watch, "from_consult_record", real_reader)
    done = run_once(rec, out, AlwaysAnswer(), now=NOW + 700, idle_s=180, failures=failures)
    assert [(d["session_id"], d["status"]) for d in done] == [("a_half", "ok")] and "a_half" not in failures


def test_unexpected_error_is_logged_by_class_only_without_patient_words(tmp_path, capsys):
    rec, out = _dirs(tmp_path)
    _write(rec / "abcdef123456.jsonl", ENDED, mtime=NOW - 10)
    _write(rec / "zz_good.jsonl", [{"t": 1.0, "kind": "user", "text": "头晕"}, {"t": 2.0, "kind": "summary"}],
           mtime=NOW - 10)

    class Crashy(AlwaysAnswer):
        def ask(self, state, questions):
            text = state["chat"]["messages"][-1]["text"]
            if text == "胃疼两天了":
                raise RuntimeError(f"意外：{text}")  # 不是 JudgeError，engine 接不住
            return super().ask(state, questions)

    assert main(["--once", "--consult-dir", str(rec), "--out-dir", str(out)], backend=Crashy()) == 0
    printed = capsys.readouterr().out
    assert "abcdef12" in printed and "RuntimeError" in printed and "胃疼" not in printed
    assert (out / "zz_good.judge.json").is_file()


def test_watch_loop_survives_an_unexpected_error_in_one_round(tmp_path, monkeypatch, capsys):
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("磁盘抖了一下")
        return []

    class Stop(BaseException):
        pass

    def sleep(_seconds):
        if len(calls) >= 2:
            raise Stop

    monkeypatch.setattr(watch, "run_once", flaky)
    argv = ["--consult-dir", str(tmp_path), "--out-dir", str(tmp_path / "out")]
    with pytest.raises(Stop):
        main(argv, backend=AlwaysAnswer(), sleep=sleep)
    assert len(calls) == 2  # 第一轮出错后照常进入第二轮
    printed = capsys.readouterr().out
    assert "OSError" in printed and "磁盘" not in printed
    calls.clear()
    assert main(argv + ["--once"], backend=AlwaysAnswer()) == 1  # --once 这一轮出错：不抛，退出码非 0


# ---- #12 M2：部分失败的结果照常写出，但要定时重判 ----

class HalfDown(AlwaysAnswer):
    """情绪组正常、医疗组出错：一半判断失败。"""

    def ask(self, state, questions):
        if "risk_clue" in questions:
            raise JudgeError("超时")
        return super().ask(state, questions)


def test_partial_failure_is_written_for_the_doctor_and_judged_again_later(tmp_path):
    rec, out = _dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    failures = {}
    done = run_once(rec, out, HalfDown(), now=NOW, idle_s=180, failures=failures)
    assert done[0]["status"] == "partial" and done[0]["errors"] == 1 and "s1" in failures
    assert "稍后重判" in describe(done[0])
    data = json.loads((out / "s1.judge.json").read_text(encoding="utf-8"))
    assert data["errors"] == 1 and data["hits"]  # 判到的先给医生看
    assert run_once(rec, out, HalfDown(), now=NOW + 60, idle_s=180, failures=failures) == []  # 退避中
    done = run_once(rec, out, HalfDown(), now=NOW + 700, idle_s=180, failures=failures)  # 到点重判，仍部分失败
    assert [(d["session_id"], d["status"]) for d in done] == [("s1", "partial")] and "s1" in failures
    done = run_once(rec, out, AlwaysAnswer(), now=NOW + 1400, idle_s=180, failures=failures)
    assert [(d["session_id"], d["status"]) for d in done] == [("s1", "ok")] and "s1" not in failures
    assert json.loads((out / "s1.judge.json").read_text(encoding="utf-8"))["errors"] == 0  # 覆盖成完整结果
    assert run_once(rec, out, AlwaysAnswer(), now=NOW + 2100, idle_s=180, failures=failures) == []  # 判全了不再判


def test_unfinished_result_on_disk_is_judged_again_after_a_restart(tmp_path):
    # 服务重启后 failures 是空的：只凭磁盘上的 judge.json——errors > 0 或解析不了的都要重判
    rec, out = _dirs(tmp_path)
    for sid in ("broken", "clean", "partial"):
        _write(rec / f"{sid}.jsonl", ENDED, mtime=NOW - 100)
    (out / "clean.judge.json").write_text(json.dumps({"errors": 0, "hits": []}), encoding="utf-8")
    (out / "partial.judge.json").write_text(json.dumps({"errors": 1, "hits": []}), encoding="utf-8")
    (out / "broken.judge.json").write_text('{"errors": 0, "hi', encoding="utf-8")  # 写了一半
    for p in out.iterdir():
        os.utime(p, (NOW - 50, NOW - 50))  # 结果都比记录新
    assert [sid for sid, _ in pending_sessions(rec, out, now=NOW, idle_s=180)] == ["broken", "partial"]
    failures = {}  # 新进程
    done = run_once(rec, out, HalfDown(), now=NOW, idle_s=180, failures=failures)
    assert [(d["session_id"], d["status"]) for d in done] == [("broken", "partial"), ("partial", "partial")]
    assert run_once(rec, out, HalfDown(), now=NOW + 60, idle_s=180, failures=failures) == []  # 仍按 failures 退避，不空转
    done = run_once(rec, out, AlwaysAnswer(), now=NOW + 700, idle_s=180, failures=failures)
    assert [(d["session_id"], d["status"]) for d in done] == [("broken", "ok"), ("partial", "ok")]
    assert run_once(rec, out, AlwaysAnswer(), now=NOW + 1400, idle_s=180, failures={}) == []  # 判全了，再重启也不重判


# ---- #8 实时摄像头观察：会话结束后生成 observe.json，不经过大模型 ----

def _obs_dirs(tmp_path):
    rec, out = _dirs(tmp_path)
    obs = tmp_path / "obs"
    obs.mkdir()
    return rec, out, obs


def _frames(path, n=20, t0=1.0, mtime=None):
    """n 帧没有检出的空帧（f / p 都是 null）：够 live.py 生成段落，不依赖具体数值。"""
    path.write_text("".join(json.dumps({"t": t0 + i / 5, "f": None, "p": None}) + "\n" for i in range(n)),
                    encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_observe_is_built_for_an_ended_session_with_frames(tmp_path):
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 10)
    _write(rec / "s2.jsonl", ONGOING, mtime=NOW - 20)            # 还在问：不生成
    _frames(obs / "s2.frames.jsonl", mtime=NOW - 20)
    _write(rec / "s3.jsonl", ENDED, mtime=NOW - 10)              # 没开摄像头：不生成
    done = watch.run_observe(rec, obs, out, now=NOW, idle_s=180)
    assert [(d["session_id"], d["status"]) for d in done] == [("s1", "observe")]
    data = json.loads((out / "s1.observe.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == "face_body-live-0.1" and [s["t"] for s in data["segments"]] == [2.0]
    assert not (out / "s2.observe.json").exists() and not (out / "s3.observe.json").exists()
    assert "s1 同期观察已生成：1 段回答" in describe(done[0])


def test_observe_is_not_rebuilt_until_frames_or_record_change(tmp_path):
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 100)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 100)
    assert len(watch.run_observe(rec, obs, out, now=NOW, idle_s=180)) == 1
    assert watch.run_observe(rec, obs, out, now=NOW + 30, idle_s=180) == []   # 没变化：不重算
    later = (out / "s1.observe.json").stat().st_mtime + 5
    _frames(obs / "s1.frames.jsonl", n=30, mtime=later)                       # 问诊结束后又到了一批帧
    assert [d["status"] for d in watch.run_observe(rec, obs, out, now=NOW + 60, idle_s=180)] == ["observe"]


def test_observe_error_is_logged_by_class_and_does_not_block_judge(tmp_path, monkeypatch, capsys):
    from apps.emotion.face_body import live
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "abcdef123456.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "abcdef123456.frames.jsonl", mtime=NOW - 10)

    def boom(*args, **kwargs):
        raise ValueError("胃疼两天了")  # 异常文本可能带对话内容：日志只能有类名

    monkeypatch.setattr(live, "observe_session", boom)
    argv = ["--once", "--consult-dir", str(rec), "--out-dir", str(out), "--obs-dir", str(obs)]
    assert main(argv, backend=AlwaysAnswer()) == 0
    printed = capsys.readouterr().out
    assert "同期观察出错：ValueError" in printed and "胃疼" not in printed
    assert (out / "abcdef123456.judge.json").is_file() and not (out / "abcdef123456.observe.json").exists()


def test_failed_observe_is_not_retried_on_the_same_data(tmp_path, monkeypatch):
    from apps.emotion.face_body import live
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 10)
    real = live.observe_session
    monkeypatch.setattr(live, "observe_session", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    failures = {}
    assert [d["status"] for d in watch.run_observe(rec, obs, out, now=NOW, failures=failures)] == ["observe_error"]
    monkeypatch.setattr(live, "observe_session", real)
    assert watch.run_observe(rec, obs, out, now=NOW + 30, failures=failures) == []  # 同样的数据：不空转
    _frames(obs / "s1.frames.jsonl", n=25, mtime=NOW + 40)
    assert [d["status"] for d in watch.run_observe(rec, obs, out, now=NOW + 60, failures=failures)] == ["observe"]


def test_observe_is_written_even_when_the_judge_backend_is_down(tmp_path):
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "s1.jsonl", ENDED, mtime=NOW - 10)
    _frames(obs / "s1.frames.jsonl", mtime=NOW - 10)
    argv = ["--once", "--consult-dir", str(rec), "--out-dir", str(out), "--obs-dir", str(obs)]
    assert main(argv, backend=Down()) == 0  # 大模型不在线：judge 失败退避，同期观察照常生成
    assert (out / "s1.observe.json").is_file() and not (out / "s1.judge.json").exists()


def test_observe_keeps_running_while_judge_waits_for_a_live_consultation(tmp_path):
    # 评审发现：judge 给正在进行的下一场问诊让路（最多 --max-wait）时，主循环卡在 judge 里，
    # 刚结束的会话要等 judge 跑完才生成同期观察。常驻模式下同期观察必须照常按轮生成。
    import threading
    rec, out, obs = _obs_dirs(tmp_path)
    _write(rec / "a.jsonl", ENDED, mtime=time.time() - 10)   # A 已结束，judge A 会被卡住
    release = threading.Event()

    class Waiting(Down):
        def ask(self, state, questions):
            release.wait(10)                                  # 相当于 PoliteBackend 在等数字人空闲
            return super().ask(state, questions)

    class Stop(BaseException):
        pass

    def stop(_seconds):
        raise Stop

    argv = ["--consult-dir", str(rec), "--out-dir", str(out), "--obs-dir", str(obs), "--interval", "0.2"]
    t = threading.Thread(target=lambda: pytest.raises(Stop, main, argv, backend=Waiting(), sleep=stop), daemon=True)
    t.start()
    try:
        time.sleep(0.5)                                       # judge A 已经在等了
        _write(rec / "b.jsonl", ENDED, mtime=time.time())     # B 此时结束，开过摄像头
        _frames(obs / "b.frames.jsonl")
        deadline = time.time() + 3
        while not (out / "b.observe.json").exists() and time.time() < deadline:
            time.sleep(0.1)
        assert (out / "b.observe.json").is_file()
    finally:
        release.set()
        t.join(15)
