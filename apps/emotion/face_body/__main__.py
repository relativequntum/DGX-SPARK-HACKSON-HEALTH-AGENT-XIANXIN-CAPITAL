# -*- coding: utf-8 -*-
"""命令行入口（仓库根目录运行）。

    python -m apps.emotion.face_body fetch-models [--proxy http://<代理>]        # 下载并校验 MediaPipe 模型
    python -m apps.emotion.face_body analyze <视频> [--window 5] [--stride 1]      # → outputs/face_body/<名>.face_body.json
    python -m apps.emotion.face_body annotate <视频> [--frames 2,12,17]            # → 叠加打点的演示视频 + 关键帧（含人脸）
    python -m apps.emotion.face_body record --sec 40 --out <文件.mp4> | --check    # 开发机录像（Spark 没摄像头）

模型目录：--models > 环境变量 FACE_BODY_MODEL_DIR > 本包下的 models/。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .analyze import analyze_video
from .models import default_model_dir, fetch_models


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m apps.emotion.face_body",
                                description="阶段三面部 / 身体观察通道（不做人脸识别、不做表情分类）")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="视频 → 按时间窗的观察量 JSON（只有数值，不存图像）")
    a.add_argument("video", type=pathlib.Path)
    a.add_argument("--window", type=float, default=5.0, help="时间窗长度（秒）")
    a.add_argument("--stride", type=int, default=1, help="每 N 帧处理一帧")
    a.add_argument("--models", type=pathlib.Path, default=None)
    a.add_argument("--out-dir", default="outputs/face_body")

    n = sub.add_parser("annotate", help="视频 → 叠加面部打点 / 头姿轴 / 骨架 / 数值面板的演示视频 + 关键帧（含人脸，仅本机演示）")
    n.add_argument("video", type=pathlib.Path)
    n.add_argument("--frames", default="2,12,17,27,37", help="导出关键帧的秒数，逗号分隔")
    n.add_argument("--models", type=pathlib.Path, default=None)
    n.add_argument("--out-dir", default="outputs/face_body")

    f = sub.add_parser("fetch-models", help="下载 MediaPipe 模型并校验 sha256")
    f.add_argument("--models", type=pathlib.Path, default=None)
    f.add_argument("--proxy", default=None, help="HTTP 代理，例如 Spark 局域网代理")

    r = sub.add_parser("record", help="开发机摄像头录一段带逐帧时间戳的视频")
    r.add_argument("--sec", type=float, default=40.0)
    r.add_argument("--out", type=pathlib.Path, default=pathlib.Path("outputs/face_body/recordings/clip.mp4"))
    r.add_argument("--cam", type=int, default=0)
    r.add_argument("--check", action="store_true", help="只检查有哪些摄像头能打开")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "record":
        from .record import check_cameras, record

        if args.check:
            for cam in check_cameras():
                print(f"[face_body] 摄像头 {cam['index']}: opened={cam['opened']} frame={cam['frame']} "
                      f"shape={cam['shape']} fps={cam['fps']}")
            return 0
        info = record(args.out, seconds=args.sec, cam=args.cam)
        print(f"[face_body] 已录 {info['video']}：{info['frames']} 帧 {info['duration_s']}s {info['fps']} fps")
        return 0

    model_dir = args.models or default_model_dir()
    if args.command == "fetch-models":
        paths = fetch_models(model_dir, proxy=args.proxy)
        for key, path in paths.items():
            print(f"[face_body] {key}: {path}")
        return 0

    out_dir = pathlib.Path(args.out_dir)
    if args.command == "analyze":
        report = analyze_video(args.video, model_dir, window=args.window, stride=args.stride)
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{args.video.stem}.face_body.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print_summary(report)
        print(f"[face_body] 写出 {out}")
        return 0

    from .annotate import annotate_video

    keyframes = [float(x) for x in args.frames.split(",") if x.strip()]
    info = annotate_video(args.video, model_dir, out_dir, keyframes=keyframes)
    print(f"[face_body] 写出 {info['video']}（{info['codec']}），关键帧 {len(info['keyframes'])} 张，字体 {info['font']}")
    if info["codec"] != "h264":
        print("[face_body] 没找到 ffmpeg，视频是 mp4v 编码：浏览器可能播不了，装 imageio-ffmpeg 或 ffmpeg 后重跑")
    return 0


def print_summary(report: dict) -> None:
    print(f"[face_body] {report.get('video')}：{report.get('duration_s')}s，{report.get('frames_total')} 帧，"
          f"处理 {report.get('process_fps')} fps，人脸检出 {report.get('face_detect_ratio')}，"
          f"姿态检出 {report.get('pose_detect_ratio')}")
    head = f"{'窗(秒)':>11} {'面部':>7} {'yaw':>6} {'pitch':>6} {'目光偏离':>6} {'眨眼/分':>6} {'AU4皱眉':>6} {'AU12上扬':>7} {'身体':>7} {'手触脸':>5} {'小动作':>6}"
    print(head)
    for w in report.get("windows", []):
        h, g, b = w.get("head", {}), w.get("gaze", {}), w.get("blink", {})
        au, body = w.get("au_proxy", {}), w.get("body", {})

        def mean(d, k):
            v = (d.get(k) or {}).get("mean")
            return "-" if v is None else v

        print(f"{w['t0']:>5}-{w['t1']:<5} {w['face_status']:>7} {mean(h, 'yaw'):>6} {mean(h, 'pitch'):>6} "
              f"{g.get('away_ratio', '-') if g else '-':>6} {b.get('per_min', '-') if b else '-':>6} "
              f"{au.get('AU4 皱眉', '-'):>6} {au.get('AU12 嘴角上扬', '-'):>7} {w['body_status']:>7} "
              f"{body.get('hand_face_ratio', '-') if body else '-':>5} {body.get('motion_x1000', '-') if body else '-':>6}")


if __name__ == "__main__":
    sys.exit(main())
