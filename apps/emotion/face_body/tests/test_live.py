# -*- coding: utf-8 -*-
import json
import math

import numpy as np
import pytest

from apps.emotion.face_body import live
from apps.emotion.face_body.features import AU_MAP
from apps.emotion.face_body.live import (CAM_BLENDSHAPES, SCHEMA_VERSION, answer_intervals, build_observation,
                                         load_events, load_frames, matrix_from_flat, observe_session,
                                         to_frame_record, write_observation)

T0 = 1_790_000_000.0  # 服务器时间（秒），与问诊记录的 t 同一口径


def _mat(yaw=0.0, layout="col", tz=-45.0):
    """已知 yaw 的 4x4 姿态矩阵，按浏览器的排法摊成 16 个数（col = 列主序）。"""
    t = math.radians(yaw)
    c, s = math.cos(t), math.sin(t)
    m = np.array([[c, 0, s, 1.5], [0, 1, 0, -2.0], [-s, 0, c, tz], [0, 0, 0, 1.0]])
    return [float(v) for v in (m.T if layout == "col" else m).reshape(-1)]


def _bs(**kw):
    d = {k: 0.0 for k in CAM_BLENDSHAPES}
    d.update(kw)
    return d


def _pose(hand=False, shift=0.0, shoulders=True):
    p = [[0.5, 0.5, 0.0] for _ in range(25)]
    for i, (x, y) in {0: (0.50, 0.30), 11: (0.62, 0.55), 12: (0.38, 0.55), 15: (0.70, 0.90),
                      16: (0.30, 0.90), 23: (0.58, 0.95), 24: (0.42, 0.95)}.items():
        p[i] = [x + shift, y, 1.0]
    if hand:
        p[15] = [0.52 + shift, 0.32, 1.0]
    if not shoulders:
        p[12][2] = 0.1
    return p


def _frame(t, face=True, pose=True, yaw=0.0, gaze=0.0, blink=0.0, hand=False, shift=0.0):
    f = {"bs": _bs(eyeLookOutLeft=gaze, eyeLookInRight=gaze, eyeBlinkLeft=blink, eyeBlinkRight=blink),
         "m": _mat(yaw)} if face else None
    return {"t": t, "f": f, "p": _pose(hand, shift) if pose else None}


def _session(n=200, **kw):
    """5 fps、从 T0 开始的 n 帧。"""
    return [_frame(T0 + i / 5, **kw) for i in range(n)]


def test_cam_blendshapes_cover_every_blendshape_features_reads():
    used = {"eyeLookOutLeft", "eyeLookInRight", "eyeLookInLeft", "eyeLookOutRight", "eyeLookUpLeft",
            "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight", "eyeBlinkLeft", "eyeBlinkRight"}
    used |= {n for _, names in AU_MAP for n in names}
    assert len(CAM_BLENDSHAPES) == 26 == len(set(CAM_BLENDSHAPES))
    assert set(CAM_BLENDSHAPES) == used


@pytest.mark.parametrize("layout", ["col", "row"])
def test_matrix_layout_is_detected_from_where_the_translation_sits(layout):
    from apps.emotion.face_body.features import euler_from_matrix
    yaw, pitch, roll = euler_from_matrix(matrix_from_flat(_mat(25.0, layout)))
    assert yaw == pytest.approx(25.0, abs=1e-6) and abs(pitch) < 1e-6 and abs(roll) < 1e-6


def test_rotation_only_matrix_falls_back_to_the_declared_layout():
    from apps.emotion.face_body.features import euler_from_matrix
    flat = _mat(25.0, "col", tz=0.0)
    flat[12] = flat[13] = 0.0  # 平移全为 0：看不出行列序
    assert euler_from_matrix(matrix_from_flat(flat, layout="col"))[0] == pytest.approx(25.0, abs=1e-6)
    assert euler_from_matrix(matrix_from_flat(flat, layout="row"))[0] == pytest.approx(-25.0, abs=1e-6)


def test_frame_record_has_the_same_shape_as_offline_frame_record():
    rec = to_frame_record(_frame(T0 + 2.5, yaw=10.0, gaze=0.3, blink=0.6, hand=True), T0)
    assert rec["t"] == pytest.approx(2.5)
    assert rec["face"] is True and rec["pose"] is True
    assert rec["yaw"] == pytest.approx(10.0, abs=1e-6)
    assert rec["gaze_h"] == pytest.approx(0.3) and rec["blink"] == pytest.approx(0.6)
    assert list(rec["au"]) == [name for name, _ in AU_MAP]
    assert rec["hand_face"] is True and "shoulders" not in rec and 11 in rec["kp"]


def test_frame_without_face_or_shoulders_is_not_a_detection():
    rec = to_frame_record({"t": T0, "f": None, "p": None}, T0)
    assert rec == {"t": 0.0, "face": False, "pose": False}
    cut = to_frame_record({"t": T0, "f": None, "p": _pose(shoulders=False)}, T0)
    assert cut["pose"] is False


def test_load_frames_skips_bad_lines_and_sorts_by_server_time(tmp_path):
    path = tmp_path / "s.frames.jsonl"
    rows = [json.dumps({"t": T0 + 1, "f": None, "p": None}), "not json", json.dumps([1, 2]),
            json.dumps({"t": "x", "f": None}), json.dumps({"t": T0, "f": None, "p": None}), '{"t": 17900']
    path.write_text("\n".join(rows), encoding="utf-8")
    assert [r["t"] for r in load_frames(path)] == [T0, T0 + 1]


def test_load_events_keeps_user_with_text_and_assistant(tmp_path):
    path = tmp_path / "s.jsonl"
    evs = [{"t": T0 + 1, "kind": "assistant", "text": "哪里不舒服？"}, {"t": T0 + 2, "kind": "user", "text": " "},
           {"t": T0 + 3, "kind": "user", "text": "胃疼"}, {"t": T0 + 4, "kind": "summary", "doctor": "…"},
           {"kind": "user", "text": "没有时间"}]
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs), encoding="utf-8")
    assert load_events(path) == [{"t": T0 + 1, "kind": "assistant"}, {"t": T0 + 3, "kind": "user"}]


def test_answer_intervals_start_at_the_previous_reply_or_answer_capped_at_60s():
    evs = [{"t": 100.0, "kind": "user"},                                   # 前面只有开场白：往前 60 秒
           {"t": 110.0, "kind": "assistant"}, {"t": 130.0, "kind": "user"},  # 上一句助手回复 → 本句
           {"t": 140.0, "kind": "user"},                                   # 连说两句：从上一句算起
           {"t": 150.0, "kind": "assistant"}, {"t": 300.0, "kind": "user"}]  # 隔太久：最多 60 秒
    assert answer_intervals(evs) == [(40.0, 100.0), (110.0, 130.0), (130.0, 140.0), (240.0, 300.0)]


EVENTS = [{"t": T0 + 8, "kind": "assistant"}, {"t": T0 + 20, "kind": "user"},
          {"t": T0 + 22, "kind": "assistant"}, {"t": T0 + 35, "kind": "user"}]


def test_segments_follow_answers_and_carry_the_exact_event_time():
    obs = build_observation(_session(), EVENTS, session_id="abc12345")
    assert obs["schema_version"] == SCHEMA_VERSION and obs["session_id"] == "abc12345"
    assert [s["t"] for s in obs["segments"]] == [T0 + 20, T0 + 35]  # 原样的 t，医生端按它对回原句
    s1, s2 = obs["segments"]
    assert s1["interval"] == [round(T0 + 8, 3), round(T0 + 20, 3)]
    assert s1["frames"] == 61 and s1["face_status"] == "ok" and s1["body_status"] == "ok"
    assert s1["head_motion_deg_per_frame"] == 0.0 and s1["hand_face_ratio"] == 0.0
    assert obs["camera_frames"] == 200 and obs["face_detect_ratio"] == 1.0 and obs["pose_detect_ratio"] == 1.0
    assert obs["baseline"]["source"] == "first_5s"


def test_gaze_away_blinks_and_hand_to_face_per_segment():
    frames = []
    for i in range(200):
        t = i / 5
        away = t >= 22                        # 第二段目光偏开
        blink = 0.8 if i in (50, 51, 70, 71) else 0.0  # 第一段两次眨眼
        frames.append(_frame(T0 + t, gaze=0.7 if away else 0.0, blink=blink, hand=(t >= 22 and i % 2 == 0)))
    s1, s2 = build_observation(frames, EVENTS)["segments"]
    assert s1["gaze_away_ratio"] == 0.0 and s1["blink_count"] == 2 and s1["blink_per_min"] == 10.0
    assert s2["gaze_away_ratio"] == 1.0 and s2["blink_count"] == 0
    assert s2["hand_face_ratio"] == pytest.approx(0.5, abs=0.02)


def test_segment_without_frames_or_with_too_few_is_unknown_without_numbers():
    few = [_frame(T0 + 19 + i / 5) for i in range(5)]  # 只有 5 帧，且不到半段
    obs = build_observation([_frame(T0)] + few, EVENTS)
    s1, s2 = obs["segments"]
    assert s1["face_status"] == "unknown" and s1["gaze_away_ratio"] is None and s1["blink_per_min"] is None
    assert s2["frames"] == 0 and s2["face_status"] == s2["body_status"] == "unknown"
    assert all(s2[k] is None for k in live.SEGMENT_KEYS)


def test_face_only_and_pose_only_segments():
    face_only = build_observation(_session(pose=False), EVENTS)["segments"][0]
    assert face_only["face_status"] == "ok" and face_only["body_status"] == "unknown"
    assert face_only["gaze_away_ratio"] is not None and face_only["hand_face_ratio"] is None
    pose_only = build_observation(_session(face=False), EVENTS)["segments"][0]
    assert pose_only["face_status"] == "unknown" and pose_only["body_status"] == "ok"
    assert pose_only["gaze_away_ratio"] is None and pose_only["body_motion_x1000"] == 0.0


def test_first_answer_before_any_reply_is_measured_from_camera_start():
    # 开场白不进问诊记录：第一句回答前没有助手事件；摄像头从 T0 开到回答，整段都有帧，应当给数
    obs = build_observation(_session(n=60), [{"t": T0 + 11.8, "kind": "user"}])
    seg = obs["segments"][0]
    assert seg["interval"][0] == round(T0 + 11.8 - 60, 3)
    assert seg["face_status"] == "ok" and seg["frames"] == 60


def test_camera_switched_off_mid_answer_makes_that_segment_unknown():
    frames = _session(n=140)  # 摄像头在第二段中途（T0+27.8）关掉：第二段只覆盖了 5.8 / 13 秒
    s1, s2 = build_observation(frames, EVENTS)["segments"]
    assert s1["face_status"] == "ok"
    assert s2["frames"] == 30 and s2["face_status"] == "unknown" and s2["gaze_away_ratio"] is None


def test_session_medians_skip_unknown_segments():
    frames = []
    for i in range(200):
        t = i / 5
        frames.append(_frame(T0 + t, gaze=0.7 if t >= 22 else 0.0))
    obs = build_observation(frames, EVENTS + [{"t": T0 + 60, "kind": "user"}])  # 第三段没有帧
    assert obs["medians"]["gaze_away_ratio"] == 0.5  # (0.0 + 1.0) / 2，unknown 段不参与
    assert obs["segments"][2]["face_status"] == "unknown"


def test_no_frames_at_all_gives_unknown_segments_and_zero_ratios():
    obs = build_observation([], EVENTS)
    assert obs["camera_frames"] == 0 and obs["face_detect_ratio"] == 0.0 and obs["baseline"] is None
    assert [s["face_status"] for s in obs["segments"]] == ["unknown", "unknown"]


def test_write_observation_replaces_atomically_and_leaves_no_temp_file(tmp_path):
    obs = build_observation(_session(), EVENTS, session_id="abc12345")
    path = write_observation(obs, tmp_path / "out")
    assert path.name == "abc12345.observe.json"
    assert json.loads(path.read_text(encoding="utf-8"))["segments"][0]["t"] == T0 + 20
    write_observation(obs, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["abc12345.observe.json"]


def test_observe_session_and_cli(tmp_path, capsys):
    consult = tmp_path / "abc12345.jsonl"
    consult.write_text("\n".join(json.dumps(dict(e, text="…")) for e in EVENTS), encoding="utf-8")
    frames = tmp_path / "abc12345.frames.jsonl"
    frames.write_text("\n".join(json.dumps(f) for f in _session()), encoding="utf-8")
    path = observe_session(consult, frames, tmp_path / "out")
    assert json.loads(path.read_text(encoding="utf-8"))["session_id"] == "abc12345"
    assert live.main(["--consult", str(consult), "--frames", str(frames), "--out-dir", str(tmp_path / "o2")]) == 0
    assert "2 段回答" in capsys.readouterr().out
