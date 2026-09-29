# -*- coding: utf-8 -*-
"""MediaPipe 模型文件：官方下载地址 + sha256。权重不进仓库（AGENTS.md），用 fetch-models 下载到本地目录。

默认目录：环境变量 FACE_BODY_MODEL_DIR，否则本包下的 models/（.gitignore 已挡住任何 models/ 目录）。
Spark 上直连 Google storage 可能慢，可以走局域网代理：fetch-models --proxy http://<代理>。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import urllib.request
from collections import namedtuple

ModelSpec = namedtuple("ModelSpec", "filename url sha256")

_BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS = {
    "face": ModelSpec("face_landmarker.task",
                      f"{_BASE}/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
                      "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"),
    "pose": ModelSpec("pose_landmarker_full.task",
                      f"{_BASE}/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task",
                      "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1"),
}


def default_model_dir() -> pathlib.Path:
    env = (os.environ.get("FACE_BODY_MODEL_DIR") or "").strip()
    return pathlib.Path(env).expanduser() if env else pathlib.Path(__file__).resolve().parent / "models"


def ensure_models(model_dir) -> dict:
    model_dir = pathlib.Path(model_dir)
    paths = {key: model_dir / spec.filename for key, spec in MODELS.items()}
    missing = [p.name for p in paths.values() if not p.is_file() or p.stat().st_size == 0]
    if missing:
        raise FileNotFoundError(f"{model_dir} 里缺模型文件 {', '.join(missing)}；先运行 "
                                f"python -m apps.emotion.face_body fetch-models --models {model_dir}")
    return paths


def load_models(model_dir) -> dict:
    """{key: 模型字节}，交给 MediaPipe 前先校验 sha256（校验的就是要加载的那份字节）。
    对不上抛 ValueError：文件被换过或不完整，重跑 fetch-models（它会重新下载校验不过的文件）。"""
    paths = ensure_models(model_dir)
    out = {}
    for key, spec in MODELS.items():
        data = paths[key].read_bytes()
        got = hashlib.sha256(data).hexdigest()
        if got != spec.sha256:
            raise ValueError(f"{paths[key]} 校验失败：sha256 {got[:12]}… 与登记的 {spec.sha256[:12]}… 不一致；"
                             f"重新运行 python -m apps.emotion.face_body fetch-models --models {model_dir}")
        out[key] = data
    return out


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_models(model_dir, proxy: str | None = None, timeout: float = 120) -> dict:
    """下载缺的或校验不过的模型；先写 .part，sha256 对上才改名，对不上删掉并抛 ValueError。"""
    model_dir = pathlib.Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for key, spec in MODELS.items():
        dest = model_dir / spec.filename
        if not (dest.is_file() and sha256_of(dest) == spec.sha256):
            part = model_dir / (spec.filename + ".part")
            try:
                _download(spec.url, part, proxy=proxy, timeout=timeout)
                got = sha256_of(part)
                if got != spec.sha256:
                    raise ValueError(f"{spec.filename} 校验失败：sha256 {got[:12]}… 与登记的 {spec.sha256[:12]}… 不一致")
                part.replace(dest)
            finally:
                if part.exists():
                    part.unlink()
        out[key] = dest
    return out


def _download(url: str, dest: pathlib.Path, proxy: str | None = None, timeout: float = 120) -> None:
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    with opener.open(url, timeout=timeout) as resp, open(dest, "wb") as fh:
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            fh.write(chunk)
