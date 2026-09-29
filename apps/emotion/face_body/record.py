# -*- coding: utf-8 -*-
"""开发机上录一段摄像头视频，带逐帧时间戳（`<out>.stamps.json`，毫秒），供 analyze / annotate 对齐时间。

录的是你自己：只留本机，不入库、不上传，演示完就删。Spark 是无头服务器、没有摄像头，这个子命令只在开发机用。
"""
from __future__ import annotations

import json
import pathlib
import sys
import time


def _open(cv2, index: int):
    backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
    return cv2.VideoCapture(index, backend)


def check_cameras(indices=(0, 1)) -> list:
    import cv2

    found = []
    for index in indices:
        cap = _open(cv2, index)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        found.append({"index": index, "opened": cap.isOpened(), "frame": ok,
                      "shape": None if frame is None else list(frame.shape), "fps": cap.get(cv2.CAP_PROP_FPS)})
        cap.release()
    return found


def record(out, seconds: float = 40.0, cam: int = 0, width: int = 640, height: int = 480) -> dict:
    """录 seconds 秒（预览窗按 q 提前结束），写 mp4 与同名 .stamps.json。"""
    import cv2

    cap = _open(cv2, cam)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        raise RuntimeError(f"摄像头 {cam} 打不开；先跑 record --check 看看有哪些可用")
    h, w = frame.shape[:2]
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 30, (w, h))
    stamps = []
    countdown = time.time()
    while time.time() - countdown < 3:  # 3 秒倒计时，让人坐好
        ok, frame = cap.read()
        if ok:
            cv2.putText(frame, f"start in {3 - int(time.time() - countdown)}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 255), 2)
            cv2.imshow("record", frame)
            cv2.waitKey(1)
    started = time.time()
    try:
        while True:
            ok, frame = cap.read()
            elapsed = time.time() - started
            if not ok or elapsed >= seconds:
                break
            writer.write(frame)
            stamps.append(round(elapsed * 1000))
            shown = frame.copy()
            cv2.putText(shown, f"REC {elapsed:4.1f}/{seconds:.0f}s", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (0, 0, 255), 2)
            cv2.imshow("record", shown)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        writer.release()
        cap.release()
        cv2.destroyAllWindows()
    pathlib.Path(str(out) + ".stamps.json").write_text(json.dumps(stamps), encoding="utf-8")
    duration = stamps[-1] / 1000 if stamps else 0.0
    return {"video": out, "frames": len(stamps), "duration_s": round(duration, 1),
            "fps": round(len(stamps) / duration, 1) if duration else None, "size": [w, h]}
