# -*- coding: utf-8 -*-
"""逐帧特征：MediaPipe 的面部变换矩阵 / 52 个 blendshape / 33 个姿态关键点 → 可观察量。

只算「观察到什么」：头姿角度、目光偏移、眨眼程度、面部动作单元（AU）的 blendshape 近似、坐姿与小动作。
不做人脸识别、不做表情或情绪分类。纯 numpy，不依赖 mediapipe，便于测试。
"""
from __future__ import annotations

import math

import numpy as np

# blendshape → 近似 AU（FACS）。只取与 MSE「情感 / 外观」条目相关的几个；是近似，不是 FACS 编码。
AU_MAP = (
    ("AU1 内眉上提", ("browInnerUp",)),
    ("AU2 外眉上提", ("browOuterUpLeft", "browOuterUpRight")),
    ("AU4 皱眉", ("browDownLeft", "browDownRight")),
    ("AU6 眼轮匝肌", ("cheekSquintLeft", "cheekSquintRight")),
    ("AU7 眼睑紧缩", ("eyeSquintLeft", "eyeSquintRight")),
    ("AU12 嘴角上扬", ("mouthSmileLeft", "mouthSmileRight")),
    ("AU15 嘴角下压", ("mouthFrownLeft", "mouthFrownRight")),
    ("AU24 抿嘴", ("mouthPressLeft", "mouthPressRight")),
    ("AU26 张口", ("jawOpen",)),
)

VISIBLE = 0.5          # 姿态关键点 visibility 高于它才用
HAND_FACE_DIST = 0.18  # 手腕到鼻尖的归一化距离小于它，记一帧「手触脸」
# MediaPipe Pose 关键点下标
NOSE, L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_HIP, R_HIP = 0, 11, 12, 15, 16, 23, 24


def euler_from_matrix(m) -> tuple:
    """4x4 面部变换矩阵（相机坐标系下的人脸姿态）→ (yaw, pitch, roll)，单位度。"""
    r = np.asarray(m, dtype=float)[:3, :3]
    sy = math.hypot(r[0, 0], r[1, 0])
    if sy > 1e-6:
        pitch = math.atan2(r[2, 1], r[2, 2])
        roll = math.atan2(r[1, 0], r[0, 0])
    else:  # 万向锁：yaw ≈ ±90°，roll 无法与 pitch 区分，记 0
        pitch = math.atan2(-r[1, 2], r[1, 1])
        roll = 0.0
    yaw = math.atan2(-r[2, 0], sy)
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


def gaze_from_blendshapes(bs: dict) -> tuple:
    """目光偏移近似，约 [-1, 1]：水平 = 两眼 eyeLook 左右差，垂直正值 = 向上。逐帧噪声大，聚合前要平滑。"""
    h = ((bs["eyeLookOutLeft"] + bs["eyeLookInRight"]) - (bs["eyeLookInLeft"] + bs["eyeLookOutRight"])) / 2
    v = ((bs["eyeLookUpLeft"] + bs["eyeLookUpRight"]) - (bs["eyeLookDownLeft"] + bs["eyeLookDownRight"])) / 2
    return float(h), float(v)


def blink_score(bs: dict) -> float:
    """0 = 睁眼，1 = 闭眼；两眼平均。"""
    return float((bs["eyeBlinkLeft"] + bs["eyeBlinkRight"]) / 2)


def au_proxy(bs: dict) -> dict:
    """AU 名 → 对应 blendshape 的平均值（0~1），顺序固定为 AU_MAP 的顺序。"""
    return {name: float(np.mean([bs[n] for n in names])) for name, names in AU_MAP}


def shoulders_visible(landmarks) -> bool:
    """双肩 visibility 都高于 VISIBLE。肩是身体通道的基准：肩倾、肩宽、躯干前倾都由双肩算。"""
    return landmarks[L_SHOULDER].visibility > VISIBLE and landmarks[R_SHOULDER].visibility > VISIBLE


def pose_features(landmarks) -> dict:
    """33 个姿态关键点（带 x / y / visibility，归一化坐标）→ 坐姿与小动作用的量。

    shoulders：双肩是否都可见。任一肩不可见时肩坐标是模型推测的，由它算的
      shoulder_tilt / shoulder_cx / shoulder_cy / shoulder_w / torso_lean 都记 None；
      analyze.frame_record 把这样的帧记为没有检出姿态（身体通道不用它）。
    shoulder_tilt：双肩连线倾角，归一到 (-90, 90]，0 = 水平；正对镜头时右肩在画面左侧。
    torso_lean：肩中点相对髋中点的前后倾角；肩或髋不可见时为 None。
    kp：前 25 个关键点里可见的，{下标: (x, y)}，小动作量按同一关节前后帧位移算。
    """
    p = landmarks
    ls, rs, nose = p[L_SHOULDER], p[R_SHOULDER], p[NOSE]
    shoulders = shoulders_visible(p)
    tilt = cx = cy = width = lean = None
    if shoulders:
        tilt = math.degrees(math.atan2(rs.y - ls.y, rs.x - ls.x))
        tilt = tilt - 180 if tilt > 90 else (tilt + 180 if tilt < -90 else tilt)
        cx, cy = (ls.x + rs.x) / 2, (ls.y + rs.y) / 2
        width = abs(rs.x - ls.x)
        lh, rh = p[L_HIP], p[R_HIP]
        if lh.visibility > VISIBLE and rh.visibility > VISIBLE:
            hx, hy = (lh.x + rh.x) / 2, (lh.y + rh.y) / 2
            lean = math.degrees(math.atan2(cx - hx, hy - cy))
    # 手触脸只看手腕与鼻尖，不要求鼻尖可见：手挡住脸时鼻尖的 visibility 本来就会掉
    dists = [math.hypot(w.x - nose.x, w.y - nose.y) for w in (p[L_WRIST], p[R_WRIST]) if w.visibility > VISIBLE]
    return {
        "shoulders": shoulders,
        "shoulder_tilt": tilt,
        "shoulder_cx": cx,
        "shoulder_cy": cy,
        "shoulder_w": width,
        "torso_lean": lean,
        "hand_face": bool(dists) and min(dists) < HAND_FACE_DIST,
        "kp": {i: (q.x, q.y) for i, q in enumerate(p[:25]) if q.visibility > VISIBLE},
    }
