# -*- coding: utf-8 -*-
"""把一张人脸照片做成 Chrome 假摄像头能用的 Y4M 视频（逐帧轻微转头），只用于本机冒烟测试。

    python apps/multimodal/web/tests/make_face_y4m.py --out <临时目录>/face.y4m [--image <照片>]

不给 --image 时下载 MediaPipe 官方测试图 portrait.jpg（MediaPipe 仓库的公开测试素材）。
照片和视频都只放在临时目录，**不进仓库**；不要用真实患者或同事的照片。需要 numpy、pillow。
Chrome 用法：--use-fake-device-for-media-stream --use-file-for-fake-video-capture=<face.y4m>
"""
import argparse
import math
import pathlib
import urllib.request

import numpy as np
from PIL import Image

PORTRAIT_URL = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg"
W, H, FPS, N = 640, 480, 10, 50   # 5 秒一圈，Chrome 循环播放


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--image")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    src = pathlib.Path(args.image) if args.image else out.with_name("portrait.jpg")
    if not src.is_file():
        urllib.request.urlretrieve(PORTRAIT_URL, src)
    face = Image.open(src).convert("RGB")
    face = face.resize((round(face.width * H / face.height), H))
    with open(out, "wb") as fh:
        fh.write(f"YUV4MPEG2 W{W} H{H} F{FPS}:1 Ip A1:1 C420jpeg\n".encode("ascii"))
        for k in range(N):
            frame = Image.new("RGB", (W, H), (96, 110, 118))
            turned = face.rotate(8 * math.sin(2 * math.pi * k / N), resample=Image.BICUBIC,
                                 fillcolor=(96, 110, 118))
            frame.paste(turned, ((W - turned.width) // 2, 0))
            ycc = np.asarray(frame.convert("YCbCr"), dtype=np.float32)
            y = ycc[:, :, 0].astype(np.uint8)
            u = ycc[:, :, 1].reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).round().astype(np.uint8)
            v = ycc[:, :, 2].reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3)).round().astype(np.uint8)
            fh.write(b"FRAME\n" + y.tobytes() + u.tobytes() + v.tobytes())
    print(f"写出 {out}（{N} 帧，{W}x{H}，{FPS} fps）")


if __name__ == "__main__":
    main()
