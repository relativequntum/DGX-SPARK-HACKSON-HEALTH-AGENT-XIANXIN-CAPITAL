# -*- coding: utf-8 -*-
"""逐帧记录 → 按时间窗聚合的观察量（纯 numpy）。

帧记录（analyze.py 产出）：{"t": 秒, "face": bool, "pose": bool, ...}
  face=True 时带 yaw / pitch / roll / gaze_h / gaze_v / blink / au；
  pose=True（检出姿态且双肩可见）时带 shoulder_tilt / shoulder_w / torso_lean / hand_face / kp。
口径（沿用 2026-09-22 本机 spike 实测过的做法）：
- 目光偏离看「相对本人基线」：基线 = 前 5 秒有人脸帧的中位数（决策记录第 22 条：只与本人比，不与数据集比）；
  逐帧先做 9 帧滑动中位数（eyeLook* 逐帧噪声大）；目光偏移 > 0.25 或 yaw 偏 > 20° 或 pitch 偏 > 15° 记一帧偏离；
- 眨眼带滞回：> 0.5 判闭、< 0.3 判开，阈值附近抖动不重复计数；在整段人脸帧上判，记在闭眼开始的那个窗，跨窗不重复计；
- 末窗不足半个窗长时并入前一窗（该窗最长 1.5 个窗长）；整段不足半个窗长时只有一窗，记 unknown；
- 一个窗里某通道检出率 < min_ratio（默认 0.5）或检出帧 < min_frames（默认 10）就记 unknown、不给数
  （安全文档：输出必须有 unknown 状态）。
"""
from __future__ import annotations

import math

import numpy as np

SCHEMA_VERSION = "face_body-0.1"
NOTICE = ("只记录可观察量：头姿、目光偏离、眨眼、面部动作单元的 blendshape 近似、坐姿与小动作。"
          "不做人脸识别（身份）、不做表情或情绪分类；数值只与本人基线比较，待医务人员结合问诊判断。")
GAZE_AWAY, YAW_AWAY, PITCH_AWAY = 0.25, 20.0, 15.0
BLINK_CLOSE, BLINK_OPEN = 0.5, 0.3
SMOOTH_K = 9
BASELINE_S = 5.0
# 一个窗里某通道至少要有这么多检出帧才给数。25–30 fps 的 5 秒窗有 125–150 帧，--stride 3 也有 40 帧以上；
# 不到 10 帧（帧率太低、或整段极短）时均值、眨眼率都不可靠
MIN_FRAMES = 10
_BASE_KEYS = ("gaze_h", "gaze_v", "yaw", "pitch")


def stat(values) -> dict:
    xs = np.asarray([v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))],
                    dtype=float)
    if xs.size == 0:
        return {"mean": None, "std": None, "n": 0}
    return {"mean": round(float(xs.mean()), 2), "std": round(float(xs.std()), 2), "n": int(xs.size)}


def rolling_median(values, k: int = SMOOTH_K) -> list:
    xs = np.asarray(values, dtype=float)
    half = k // 2
    return [float(np.median(xs[max(0, i - half): i + half + 1])) for i in range(len(xs))]


def blink_onsets(values, close: float = BLINK_CLOSE, reopen: float = BLINK_OPEN) -> list:
    """逐帧是否「这一帧开始闭眼」（带滞回）。在整段上判，窗只数落在自己里的开始帧，跨窗的一次眨眼只计一次。"""
    out, closed = [], False
    for v in values:
        onset = not closed and v > close
        if onset:
            closed = True
        elif closed and v < reopen:
            closed = False
        out.append(onset)
    return out


def count_blinks(values, close: float = BLINK_CLOSE, reopen: float = BLINK_OPEN) -> int:
    return sum(blink_onsets(values, close, reopen))


def individual_baseline(frames, seconds: float = BASELINE_S):
    """本人基线：前 seconds 秒有人脸帧的中位数；前段没有人脸就用全部人脸帧；一帧人脸都没有返回 None。"""
    faces = [f for f in frames if f.get("face")]
    if not faces:
        return None
    early = [f for f in faces if f["t"] < seconds]
    use, source = (early, f"first_{seconds:g}s") if early else (faces, "all_frames")
    base = {k: float(np.median([f[k] for f in use])) for k in _BASE_KEYS}
    base.update(source=source, frames=len(use))
    return base


def window_edges(dur: float, window: float) -> list:
    """[(t0, t1), ...]：按 window 切到 dur 为止（dur 恰好是窗长整数倍时不多出空窗）。
    末窗不足半个窗长就并入前一窗，免得几帧的尾巴单独成窗、给出离谱的数（例如 2 帧闭眼算出每分钟 1500 次眨眼）；
    只有一窗时没有可并的，留给 aggregate 记 unknown。"""
    n = math.ceil(dur / window) if dur > 0 else 0
    edges = [(k * window, min((k + 1) * window, dur)) for k in range(n)]
    if len(edges) >= 2 and edges[-1][1] - edges[-1][0] < window / 2:
        edges[-2:] = [(edges[-2][0], dur)]
    return edges


def aggregate(frames, window: float = 5.0, min_ratio: float = 0.5, baseline=None,
              min_frames: int = MIN_FRAMES) -> list:
    if not frames:
        return []
    baseline = baseline if baseline is not None else individual_baseline(frames)
    rows = [dict(f) for f in frames]
    faces = [r for r in rows if r.get("face")]
    for key in _BASE_KEYS:
        for r, v in zip(faces, rolling_median([r[key] for r in faces])):
            r[key + "_s"] = v
    for r, onset in zip(faces, blink_onsets([r["blink"] for r in faces])):
        r["blink_onset"] = onset

    dur = rows[-1]["t"]
    edges = window_edges(dur, window)
    min_frames = max(1, int(min_frames))

    def status(detected: list, total: int, span: float) -> str:
        # 检出帧够数（min_frames ≥ 1，所以 total 不会是 0）、检出率够、窗不短于半个窗长（只可能是整段太短的唯一一窗）
        enough = len(detected) >= min_frames and len(detected) / total >= min_ratio
        return "ok" if enough and span >= window / 2 else "unknown"

    out = []
    for k, (w0, w1) in enumerate(edges):
        last = k == len(edges) - 1
        fs = [r for r in rows if w0 <= r["t"] and (last or r["t"] < w1)]
        ff = [r for r in fs if r.get("face")]
        pf = [r for r in fs if r.get("pose")]
        face_ratio = len(ff) / len(fs) if fs else 0.0
        pose_ratio = len(pf) / len(fs) if fs else 0.0
        win = {"t0": round(w0, 1), "t1": round(w1, 1), "frames": len(fs),
               "face_ratio": round(face_ratio, 2), "pose_ratio": round(pose_ratio, 2),
               "face_status": status(ff, len(fs), w1 - w0),
               "body_status": status(pf, len(fs), w1 - w0)}
        if win["face_status"] == "ok":
            win.update(_face_metrics(ff, baseline, w1 - w0))
        if win["body_status"] == "ok":
            win["body"] = _body_metrics(pf)
        out.append(win)
    return out


def _face_metrics(ff: list, baseline, span: float) -> dict:
    dang = [abs(ff[j]["yaw"] - ff[j - 1]["yaw"]) + abs(ff[j]["pitch"] - ff[j - 1]["pitch"]) for j in range(1, len(ff))]
    head = {"yaw": stat([r["yaw"] for r in ff]), "pitch": stat([r["pitch"] for r in ff]),
            "roll": stat([r["roll"] for r in ff]),
            "motion_deg_per_frame": round(float(np.mean(dang)), 2) if dang else None}
    gaze = {"h": stat([r["gaze_h"] for r in ff]), "v": stat([r["gaze_v"] for r in ff]), "away_ratio": None}
    if baseline:
        away = [abs(r["gaze_h_s"] - baseline["gaze_h"]) > GAZE_AWAY or abs(r["gaze_v_s"] - baseline["gaze_v"]) > GAZE_AWAY
                or abs(r["yaw_s"] - baseline["yaw"]) > YAW_AWAY or abs(r["pitch_s"] - baseline["pitch"]) > PITCH_AWAY
                for r in ff]
        gaze["away_ratio"] = round(float(np.mean(away)), 2)
        gaze["baseline"] = {"h": round(baseline["gaze_h"], 3), "v": round(baseline["gaze_v"], 3),
                            "yaw": round(baseline["yaw"], 1), "pitch": round(baseline["pitch"], 1)}
    blinks = sum(bool(r.get("blink_onset")) for r in ff)
    names = list(dict.fromkeys(name for r in ff for name in r.get("au", {})))
    return {
        "head": head,
        "gaze": gaze,
        "blink": {"count": blinks, "per_min": round(blinks * 60 / span, 1) if span > 0 else None},
        "au_proxy": {n: round(float(np.mean([r["au"][n] for r in ff if n in r.get("au", {})])), 3) for n in names},
    }


def _body_metrics(pf: list) -> dict:
    moves = []
    for a, b in zip(pf, pf[1:]):
        common = set(a.get("kp") or {}) & set(b.get("kp") or {})
        if common:
            moves.append(np.mean([math.hypot(a["kp"][i][0] - b["kp"][i][0], a["kp"][i][1] - b["kp"][i][1])
                                  for i in common]) * 1000)
    return {
        "shoulder_tilt": stat([r["shoulder_tilt"] for r in pf]),
        "shoulder_w": stat([r["shoulder_w"] for r in pf]),
        "torso_lean": stat([r.get("torso_lean") for r in pf]),
        "hand_face_ratio": round(float(np.mean([bool(r["hand_face"]) for r in pf])), 2),
        "motion_x1000": round(float(np.mean(moves)), 2) if moves else None,
    }


def build_report(frames, window: float = 5.0, min_ratio: float = 0.5, meta=None,
                 min_frames: int = MIN_FRAMES) -> dict:
    n = len(frames)
    baseline = individual_baseline(frames)
    report = {
        "schema_version": SCHEMA_VERSION,
        "notice": NOTICE,
        "window_s": window,
        "min_ratio": min_ratio,
        "min_frames": min_frames,
        "frames_total": n,
        "duration_s": round(frames[-1]["t"], 1) if frames else 0.0,
        "face_detect_ratio": round(sum(bool(f.get("face")) for f in frames) / n, 2) if n else 0.0,
        "pose_detect_ratio": round(sum(bool(f.get("pose")) for f in frames) / n, 2) if n else 0.0,
        "baseline": ({k: (round(v, 3) if isinstance(v, float) else v) for k, v in baseline.items()}
                     if baseline else None),
        "windows": aggregate(frames, window, min_ratio, baseline, min_frames=min_frames),
    }
    report.update(meta or {})
    return report
