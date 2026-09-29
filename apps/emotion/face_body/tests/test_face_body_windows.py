# -*- coding: utf-8 -*-
import pytest

from apps.emotion.face_body.windows import (MIN_FRAMES, SCHEMA_VERSION, aggregate, build_report, count_blinks,
                                            individual_baseline, rolling_median, stat, window_edges)


def _face(t, gaze_h=0.0, blink=0.0, yaw=0.0, smile=0.0):
    return {"t": t, "face": True, "pose": False, "yaw": yaw, "pitch": 0.0, "roll": 0.0,
            "gaze_h": gaze_h, "gaze_v": 0.0, "blink": blink, "au": {"AU12 嘴角上扬": smile}}


def _no_face(t):
    return {"t": t, "face": False, "pose": False}


def _body(t, hand=False, shift=0.0):
    return {"t": t, "face": False, "pose": True, "shoulder_tilt": 0.0, "shoulder_w": 0.24, "torso_lean": 0.0,
            "hand_face": hand, "kp": {0: (0.5 + shift, 0.5), 11: (0.4 + shift, 0.6)}}


def test_stat_ignores_missing_values():
    assert stat([1, None, float("nan"), 3]) == {"mean": 2.0, "std": 1.0, "n": 2}
    assert stat([]) == {"mean": None, "std": None, "n": 0}


def test_rolling_median_removes_single_frame_spikes():
    assert rolling_median([0, 0, 10, 0, 0], k=3) == [0, 0, 0, 0, 0]


def test_blink_count_uses_hysteresis():
    # 0.45 仍算闭着（没降到 0.3 以下），不重复计数
    assert count_blinks([0.1, 0.6, 0.45, 0.6, 0.2, 0.7, 0.1]) == 2


def test_baseline_uses_first_seconds_with_face():
    frames = [_face(i / 10, gaze_h=0.1 if i < 50 else 0.9) for i in range(100)]
    base = individual_baseline(frames, seconds=5.0)
    assert base["gaze_h"] == pytest.approx(0.1) and base["source"] == "first_5s"


def test_baseline_falls_back_to_all_face_frames_and_none_without_face():
    frames = [_no_face(i / 10) for i in range(60)] + [_face(6 + i / 10, gaze_h=0.4) for i in range(10)]
    assert individual_baseline(frames)["source"] == "all_frames"
    assert individual_baseline([_no_face(0.0), _no_face(0.1)]) is None


def test_window_with_too_few_face_frames_is_unknown_without_face_metrics():
    frames = [_face(i / 10) for i in range(50)]
    frames += [_face(5 + i / 10) if i < 15 else _no_face(5 + i / 10) for i in range(50)]
    wins = aggregate(frames, window=5.0)
    assert [w["face_status"] for w in wins] == ["ok", "unknown"]
    assert all(k in wins[0] for k in ("head", "gaze", "blink", "au_proxy"))
    assert not any(k in wins[1] for k in ("head", "gaze", "blink", "au_proxy"))
    assert wins[1]["face_ratio"] == 0.3


def test_gaze_away_ratio_is_relative_to_individual_baseline():
    frames = [_face(i / 10, gaze_h=0.2) for i in range(50)]
    frames += [_face(5 + i / 10, gaze_h=0.2 if i < 25 else 0.7) for i in range(50)]
    wins = aggregate(frames, window=5.0)
    assert wins[0]["gaze"]["away_ratio"] == 0.0
    assert wins[1]["gaze"]["away_ratio"] == pytest.approx(0.5)
    assert wins[1]["gaze"]["baseline"]["h"] == pytest.approx(0.2)


def test_blink_rate_and_au_mean_per_window():
    blinks = [0.0] * 51
    for j in (5, 20, 35):
        blinks[j] = 0.9
    frames = [_face(i / 10, blink=blinks[i], smile=0.4 if i % 2 == 0 else 0.2) for i in range(51)]
    (w,) = aggregate(frames, window=5.0)  # 时长正好 5 秒：最后一帧也归进这个窗
    assert w["frames"] == 51
    assert w["blink"] == {"count": 3, "per_min": 36.0}
    assert w["au_proxy"]["AU12 嘴角上扬"] == pytest.approx(0.302, abs=1e-3)


def test_body_window_reports_hand_to_face_ratio_and_motion():
    frames = [_body(i / 10, hand=i < 13, shift=0.001 * i) for i in range(51)]
    (w,) = aggregate(frames, window=5.0)
    assert w["body_status"] == "ok" and w["face_status"] == "unknown"
    assert w["body"]["hand_face_ratio"] == pytest.approx(13 / 51, abs=0.01)
    assert w["body"]["motion_x1000"] == pytest.approx(1.0)


def test_report_carries_schema_notice_and_detection_ratios():
    frames = [_face(i / 10) for i in range(30)] + [_no_face(3 + i / 10) for i in range(21)]
    report = build_report(frames, window=5.0)
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["window_s"] == 5.0
    assert report["min_frames"] == MIN_FRAMES == 10
    assert report["face_detect_ratio"] == pytest.approx(30 / 51, abs=0.01)
    assert report["pose_detect_ratio"] == 0.0
    assert "不做人脸识别" in report["notice"]
    assert report["baseline"]["source"] == "first_5s"
    assert len(report["windows"]) == 1


def test_body_motion_compares_the_same_joints_across_frames():
    # 第二帧多了一个可见关节：只比两帧都可见的关节，新出现的关节不算位移
    frames = [dict(_body(0.0), kp={0: (0.5, 0.5)}), dict(_body(0.1), kp={11: (0.9, 0.9), 0: (0.501, 0.5)}),
              dict(_body(0.2), kp={11: (0.9, 0.9), 0: (0.502, 0.5)})]
    # 补满 5 秒（不足半个窗长的整段会记 unknown）；补的帧没有可见关节，不产生位移
    frames += [dict(_body(i / 10), kp={}) for i in range(3, 51)]
    (w,) = aggregate(frames, window=5.0)
    assert w["body"]["motion_x1000"] == pytest.approx(0.75)  # 第一对 1.0（只有关节 0），第二对 (1.0+0)/2


def test_window_edges_merge_a_short_tail_but_keep_exact_multiples():
    assert window_edges(10.0, 5.0) == [(0.0, 5.0), (5.0, 10.0)]            # 正好整数倍：不多出空窗
    assert window_edges(10.04, 5.0) == [(0.0, 5.0), (5.0, 10.04)]          # 尾巴 0.04 秒：并入前一窗
    assert window_edges(12.5, 5.0) == [(0.0, 5.0), (5.0, 10.0), (10.0, 12.5)]  # 正好半个窗长：单独成窗
    assert window_edges(2.0, 5.0) == [(0.0, 2.0)]                          # 只有一窗：不并，由状态判定记 unknown
    assert window_edges(0.0, 5.0) == []


def test_short_trailing_window_does_not_report_its_own_numbers():
    # 25 fps、252 帧：末尾 [10.0, 10.04] 只有 2 帧、恰好闭眼。旧逻辑单独成窗、标 ok，得出每分钟 1500 次眨眼
    frames = [_face(i / 25, blink=0.9 if i >= 250 else 0.0) for i in range(252)]
    wins = aggregate(frames, window=5.0)
    assert [(w["t0"], w["t1"], w["frames"]) for w in wins] == [(0.0, 5.0, 125), (5.0, 10.0, 127)]
    assert wins[1]["face_status"] == "ok"
    assert wins[1]["blink"] == {"count": 1, "per_min": round(60 / 5.04, 1)}


def test_clip_shorter_than_half_a_window_is_unknown():
    frames = [{**_body(i / 25), **_face(i / 25), "pose": True} for i in range(50)]  # 25 fps、约 2 秒，人脸姿态全检出
    (w,) = aggregate(frames, window=5.0)
    assert w["frames"] == 50 and w["face_ratio"] == 1.0 and w["pose_ratio"] == 1.0
    assert w["face_status"] == "unknown" and w["body_status"] == "unknown"
    assert not any(k in w for k in ("head", "gaze", "blink", "au_proxy", "body"))
    (w,) = aggregate(frames, window=2.0)  # 窗长配合片段长度就能给数
    assert w["face_status"] == "ok" and w["body_status"] == "ok"


def test_window_with_too_few_detected_frames_is_unknown_even_at_full_ratio():
    # 1 帧/秒：每个 5 秒窗只有 5–6 帧，检出率 1.0 也不给数
    frames = [_face(float(i)) for i in range(11)]
    wins = aggregate(frames, window=5.0)
    assert [w["frames"] for w in wins] == [5, 6]
    assert [w["face_ratio"] for w in wins] == [1.0, 1.0]
    assert [w["face_status"] for w in wins] == ["unknown", "unknown"]
    assert aggregate(frames, window=5.0, min_frames=5)[0]["face_status"] == "ok"


def test_blink_spanning_a_window_boundary_counts_once():
    # 4.8–5.2 秒一直闭眼：只算在开始闭眼的第一个窗，第二个窗不再从「闭着」重新计一次
    frames = [_face(i / 10, blink=0.9 if 48 <= i <= 52 else 0.0) for i in range(100)]
    wins = aggregate(frames, window=5.0)
    assert [w["blink"]["count"] for w in wins] == [1, 0]
