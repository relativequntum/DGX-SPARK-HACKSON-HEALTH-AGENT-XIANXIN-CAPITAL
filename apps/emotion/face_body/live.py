# -*- coding: utf-8 -*-
"""实时通道（浏览器打点）：患者页上传的逐帧关键点数值 → 按患者每次回答切段的同期观察。

输入：
- `<OBS_DIR>/<会话>.frames.jsonl`：doctor_service 追加写，每行
  `{"t": 服务器秒, "f": {"bs": {26 个 blendshape}, "m": [16 个数]} | null, "p": [[x, y, visibility] × 25] | null}`；
- `<CONSULT_DIR>/<会话>.jsonl`：数字人的问诊记录，事件 `{"t", "kind": "user"|"assistant"|"summary", "text"}`。
输出：`<JUDGE_OUT>/<会话>.observe.json`（`schema_version: face_body-live-0.1`），医生工作台读它。

口径与离线视频相同：逐帧换算用 features.py，本人基线、平滑、眨眼滞回、unknown 判定用 windows.py；
每段检出帧 < 6 或检出率 < 0.5 记 unknown、不给数。不做人脸识别，不做表情或情绪分类。纯 numpy。

    python -m apps.emotion.face_body.live --consult <会话>.jsonl --frames <会话>.frames.jsonl --out-dir <目录>
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

import numpy as np

from .features import au_proxy, blink_score, euler_from_matrix, gaze_from_blendshapes, pose_features
from .windows import NOTICE, aggregate, individual_baseline

SCHEMA_VERSION = "face_body-live-0.1"
# 浏览器上传的 blendshape 白名单：features.py 用到的 26 个（目光 8、眨眼 2、AU 近似 16）。
# 与 apps/multimodal/web/camera-metrics.js、apps/multimodal/deploy/livetalking/doctor_service.py 三处一致，有测试核对。
CAM_BLENDSHAPES = (
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookUpLeft", "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
    "cheekSquintLeft", "cheekSquintRight", "eyeSquintLeft", "eyeSquintRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthPressLeft", "mouthPressRight", "jawOpen",
)
# MediaPipe 网页版 Matrix.data 的行列序：它把 MatrixData 的 packed_data 原样给出，默认列主序
# （核实记录：docs/notes/mediapipe-js-matrix.md）。
# matrix_from_flat 先按平移所在位置自动判断，只有判断不了（平移为 0 的合成矩阵）时才用它。
MATRIX_LAYOUT = "col"
BASELINE_S = 5.0        # 本人基线：开启摄像头后前 5 秒
MAX_SEGMENT_S = 60.0    # 一段最长截取 60 秒
MIN_FRAMES = 6          # 约 5 fps，一段至少 6 帧检出才给数
MIN_RATIO = 0.5
SEGMENT_KEYS = ("gaze_away_ratio", "blink_per_min", "head_motion_deg_per_frame",
                "hand_face_ratio", "body_motion_x1000")


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def matrix_from_flat(values, layout: str = MATRIX_LAYOUT) -> np.ndarray:
    """浏览器发来的 16 个数 → 4x4 矩阵，与 Python mediapipe 的 facial_transformation_matrixes[0] 同向。

    真矩阵最后一行是 [0, 0, 0, 1]，平移在最后一列（人脸离镜头几十厘米，平移不会是 0）：
    按行排开后平移落在最后一行，说明发来的是列主序，转置回来；两处都为 0 时按 layout。"""
    m = np.asarray(values, dtype=float).reshape(4, 4)
    bottom, right = float(np.abs(m[3, :3]).sum()), float(np.abs(m[:3, 3]).sum())
    if bottom > right:
        return m.T
    if right > bottom:
        return m
    return m.T if layout == "col" else m


def to_frame_record(frame: dict, t0: float) -> dict:
    """frames.jsonl 的一行 → 与 analyze.frame_record 同形的帧记录；t 为相对 t0（第一帧）的秒数。"""
    rec = {"t": float(frame["t"]) - t0, "face": False, "pose": False}
    f = frame.get("f")
    if isinstance(f, dict):
        bs = {k: float(f["bs"][k]) for k in CAM_BLENDSHAPES}
        yaw, pitch, roll = euler_from_matrix(matrix_from_flat(f["m"]))
        gaze_h, gaze_v = gaze_from_blendshapes(bs)
        rec.update(face=True, yaw=yaw, pitch=pitch, roll=roll, gaze_h=gaze_h, gaze_v=gaze_v,
                   blink=blink_score(bs), au=au_proxy(bs))
    p = frame.get("p")
    if isinstance(p, list) and len(p) >= 25:
        feats = pose_features([SimpleNamespace(x=float(q[0]), y=float(q[1]), visibility=float(q[2]))
                               for q in p[:25]])
        if feats.pop("shoulders"):
            rec.update(pose=True, **feats)
    return rec


def load_frames(path) -> list:
    """读 frames.jsonl，按服务器时间 t 排序；坏行（写了一半、不是对象、t 不是有限数）跳过。"""
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and _finite(row.get("t")):
            out.append(row)
    out.sort(key=lambda r: r["t"])
    return out


def load_events(path) -> list:
    """问诊记录 → [{"t", "kind"}]：只要 t 是有限数的 user（有文字）与 assistant 事件，按 t 排序。"""
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or not _finite(ev.get("t")):
            continue
        kind = ev.get("kind")
        if kind == "assistant" or (kind == "user" and str(ev.get("text") or "").strip()):
            out.append({"t": ev["t"], "kind": kind})
    out.sort(key=lambda e: e["t"])
    return out


def answer_intervals(events) -> list:
    """[(起点, t_u), ...]：每条患者回答一段。起点取「此前最近一条助手回复」与「上一条患者回答」中较晚的
    （患者连说两句时两段不重叠）；都没有（第一句之前只有开场白，开场白不进记录）或早于 t_u - 60 秒时取 t_u - 60 秒。"""
    out, last = [], None
    for ev in events:
        if ev["kind"] == "user":
            t_u = ev["t"]
            start = t_u - MAX_SEGMENT_S
            if last is not None and last > start:
                start = last
            out.append((start, t_u))
        last = ev["t"]
    return out


def summarize_segment(recs, a: float, b: float, baseline) -> dict:
    """相对时间 [a, b] 内的帧 → 一段的检出状态与指标。时间改为相对段内第一帧，窗长 = b - a，
    所以 windows.aggregate 只会给一个窗：摄像头只开了不到半段时记 unknown，眨眼率按实际覆盖的时长算。"""
    seg = [r for r in recs if a <= r["t"] <= b]
    out = {"frames": len(seg), "face_status": "unknown", "body_status": "unknown", "blink_count": None}
    out.update({k: None for k in SEGMENT_KEYS})
    if not seg or b - a <= 0:
        return out
    first = seg[0]["t"]
    wins = aggregate([dict(r, t=r["t"] - first) for r in seg], window=b - a, min_ratio=MIN_RATIO,
                     baseline=baseline, min_frames=MIN_FRAMES)
    if len(wins) != 1:  # 只有一帧（时长为 0）时没有窗
        return out
    w = wins[0]
    out.update(face_status=w["face_status"], body_status=w["body_status"])
    if w["face_status"] == "ok":
        out.update(gaze_away_ratio=w["gaze"]["away_ratio"], blink_count=w["blink"]["count"],
                   blink_per_min=w["blink"]["per_min"], head_motion_deg_per_frame=w["head"]["motion_deg_per_frame"])
    if w["body_status"] == "ok":
        out.update(hand_face_ratio=w["body"]["hand_face_ratio"], body_motion_x1000=w["body"]["motion_x1000"])
    return out


def _median(values):
    xs = [v for v in values if v is not None]
    return round(float(np.median(xs)), 2) if xs else None


def build_observation(frames, events, session_id: str = "") -> dict:
    """逐帧数值 + 问诊事件 → observe.json 的内容。frames 为 load_frames 的结果（已按 t 排序）。"""
    t0 = frames[0]["t"] if frames else 0.0
    recs = []
    for fr in frames:
        try:
            recs.append(to_frame_record(fr, t0))
        except (KeyError, TypeError, ValueError, IndexError):
            continue  # 单帧数据不全就跳过，不影响其余帧
    baseline = individual_baseline(recs, BASELINE_S) if recs else None
    segments = []
    for start, t_u in answer_intervals(events):
        seg = {"t": t_u, "interval": [round(start, 3), round(t_u, 3)]}
        # 摄像头开启之前没有「漏看」：起点不早于第一帧，否则第一句回答（前面只有开场白）总是覆盖不足
        seg.update(summarize_segment(recs, max(start - t0, 0.0), t_u - t0, baseline))
        segments.append(seg)
    n = len(recs)
    return {
        "schema_version": SCHEMA_VERSION,
        "notice": NOTICE,
        "session_id": session_id,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "camera_frames": n,
        "face_detect_ratio": round(sum(r["face"] for r in recs) / n, 2) if n else 0.0,
        "pose_detect_ratio": round(sum(r["pose"] for r in recs) / n, 2) if n else 0.0,
        "min_frames": MIN_FRAMES,
        "min_ratio": MIN_RATIO,
        "max_segment_s": MAX_SEGMENT_S,
        "baseline": ({k: (round(v, 3) if isinstance(v, float) else v) for k, v in baseline.items()}
                     if baseline else None),
        "medians": {k: _median(s[k] for s in segments) for k in SEGMENT_KEYS},
        "segments": segments,
    }


def write_observation(obs: dict, out_dir) -> pathlib.Path:
    """写 <out_dir>/<会话>.observe.json：先写同目录临时文件再改名，医生端不会读到写了一半的文件。"""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{obs['session_id']}.observe.json"
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", suffix=".tmp", dir=str(out_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obs, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return dest


def observe_session(consult_path, frames_path, out_dir) -> pathlib.Path:
    """一次问诊：读 frames 与问诊记录 → 写 observe.json，返回路径。会话编号取问诊记录的文件名。"""
    consult_path = pathlib.Path(consult_path)
    obs = build_observation(load_frames(frames_path), load_events(consult_path), session_id=consult_path.stem)
    return write_observation(obs, out_dir)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m apps.emotion.face_body.live",
                                description="浏览器打点的逐帧数值 + 问诊记录 → 每条患者回答的同期观察（observe.json）")
    p.add_argument("--consult", required=True, help="问诊记录 <会话>.jsonl")
    p.add_argument("--frames", required=True, help="<会话>.frames.jsonl")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    path = observe_session(args.consult, args.frames, args.out_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = sum(1 for s in data["segments"] if s["face_status"] == "ok" or s["body_status"] == "ok")
    print(f"{path.name}：{data['camera_frames']} 帧，{len(data['segments'])} 段回答，其中 {ok} 段有数")
    return 0


if __name__ == "__main__":
    sys.exit(main())
