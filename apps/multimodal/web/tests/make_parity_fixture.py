# -*- coding: utf-8 -*-
"""生成 camera-metrics.js 与阶段三 face_body/live.py 的一致性测试数据（合成帧，固定公式、没有随机数）。

    python apps/multimodal/web/tests/make_parity_fixture.py   # 改了 live.py / windows.py 的口径后重跑并提交

输出 fixtures/camera-parity.json：上传格式的逐帧数值 + Python 算出的逐帧记录、本人基线和各段结果；
camera-metrics.test.js 用同一批帧在 node 里算一遍，逐项核对。
"""
import json
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from apps.emotion.face_body import live  # noqa: E402
from apps.emotion.face_body.windows import individual_baseline  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "fixtures" / "camera-parity.json"
T0 = 1_790_000_000.0


def _rot(yaw, pitch, roll):
    y, p, r = (math.radians(v) for v in (yaw, pitch, roll))
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = rz @ ry @ rx
    m[:3, 3] = [1.5, -2.0, -45.0]
    return [round(float(v), 6) for v in m.T.reshape(-1)]  # 浏览器的排法：列主序


def _frame(i):
    t = i / 5
    face = i % 17 != 0
    pose = i % 13 != 0
    f = None
    if face:
        look = 0.1 + (0.35 if 80 <= i < 120 else 0.0) + 0.05 * math.sin(i / 3)
        blink = 0.9 if i in (20, 21, 55, 56, 57, 140, 141) else (0.45 if i in (58, 59) else 0.05)
        bs = {k: round(0.1 * abs(math.sin(i / 7 + n)), 4) for n, k in enumerate(live.CAM_BLENDSHAPES)}
        bs.update(eyeLookOutLeft=round(look, 4), eyeLookInRight=round(look, 4), eyeLookInLeft=0.05,
                  eyeLookOutRight=0.05, eyeBlinkLeft=blink, eyeBlinkRight=blink)
        f = {"bs": bs, "m": _rot(15 * math.sin(i / 15), 8 * math.sin(i / 23), 3 * math.sin(i / 31))}
    p = None
    if pose:
        dx = 0.002 * math.sin(i / 5)
        p = [[0.5, 0.5, 0.0] for _ in range(25)]
        for j, (x, y) in {0: (0.50, 0.30), 11: (0.62, 0.55), 12: (0.38, 0.55), 13: (0.66, 0.72), 14: (0.34, 0.72),
                          15: (0.70, 0.90), 16: (0.30, 0.90), 23: (0.58, 0.95), 24: (0.42, 0.95)}.items():
            p[j] = [round(x + dx, 5), y, 0.98]
        if 150 <= i < 170:
            p[15] = [round(0.53 + dx, 5), 0.33, 0.97]   # 手触脸
        if i % 29 == 0:
            p[12][2] = 0.2                                # 右肩不可见：这帧不算身体检出
    return {"t": T0 + t, "f": f, "p": p}


def main():
    frames = [_frame(i) for i in range(200)]
    recs = [live.to_frame_record(fr, T0) for fr in frames]
    base = individual_baseline(recs, live.BASELINE_S)
    spans = [(0.0, 39.8), (8.0, 20.0), (16.0, 24.0), (30.0, 39.8), (22.0, 23.0), (35.0, 60.0), (5.0, 5.1)]
    segments = [{"a": a, "b": b, "expect": live.summarize_segment(recs, a, b, base)} for a, b in spans]
    keep = ("t", "face", "pose", "yaw", "pitch", "roll", "gaze_h", "gaze_v", "blink", "hand_face")
    data = {
        "note": "由 make_parity_fixture.py 生成，勿手改",
        "cam_blendshapes": list(live.CAM_BLENDSHAPES),
        "t0": T0,
        "frames": frames,
        "records": [{k: r[k] for k in keep if k in r} for r in recs],
        "baseline": {k: base[k] for k in ("gaze_h", "gaze_v", "yaw", "pitch")},
        "segments": segments,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    ok = sum(1 for s in segments if s["expect"]["face_status"] == "ok")
    print(f"写出 {OUT.name}：{len(frames)} 帧，{len(segments)} 段（其中人脸 ok {ok} 段）")


if __name__ == "__main__":
    main()
