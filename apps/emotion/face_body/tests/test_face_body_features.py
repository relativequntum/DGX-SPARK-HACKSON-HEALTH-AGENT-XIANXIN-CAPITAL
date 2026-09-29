# -*- coding: utf-8 -*-
import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from apps.emotion.face_body.analyze import frame_record
from apps.emotion.face_body.features import (AU_MAP, au_proxy, blink_score, euler_from_matrix,
                                             gaze_from_blendshapes, pose_features)
from apps.emotion.face_body.windows import aggregate


def _rot(axis, deg):
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    m = np.eye(4)
    m[:3, :3] = {"x": [[1, 0, 0], [0, c, -s], [0, s, c]],
                 "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
                 "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis]
    return m


def _bs(**kw):
    names = ["eyeLookOutLeft", "eyeLookInRight", "eyeLookInLeft", "eyeLookOutRight", "eyeLookUpLeft",
             "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight", "eyeBlinkLeft", "eyeBlinkRight"]
    names += [n for _, group in AU_MAP for n in group]
    d = {n: 0.0 for n in names}
    d.update(kw)
    return d


def _pose(over=None):
    lm = [NS(x=0.5, y=0.5, visibility=0.0) for _ in range(33)]
    base = {0: (0.50, 0.30, 1.0), 11: (0.62, 0.55, 1.0), 12: (0.38, 0.55, 1.0), 15: (0.70, 0.90, 1.0),
            16: (0.30, 0.90, 1.0), 23: (0.58, 0.95, 1.0), 24: (0.42, 0.95, 1.0)}
    base.update(over or {})
    for i, (x, y, v) in base.items():
        lm[i] = NS(x=x, y=y, visibility=v)
    return lm


def test_identity_matrix_is_zero_pose():
    assert euler_from_matrix(np.eye(4)) == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


@pytest.mark.parametrize("axis,index", [("y", 0), ("x", 1), ("z", 2)])
def test_single_axis_rotation_maps_to_yaw_pitch_roll(axis, index):
    got = euler_from_matrix(_rot(axis, 25))
    assert got[index] == pytest.approx(25, abs=1e-6)
    assert all(abs(v) < 1e-6 for i, v in enumerate(got) if i != index)


def test_gimbal_lock_still_reports_yaw():
    assert euler_from_matrix(_rot("y", 90))[0] == pytest.approx(90, abs=1e-6)


def test_gaze_horizontal_and_vertical_from_eye_look_blendshapes():
    assert gaze_from_blendshapes(_bs(eyeLookOutLeft=0.8, eyeLookInRight=0.6)) == pytest.approx((0.7, 0.0))
    assert gaze_from_blendshapes(_bs(eyeLookDownLeft=0.4, eyeLookDownRight=0.6)) == pytest.approx((0.0, -0.5))


def test_blink_is_mean_of_both_eyes():
    assert blink_score(_bs(eyeBlinkLeft=0.9, eyeBlinkRight=0.5)) == pytest.approx(0.7)


def test_au_proxy_averages_mapped_blendshapes_in_fixed_order():
    au = au_proxy(_bs(mouthSmileLeft=0.4, mouthSmileRight=0.2, browInnerUp=0.5))
    assert au["AU12 嘴角上扬"] == pytest.approx(0.3)
    assert au["AU1 内眉上提"] == pytest.approx(0.5)
    assert list(au) == [name for name, _ in AU_MAP]


def test_level_shoulders_facing_camera():
    f = pose_features(_pose())
    assert f["shoulder_tilt"] == pytest.approx(0.0, abs=1e-9)
    assert f["shoulder_w"] == pytest.approx(0.24)
    assert f["torso_lean"] == pytest.approx(0.0, abs=1e-9)
    assert f["hand_face"] is False
    assert sorted(f["kp"]) == [0, 11, 12, 15, 16, 23, 24]  # 前 25 个关键点里可见的那几个，按下标存


def test_lower_right_shoulder_gives_negative_tilt():
    f = pose_features(_pose({12: (0.38, 0.57, 1.0)}))
    assert f["shoulder_tilt"] == pytest.approx(-math.degrees(math.atan2(0.02, 0.24)))


def test_wrist_near_nose_counts_as_hand_to_face():
    assert pose_features(_pose({15: (0.52, 0.32, 1.0)}))["hand_face"] is True


def test_torso_lean_is_none_when_hips_not_visible():
    assert pose_features(_pose({23: (0.58, 0.95, 0.1), 24: (0.42, 0.95, 0.1)}))["torso_lean"] is None


SHOULDER_KEYS = ("shoulder_tilt", "shoulder_w", "shoulder_cx", "shoulder_cy", "torso_lean")


@pytest.mark.parametrize("joint", [11, 12])
def test_shoulder_features_are_none_when_either_shoulder_not_visible(joint):
    x = 0.62 if joint == 11 else 0.38
    f = pose_features(_pose({joint: (x, 0.55, 0.5)}))  # visibility 正好 0.5 也算不可见（与髋、手腕同口径）
    assert f["shoulders"] is False
    assert all(f[k] is None for k in SHOULDER_KEYS)
    assert joint not in f["kp"] and 0 in f["kp"]  # 其余可见关节照常记


def test_hand_to_face_does_not_depend_on_shoulders():
    f = pose_features(_pose({11: (0.62, 0.55, 0.1), 15: (0.52, 0.32, 1.0)}))
    assert f["shoulders"] is False and f["hand_face"] is True


def _no_face():
    return NS(face_landmarks=[])


def test_frame_without_both_shoulders_is_not_a_pose_detection():
    ok = frame_record(0.0, _no_face(), NS(pose_landmarks=[_pose()]))
    assert ok["pose"] is True and ok["shoulder_w"] == pytest.approx(0.24) and "shoulders" not in ok
    cut = frame_record(0.0, _no_face(), NS(pose_landmarks=[_pose({12: (0.38, 0.55, 0.3)})]))
    assert cut == {"t": 0.0, "face": False, "pose": False}


def test_window_with_a_shoulder_out_of_view_is_body_unknown():
    # 姿态模型每帧都有结果，但左肩出画（visibility 0.2）：旧逻辑照样算肩倾肩宽、标 ok
    lm = _pose({11: (0.62, 0.55, 0.2)})
    frames = [frame_record(i / 10, _no_face(), NS(pose_landmarks=[lm])) for i in range(51)]
    (w,) = aggregate(frames, window=5.0)
    assert w["pose_ratio"] == 0.0 and w["body_status"] == "unknown" and "body" not in w
    frames = [frame_record(i / 10, _no_face(), NS(pose_landmarks=[_pose()])) for i in range(51)]
    (w,) = aggregate(frames, window=5.0)
    assert w["body_status"] == "ok" and w["body"]["shoulder_w"]["mean"] == pytest.approx(0.24)
