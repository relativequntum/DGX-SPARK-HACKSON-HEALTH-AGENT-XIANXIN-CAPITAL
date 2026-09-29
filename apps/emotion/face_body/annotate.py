# -*- coding: utf-8 -*-
"""演示用可视化：把面部 478 点网格 / 轮廓 / 虹膜、头姿坐标轴、身体骨架和逐帧数值面板画到视频上，另存几张关键帧。

输出含人脸，只用于本机演示：不要入库、不要上传、不要拿真实患者的视频来画。
H.264：找得到 ffmpeg（PATH 里的，或 pip 装的 imageio-ffmpeg）就转码成浏览器能直接播的 mp4；
找不到就保留 OpenCV 的 mp4v 编码（VLC 能播，浏览器多半不能）。
"""
from __future__ import annotations

import math
import os
import pathlib
import shutil
import subprocess
from collections import deque

import numpy as np

from .analyze import iter_frames, open_landmarkers
from .features import AU_MAP, blink_score, euler_from_matrix, gaze_from_blendshapes, pose_features

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
)
PANEL_W = 420
DEFAULT_KEYFRAMES = (2, 12, 17, 27, 37)


def find_font(candidates=FONT_CANDIDATES):
    """面板中文字体：环境变量 FACE_BODY_FONT 优先，否则候选列表里第一个存在的；都没有返回 None。"""
    env = (os.environ.get("FACE_BODY_FONT") or "").strip()
    for path in ([env] if env else []) + list(candidates):
        if path and os.path.isfile(path):
            return path
    return None


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def annotate_video(video, model_dir, out_dir, keyframes=DEFAULT_KEYFRAMES) -> dict:
    import cv2
    from mediapipe.tasks.python import vision
    from PIL import ImageFont

    video, out_dir = pathlib.Path(video), pathlib.Path(out_dir)
    (out_dir / "frames").mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    font_path = find_font()

    def font(size):
        return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()

    fonts = (font(17), font(14), font(20))
    fc, pc = vision.FaceLandmarksConnections, vision.PoseLandmarksConnections
    mp, face, pose = open_landmarkers(model_dir)
    raw = out_dir / f"{video.stem}.annotated.raw.mp4"
    writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width + PANEL_W, height))
    gaze_hist = {"h": deque(maxlen=9), "v": deque(maxlen=9)}
    prev_kp, saved = None, []
    try:
        for ts, frame in iter_frames(video):
            t = ts / 1000.0
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            fr, pr = face.detect_for_video(img, ts), pose.detect_for_video(img, ts)
            canvas, panel = frame.copy(), {"t": t, "face": False, "pose": False}
            if pr.pose_landmarks:
                p = pr.pose_landmarks[0]
                for c in pc.POSE_LANDMARKS:
                    a, b = p[c.start], p[c.end]
                    if a.visibility > 0.5 and b.visibility > 0.5:
                        cv2.line(canvas, _px(a, width, height), _px(b, width, height), (80, 220, 120), 2, cv2.LINE_AA)
                for q in p[:25]:
                    if q.visibility > 0.5:
                        cv2.circle(canvas, _px(q, width, height), 4, (0, 160, 255), -1, cv2.LINE_AA)
                pf = pose_features(p)
                if pf["shoulders"]:  # 与 analyze 同口径：任一肩不可见不算身体检出，面板不给肩倾等数
                    common = set(prev_kp or {}) & set(pf["kp"])
                    motion = (float(np.mean([math.hypot(prev_kp[i][0] - pf["kp"][i][0], prev_kp[i][1] - pf["kp"][i][1])
                                             for i in common])) * 1000) if common else None
                    prev_kp = pf["kp"]
                    panel.update(pose=True, tilt=pf["shoulder_tilt"], hand_face=pf["hand_face"], motion=motion)
            if fr.face_landmarks:
                lm = fr.face_landmarks[0]
                _lines(cv2, canvas, lm, fc.FACE_LANDMARKS_TESSELATION, (120, 120, 90), 1, width, height)
                _lines(cv2, canvas, lm, fc.FACE_LANDMARKS_CONTOURS, (255, 200, 0), 1, width, height)
                for conns in (fc.FACE_LANDMARKS_LEFT_IRIS, fc.FACE_LANDMARKS_RIGHT_IRIS):
                    _lines(cv2, canvas, lm, conns, (0, 255, 255), 2, width, height)
                for q in lm:
                    cv2.circle(canvas, _px(q, width, height), 1, (255, 255, 255), -1)
                m = fr.facial_transformation_matrixes[0]
                yaw, pitch, roll = euler_from_matrix(m)
                r = np.asarray(m)[:3, :3]
                nx, ny = _px(lm[1], width, height)
                for color, axis in (((0, 0, 255), 0), ((0, 255, 0), 1), ((255, 80, 0), 2)):  # x 红 y 绿 z 蓝（BGR）
                    tip = (int(nx + r[0, axis] * 70), int(ny - r[1, axis] * 70))
                    cv2.arrowedLine(canvas, (nx, ny), tip, color, 2, cv2.LINE_AA, tipLength=0.2)
                bs = {c.category_name: c.score for c in fr.face_blendshapes[0]}
                gh, gv = gaze_from_blendshapes(bs)
                gaze_hist["h"].append(gh)
                gaze_hist["v"].append(gv)
                panel.update(face=True, yaw=yaw, pitch=pitch, roll=roll,
                             gaze_h=float(np.median(gaze_hist["h"])), gaze_v=float(np.median(gaze_hist["v"])),
                             blink=blink_score(bs),
                             au=[(name, float(np.mean([bs[n] for n in names]))) for name, names in AU_MAP],
                             top_bs=sorted(((k, s) for k, s in bs.items() if k != "_neutral"), key=lambda x: -x[1])[:5])
            composed = np.concatenate([canvas, _panel(cv2, panel, height, fonts)], axis=1)
            writer.write(composed)
            for s in keyframes:
                if s not in saved and t >= s:
                    cv2.imwrite(str(out_dir / "frames" / f"{video.stem}_{s:g}s.jpg"), composed,
                                [cv2.IMWRITE_JPEG_QUALITY, 88])
                    saved.append(s)
    finally:
        writer.release()
        face.close()
        pose.close()
    final = out_dir / f"{video.stem}.annotated.mp4"
    codec = _to_h264(raw, final)
    return {"video": final, "codec": codec, "font": font_path,
            "keyframes": [out_dir / "frames" / f"{video.stem}_{s:g}s.jpg" for s in saved]}


def _px(q, width, height):
    return int(q.x * width), int(q.y * height)


def _lines(cv2, img, lms, conns, color, thick, width, height):
    for c in conns:
        cv2.line(img, _px(lms[c.start], width, height), _px(lms[c.end], width, height), color, thick, cv2.LINE_AA)


def _panel(cv2, panel: dict, height: int, fonts) -> np.ndarray:
    from PIL import Image, ImageDraw

    f_main, f_small, f_big = fonts
    pil = Image.new("RGB", (PANEL_W, height), (18, 22, 28))
    d = ImageDraw.Draw(pil)
    ink, dim = (230, 235, 240), (160, 170, 180)
    y = 10
    d.text((14, y), f"t = {panel['t']:5.2f} s", font=f_big, fill=ink)
    y += 30
    d.text((14, y), f"人脸 {'检出' if panel['face'] else '未检出'}   姿态 {'检出' if panel['pose'] else '未检出'}",
           font=f_main, fill=dim)
    y += 26
    if panel["face"]:
        d.text((14, y), f"头姿  yaw {panel['yaw']:6.1f}°  pitch {panel['pitch']:6.1f}°  roll {panel['roll']:6.1f}°",
               font=f_main, fill=ink)
        y += 24
        d.text((14, y), f"目光  水平 {panel['gaze_h']:+.2f}  垂直 {panel['gaze_v']:+.2f}   眨眼 {panel['blink']:.2f}",
               font=f_main, fill=ink)
        y += 26
        d.text((14, y), "AU 近似（blendshape，0–1）", font=f_small, fill=dim)
        y += 20
        for name, val in panel["au"]:
            d.text((14, y), name, font=f_small, fill=(200, 205, 210))
            d.rectangle((150, y + 4, 360, y + 14), fill=(40, 46, 54))
            d.rectangle((150, y + 4, 150 + int(210 * min(1.0, val)), y + 14),
                        fill=(255, 200, 0) if val > 0.3 else (90, 150, 220))
            d.text((404, y - 1), f"{val:.2f}", font=f_small, fill=dim, anchor="ra")
            y += 19
        y += 6
        d.text((14, y), "本帧最强的 5 个 blendshape", font=f_small, fill=dim)
        y += 20
        for k, s in panel["top_bs"]:
            d.text((14, y), f"{k:<22s} {s:.2f}", font=f_small, fill=(200, 205, 210))
            y += 18
    if panel["pose"]:
        y += 6
        motion = "-" if panel["motion"] is None else f"{panel['motion']:.1f}"
        d.text((14, y), f"身体  肩倾 {panel['tilt']:+.1f}°   手触脸 {'是' if panel['hand_face'] else '否'}   小动作 {motion}",
               font=f_main, fill=ink)
    d.text((14, height - 22), "白点面部网格 · 黄轮廓 · 青虹膜 · 红绿蓝头部轴 · 绿骨架",
           font=f_small, fill=(120, 130, 140))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _to_h264(raw: pathlib.Path, final: pathlib.Path) -> str:
    exe = find_ffmpeg()
    if exe:
        done = subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(raw), "-c:v", "libx264",
                               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(final)],
                              capture_output=True, timeout=900)
        if done.returncode == 0 and final.is_file() and final.stat().st_size > 0:
            raw.unlink()
            return "h264"
    raw.replace(final)
    return "mp4v"
