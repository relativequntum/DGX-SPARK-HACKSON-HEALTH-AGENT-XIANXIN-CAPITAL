# -*- coding: utf-8 -*-
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

SID = "0f3c9a4e-2b7d-4c1a-9e8f-5a6b7c8d9e0f"


def _frame(ct, face=True, pose=True):
    f = {"bs": {k: 0.1 for k in _cam()}, "m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1.5, -2, -45, 1]} if face else None
    p = [[0.5, 0.5, 0.9] for _ in range(25)] if pose else None
    return {"ct": ct, "f": f, "p": p}


def _cam():
    import doctor_service
    return doctor_service.CAM_BLENDSHAPES


def _batch(n=3, sent=1_790_000_000_000, age_ms=400, **kw):
    return {"v": "cam-0.1", "sent_ct": sent, "frames": [_frame(sent - age_ms - 200 * i, **kw) for i in range(n)]}


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_valid_batch_is_appended_with_server_time_and_without_client_time(ds):
    mod, dirs = ds
    client = TestClient(mod.app)
    before = time.time()
    r = client.post(f"/api/observe/{SID}", json=_batch(3))
    after = time.time()
    assert r.status_code == 200 and r.json() == {"ok": True, "accepted": 3}
    rows = _lines(dirs["obs"] / f"{SID}.frames.jsonl")
    assert len(rows) == 3 and all(set(row) == {"t", "f", "p"} for row in rows)
    assert before - 0.4 - 0.01 <= rows[0]["t"] <= after - 0.4 + 0.01   # 采集时刻 = 收到时刻 - 0.4 秒
    assert rows[1]["t"] == pytest.approx(rows[0]["t"] - 0.2, abs=2e-3)
    client.post(f"/api/observe/{SID}", json=_batch(2))
    assert len(_lines(dirs["obs"] / f"{SID}.frames.jsonl")) == 5      # 追加，不覆盖（重连沿用同一会话编号）


def test_browser_clock_far_off_does_not_shift_server_time(ds):
    mod, dirs = ds
    skewed = int((time.time() + 3600) * 1000)   # 患者电脑时钟快了一小时
    assert TestClient(mod.app).post(f"/api/observe/{SID}", json=_batch(1, sent=skewed)).status_code == 200
    (row,) = _lines(dirs["obs"] / f"{SID}.frames.jsonl")
    assert abs(row["t"] - time.time()) < 5


def test_frames_without_face_or_pose_are_kept_as_null(ds):
    mod, dirs = ds
    r = TestClient(mod.app).post(f"/api/observe/{SID}", json=_batch(2, face=False, pose=False))
    assert r.status_code == 200
    assert all(row["f"] is None and row["p"] is None for row in _lines(dirs["obs"] / f"{SID}.frames.jsonl"))


@pytest.mark.parametrize("sid", ["short", "bad.sid.1234", "a" * 65, "..%2F..%2Fetc12"])
def test_bad_session_id_is_rejected(ds, sid):
    mod, dirs = ds
    assert TestClient(mod.app).post(f"/api/observe/{sid}", json=_batch(1)).status_code in (400, 404)
    assert list(dirs["obs"].iterdir()) == []


def _mutate(kind):
    b = _batch(2)
    fr = b["frames"][0]
    if kind == "missing_bs":
        fr["f"]["bs"].pop("jawOpen")
    elif kind == "extra_bs":
        fr["f"]["bs"]["tongueOut"] = 0.1
    elif kind == "short_matrix":
        fr["f"]["m"] = fr["f"]["m"][:15]
    elif kind == "pose_24":
        fr["p"] = fr["p"][:24]
    elif kind == "pose_point_2":
        fr["p"][3] = [0.5, 0.5]
    elif kind == "bool_value":
        fr["f"]["bs"]["eyeBlinkLeft"] = True
    elif kind == "string_value":
        fr["p"][0][0] = "0.5"
    elif kind == "extra_frame_key":
        fr["img"] = "data:image/jpeg;base64,xxxx"   # 任何图像字段都不收
    elif kind == "future_frame":
        fr["ct"] = b["sent_ct"] + 5000
    elif kind == "too_old":
        fr["ct"] = b["sent_ct"] - 120_000
    elif kind == "wrong_version":
        b["v"] = "cam-9"
    elif kind == "no_frames":
        b["frames"] = []
    elif kind == "too_many_frames":
        b["frames"] = [_frame(b["sent_ct"] - 10 * i) for i in range(51)]
    return b


@pytest.mark.parametrize("kind", ["missing_bs", "extra_bs", "short_matrix", "pose_24", "pose_point_2", "bool_value",
                                  "string_value", "extra_frame_key", "future_frame", "too_old", "wrong_version",
                                  "no_frames", "too_many_frames"])
def test_any_bad_field_rejects_the_whole_batch(ds, kind):
    mod, dirs = ds
    r = TestClient(mod.app).post(f"/api/observe/{SID}", json=_mutate(kind))
    assert r.status_code == 400
    assert not (dirs["obs"] / f"{SID}.frames.jsonl").exists()


def test_non_finite_numbers_and_non_json_are_rejected(ds):
    mod, dirs = ds
    client = TestClient(mod.app)
    body = json.dumps(_batch(1)).replace("0.1", "NaN", 1)
    headers = {"Content-Type": "application/json"}
    assert client.post(f"/api/observe/{SID}", content=body, headers=headers).status_code == 400
    assert client.post(f"/api/observe/{SID}", content=b"\xff\xfe", headers=headers).status_code == 400
    assert not (dirs["obs"] / f"{SID}.frames.jsonl").exists()


def test_oversized_body_and_full_file_return_413(ds, monkeypatch):
    mod, dirs = ds
    client = TestClient(mod.app)
    big = json.dumps(_batch(2)) + " " * (mod.OBS_MAX_BODY + 1)
    r = client.post(f"/api/observe/{SID}", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    monkeypatch.setattr(mod, "OBS_MAX_FILE", 3000)
    assert client.post(f"/api/observe/{SID}", json=_batch(1)).status_code == 200
    path = dirs["obs"] / f"{SID}.frames.jsonl"
    size = path.stat().st_size
    assert client.post(f"/api/observe/{SID}", json=_batch(3)).status_code == 413
    assert path.stat().st_size == size   # 超限的那批一条都不写


def test_observe_switched_off_returns_404(ds, monkeypatch):
    mod, dirs = ds
    monkeypatch.setenv("DOCTOR_OBSERVE", "0")
    client = TestClient(mod.app)
    assert client.post(f"/api/observe/{SID}", json=_batch(1)).status_code == 404
    assert client.get("/health").json()["observe_enabled"] is False
    assert list(dirs["obs"].iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="Windows 没有 POSIX 权限位")
def test_frames_file_is_owner_only(ds, tmp_path, monkeypatch):
    mod, dirs = ds
    fresh = tmp_path / "fresh-obs"
    monkeypatch.setattr(mod, "OBS_DIR", str(fresh))
    assert TestClient(mod.app).post(f"/api/observe/{SID}", json=_batch(1)).status_code == 200
    assert (fresh.stat().st_mode & 0o777) == 0o700
    assert ((fresh / f"{SID}.frames.jsonl").stat().st_mode & 0o777) == 0o600


def test_cors_preflight_allows_post_from_the_patient_page(ds):
    mod, _ = ds
    r = TestClient(mod.app).options(f"/api/observe/{SID}", headers={
        "Origin": "http://127.0.0.1:8010", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "content-type" in r.headers["access-control-allow-headers"].lower()


def test_health_reports_observation_settings(ds):
    mod, dirs = ds
    h = TestClient(mod.app).get("/health").json()
    assert h["obs_dir"] == str(dirs["obs"]) and h["obs_dir_exists"] is True and h["observe_enabled"] is True
    assert h["ok"] is True and "judge_dir" in h   # 原有字段不变


OBSERVE = {
    "schema_version": "face_body-live-0.1", "camera_frames": 120,
    "medians": {"gaze_away_ratio": 0.2, "blink_per_min": 12.0, "head_motion_deg_per_frame": 0.5,
                "hand_face_ratio": 0.0, "body_motion_x1000": 0.6},
    "segments": [
        {"t": 1790000020.123456, "interval": [1790000008.0, 1790000020.123], "frames": 60, "face_status": "ok",
         "body_status": "ok", "gaze_away_ratio": 0.3, "blink_count": 3, "blink_per_min": 18.0,
         "head_motion_deg_per_frame": 0.6, "hand_face_ratio": 0.1, "body_motion_x1000": 0.8, "secret": "x"},
        {"t": 1790000035.5, "interval": [1790000022.0, 1790000035.5], "frames": 3, "face_status": "unknown",
         "body_status": "unknown", "gaze_away_ratio": None, "blink_count": None, "blink_per_min": None,
         "head_motion_deg_per_frame": None, "hand_face_ratio": None, "body_motion_x1000": None},
    ],
}
JUDGE = {"generated_at": "2026-09-29T12:00:00+00:00", "review_notice": "待医务人员确认", "schema_version": "judge-0.1",
         "errors": 0, "hits": [{"t": 1790000020.123456, "turn_index": 1, "text": "胃疼", "risk": False},
                               {"t": 1790000099.0, "turn_index": 5, "text": "没有了", "risk": False}]}


def _put(dirs, judge=None, observe=None, frames=False):
    if judge is not None:
        (dirs["judge"] / f"{SID}.judge.json").write_text(json.dumps(judge), encoding="utf-8")
    if observe is not None:
        (dirs["judge"] / f"{SID}.observe.json").write_text(json.dumps(observe), encoding="utf-8")
    if frames:
        (dirs["obs"] / f"{SID}.frames.jsonl").write_text('{"t": 1, "f": null, "p": null}\n', encoding="utf-8")


def test_highlights_attach_the_matching_segment_to_each_hit(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE, observe=OBSERVE, frames=True)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["ready"] is True and h["camera"] is True and h["observe_ready"] is True
    assert h["hits"][0]["observe"]["gaze_away_ratio"] == 0.3 and "secret" not in h["hits"][0]["observe"]
    assert h["hits"][1]["observe"] is None        # 没有对应段
    assert [s["t"] for s in h["observe_segments"]] == [1790000020.123456, 1790000035.5]
    assert h["observe_medians"]["blink_per_min"] == 12.0


def test_highlights_carry_observation_before_judge_is_ready(ds):
    mod, dirs = ds
    _put(dirs, observe=OBSERVE, frames=True)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["ready"] is False and h["hits"] == [] and h["observe_ready"] is True
    assert len(h["observe_segments"]) == 2


def test_session_without_camera_says_so_once_in_the_payload(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["camera"] is False and h["observe_ready"] is False and h["observe_segments"] == []
    assert all(hit["observe"] is None for hit in h["hits"])


def test_camera_on_but_observation_not_built_yet(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE, frames=True)
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["camera"] is True and h["observe_ready"] is False


def test_broken_observe_file_is_treated_as_not_ready(ds):
    mod, dirs = ds
    _put(dirs, judge=JUDGE, frames=True)
    (dirs["judge"] / f"{SID}.observe.json").write_text('{"segments": [', encoding="utf-8")
    h = TestClient(mod.app).get(f"/api/doctor/sessions/{SID}/highlights").json()
    assert h["ready"] is True and h["observe_ready"] is False and h["observe_segments"] == []


def test_existing_read_endpoints_are_unchanged(ds):
    mod, dirs = ds
    (dirs["rec"] / f"{SID}.jsonl").write_text(
        json.dumps({"t": 1790000020.123456, "kind": "user", "text": "胃疼"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    client = TestClient(mod.app)
    d = client.get(f"/api/doctor/sessions/{SID}").json()
    assert d["messages"] == [{"role": "user", "text": "胃疼", "t": 1790000020.123456, "source": ""}]
    assert client.get("/api/doctor/sessions").json()["total"] == 1
    assert client.get("/api/doctor/sessions/..bad/highlights").status_code == 400
    assert client.post("/api/doctor/sessions").status_code == 405   # 只读接口没有写方法


def test_blendshape_list_matches_phase_three():
    np = pytest.importorskip("numpy")  # noqa: F841 - 阶段三模块需要 numpy
    from apps.emotion.face_body.live import CAM_BLENDSHAPES as live_list
    assert tuple(_cam()) == tuple(live_list)


def _asgi_post(app, path, chunks, headers=()):
    """直接按 ASGI 调用，记下服务端实际读了几块请求体（TestClient 会先把请求体整个备好，看不出来）。"""
    import asyncio
    pulled = {"n": 0}

    async def receive():
        i = pulled["n"]
        pulled["n"] += 1
        if i < len(chunks):
            return {"type": "http.request", "body": chunks[i], "more_body": i + 1 < len(chunks)}
        return {"type": "http.disconnect"}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
             "headers": [(b"content-type", b"application/json")] + list(headers),
             "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 18110)}
    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, pulled["n"]


def test_declared_oversized_body_is_refused_before_reading(ds):
    # 评审发现：先把整个请求体读进内存再判 413，任何人都能用一个 1 GB 的请求把服务内存撑爆
    mod, dirs = ds
    status, pulled = _asgi_post(mod.app, f"/api/observe/{SID}", [b"{}"],
                                headers=[(b"content-length", str(10 ** 9).encode())])
    assert status == 413 and pulled == 0
    assert list(dirs["obs"].iterdir()) == []


def test_streamed_oversized_body_stops_reading_at_the_limit(ds):
    mod, dirs = ds
    chunk = b" " * 16384
    status, pulled = _asgi_post(mod.app, f"/api/observe/{SID}", [chunk] * 1000)   # 约 16 MB，不带 Content-Length
    assert status == 413 and pulled <= mod.OBS_MAX_BODY // len(chunk) + 2
    assert list(dirs["obs"].iterdir()) == []


def test_total_size_of_all_sessions_is_capped(ds, monkeypatch):
    # 评审发现：20 MB 上限只按单个会话算，换着会话编号发就能把 Spark 磁盘写满
    mod, dirs = ds
    client = TestClient(mod.app)
    assert client.post(f"/api/observe/{SID}", json=_batch(2)).status_code == 200
    used = (dirs["obs"] / f"{SID}.frames.jsonl").stat().st_size
    monkeypatch.setattr(mod, "OBS_MAX_TOTAL", used + 100)
    other = "another-session-0001"
    assert client.post(f"/api/observe/{other}", json=_batch(2)).status_code == 413
    assert not (dirs["obs"] / f"{other}.frames.jsonl").exists()
    assert client.get("/health").json()["ok"] is True   # 其余接口照常
