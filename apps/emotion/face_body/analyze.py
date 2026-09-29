# -*- coding: utf-8 -*-
"""视频 → 逐帧特征 → 按时间窗的观察量报告。依赖 mediapipe + opencv（函数里延迟导入，测试不需要装）。

帧时间戳：同名 `<video>.stamps.json`（record 子命令录的，逐帧毫秒）优先，否则按视频标称 fps 推算。
帧只在内存里处理，不写任何图像；报告里只有数值。MediaPipe 在 CPU 上跑，不占 GPU。
"""
from __future__ import annotations

import json
import pathlib
import time

from .features import au_proxy, blink_score, euler_from_matrix, gaze_from_blendshapes, pose_features
from .models import MODELS, ensure_models, load_models, sha256_of
from .windows import build_report


def open_landmarkers(model_dir):
    """返回 (mediapipe 模块, FaceLandmarker, PoseLandmarker)，都是 VIDEO 模式、单人。"""
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    # 模型先读进内存、校验 sha256 再交给 MediaPipe：Windows 上 C++ 按路径打开含中文的目录会失败
    buffers = load_models(model_dir)
    face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_buffer=buffers["face"]),
        running_mode=vision.RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True, output_facial_transformation_matrixes=True))
    pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_buffer=buffers["pose"]),
        running_mode=vision.RunningMode.VIDEO, num_poses=1))
    return mp, face, pose


def read_stamps(video):
    path = pathlib.Path(str(video) + ".stamps.json")
    if not path.is_file():
        return None
    stamps = json.loads(path.read_text(encoding="utf-8"))
    return stamps if isinstance(stamps, list) else None


def iter_frames(video, stride: int = 1):
    """逐帧产出 (毫秒时间戳, BGR 帧)。时间戳严格递增（MediaPipe VIDEO 模式的要求）。"""
    import cv2

    stamps = read_stamps(video)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"打不开视频 {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    i, last = 0, -1
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % stride == 0:
                ts = stamps[i] if stamps and i < len(stamps) else int(i * 1000 / fps)
                ts = max(int(ts), last + 1)
                last = ts
                yield ts, frame
            i += 1
    finally:
        cap.release()


def frame_record(t: float, face_result, pose_result) -> dict:
    """一帧的特征。pose=True 要求检出姿态且双肩可见：任一肩不可见时肩倾、肩宽、前倾都没有依据，
    剩下的「小动作」只剩脸上几个点的位移（头动已由面部通道的 motion_deg_per_frame 记），这帧不算身体检出。"""
    rec = {"t": t, "face": False, "pose": False}
    if face_result.face_landmarks:
        bs = {c.category_name: c.score for c in face_result.face_blendshapes[0]}
        yaw, pitch, roll = euler_from_matrix(face_result.facial_transformation_matrixes[0])
        gaze_h, gaze_v = gaze_from_blendshapes(bs)
        rec.update(face=True, yaw=yaw, pitch=pitch, roll=roll, gaze_h=gaze_h, gaze_v=gaze_v,
                   blink=blink_score(bs), au=au_proxy(bs))
    if pose_result.pose_landmarks:
        feats = pose_features(pose_result.pose_landmarks[0])
        if feats.pop("shoulders"):
            rec.update(pose=True, **feats)
    return rec


def analyze_video(video, model_dir, window: float = 5.0, stride: int = 1) -> dict:
    import cv2

    mp, face, pose = open_landmarkers(model_dir)
    frames = []
    started = time.time()
    try:
        for ts, bgr in iter_frames(video, stride):
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            frames.append(frame_record(ts / 1000.0, face.detect_for_video(img, ts), pose.detect_for_video(img, ts)))
    finally:
        face.close()
        pose.close()
    spent = time.time() - started
    duration = frames[-1]["t"] if frames else 0.0
    paths = ensure_models(model_dir)
    meta = {
        "video": pathlib.Path(video).name,
        "stride": stride,
        "fps_source": round(len(frames) * stride / duration, 1) if duration else None,
        "process_fps": round(len(frames) / spent, 1) if spent > 0 else None,
        "process_s": round(spent, 1),
        "models": {key: {"file": spec.filename, "sha256": sha256_of(paths[key])} for key, spec in MODELS.items()},
        "mediapipe": mp.__version__,
    }
    return build_report(frames, window=window, meta=meta)
