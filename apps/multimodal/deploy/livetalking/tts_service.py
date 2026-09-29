#!/usr/bin/env python3
"""本地 TTS 服务（GB10 本地推理，不出网、不调用任何云端 API）。

仅监听 127.0.0.1，供同机的 LiveTalking 通过 tts/localtts.py 适配器调用。

    POST /tts   {"text": "..."} -> audio/wav（16kHz 单声道 PCM16）
    GET  /health -> {"ok": true, "backend": "chattts|piper", ...}

后端选择（TTS_BACKEND）：
  - auto（默认）：GPU 空闲显存 >= TTS_GPU_MIN_FREE_GB 用 chattts，否则回退 piper（CPU）
  - chattts：ChatTTS，中文自然度高，需要约 3GB 显存
  - piper：onnxruntime CPU，稳定、延迟极低、音质偏机械
显存不足时 chattts 会自动降级到 piper，保证链路不断。
"""
import io
import os
import time

import numpy as np
import soundfile as sf
from fastapi import FastAPI, Response
from pydantic import BaseModel
from scipy.signal import resample_poly

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

NATIVE_RATE = {"chattts": 24000, "piper": 22050}
OUT_RATE = 16000
DEFAULT_PIPER_DIR = os.path.expanduser("~/tts-models/piper")
# ChatTTS 不传 spk_emb 时每次 infer 都会随机采样音色（男女声逐句跳变），
# 故在启动时确定一个固定音色并落盘，保证整个会话、重启后都一致。
DEFAULT_SPK_FILE = os.path.expanduser("~/livetalking-deploy/secrets/chattts-spk.txt")

app = FastAPI()
_backend = None
_backend_name = None


class TTSRequest(BaseModel):
    text: str
    skip_refine_text: bool = True


def _gpu_free_gb():
    try:
        import torch
        free, _ = torch.cuda.mem_get_info()
        return free / 2 ** 30
    except Exception:
        return 0.0


class ChatTTSBackend:
    name = "chattts"

    def __init__(self):
        import torch
        import ChatTTS
        t0 = time.time()
        self.chat = ChatTTS.Chat()
        if not self.chat.load(source=os.getenv("CHATTTS_SOURCE", "huggingface"),
                              compile=False, device=torch.device("cuda")):
            raise RuntimeError("ChatTTS load failed")
        self.spk_emb = self._resolve_speaker()
        print(f"[tts] chattts loaded in {time.time() - t0:.1f}s, "
              f"spk={self.spk_emb[:16]}...", flush=True)

    def _resolve_speaker(self):
        """取一个固定音色：优先读盘上已固化的 spk_emb，否则按固定种子采样一次并保存。"""
        import torch

        path = os.getenv("TTS_SPK_FILE", DEFAULT_SPK_FILE)
        if os.path.isfile(path):
            try:
                spk = open(path, encoding="utf-8").read().strip()
                if spk:
                    return spk
            except Exception as e:  # noqa: BLE001
                print(f"[tts] 读取音色文件失败，重新采样: {e}", flush=True)

        # 默认种子经实测为稳定女声（F0 约 210-240Hz），与默认数字人形象配对
        seed = int(os.getenv("TTS_SPK_SEED", "2024"))
        torch.manual_seed(seed)
        spk = self.chat.sample_random_speaker()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(spk)
            os.chmod(path, 0o600)
            print(f"[tts] 生成固定音色 seed={seed} -> {path}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[tts] 音色写入失败（本次进程内仍固定）: {e}", flush=True)
        return spk

    def __call__(self, text, skip_refine_text=True):
        import ChatTTS
        params = ChatTTS.Chat.InferCodeParams(spk_emb=self.spk_emb)
        # split_text=False：文本已由 LiveTalking 按段切好再送来，
        # 让 ChatTTS 内部再切分只会多一次分词与批处理开销，拖慢出声时间。
        wavs = self.chat.infer([text], lang="zh", use_decoder=True,
                               skip_refine_text=skip_refine_text,
                               split_text=False,
                               params_infer_code=params)
        return np.asarray(wavs[0], dtype=np.float32).reshape(-1), NATIVE_RATE["chattts"]


class PiperBackend:
    name = "piper"

    def __init__(self):
        from piper import PiperVoice
        model_dir = os.getenv("PIPER_MODEL_DIR", DEFAULT_PIPER_DIR)
        model = os.path.join(model_dir, "model.onnx")
        config = os.path.join(model_dir, "model.onnx.json")
        if not (os.path.isfile(model) and os.path.isfile(config)):
            raise FileNotFoundError(f"缺少 piper 模型: {model} / {config}")
        t0 = time.time()
        self.voice = PiperVoice.load(model, config_path=config)
        print(f"[tts] piper loaded in {time.time() - t0:.1f}s", flush=True)

    def __call__(self, text, skip_refine_text=True):  # noqa: ARG002
        import wave
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            # 必须先设好声道/采样率：否则 piper 写入时抛 "channels not specified"，
            # 这条路径是 ChatTTS 失败时的兜底，坏掉会让兜底也发不出声。
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.voice.config.sample_rate)
            self.voice.synthesize(text, wf)
        buf.seek(0)
        audio, sr = sf.read(buf, dtype="float32")
        return audio, sr


def get_backend():
    global _backend, _backend_name
    if _backend is not None:
        return _backend, _backend_name

    prefer = os.getenv("TTS_BACKEND", "auto")
    min_free = float(os.getenv("TTS_GPU_MIN_FREE_GB", "3"))
    order = []
    if prefer == "chattts":
        order = ["chattts", "piper"]
    elif prefer == "piper":
        order = ["piper"]
    else:
        order = ["chattts", "piper"] if _gpu_free_gb() >= min_free else ["piper", "chattts"]

    last_err = None
    for name in order:
        try:
            _backend = ChatTTSBackend() if name == "chattts" else PiperBackend()
            _backend_name = name
            return _backend, name
        except Exception as e:  # 显存不足/权重缺失等，逐个降级
            last_err = e
            print(f"[tts] 后端 {name} 不可用，降级: {e}", flush=True)
    raise RuntimeError(f"所有 TTS 后端均不可用: {last_err}")


def warmup():
    backend, name = get_backend()
    backend("warmup")
    print(f"[tts] warmup done, backend={name}", flush=True)


@app.get("/health")
def health():
    return {"ok": _backend is not None, "backend": _backend_name,
            "gpu_free_gb": round(_gpu_free_gb(), 1), "out_rate": OUT_RATE}


@app.post("/tts")
def tts(req: TTSRequest, response: Response):
    t0 = time.time()
    text = (req.text or "").strip()
    if not text:
        response.status_code = 400
        return {"error": "empty text"}

    backend, name = get_backend()
    try:
        audio, sr = backend(text, req.skip_refine_text)
    except Exception as e:
        # 运行期失败（如 CUDA OOM）也回退一次到 piper，绝不回落云端
        print(f"[tts] {name} 合成失败，回退 piper: {e}", flush=True)
        global _backend, _backend_name
        _backend, _backend_name = PiperBackend(), "piper"
        audio, sr = _backend(text, req.skip_refine_text)

    audio = audio.reshape(-1)
    if audio.size == 0:
        response.status_code = 500
        return {"error": "empty audio"}

    if sr != OUT_RATE:
        from math import gcd
        g = gcd(int(sr), OUT_RATE)
        audio = resample_poly(audio, OUT_RATE // g, int(sr) // g).astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, audio, OUT_RATE, format="WAV", subtype="PCM_16")
    # 头必须挂在真正返回的 Response 上：挂到入参 response 会被丢弃，
    # 导致调用方（LiveTalking localtts 日志）拿不到耗时，排查延迟时看不到这一环。
    return Response(content=buf.getvalue(), media_type="audio/wav", headers={
        "X-Audio-Seconds": f"{len(audio) / OUT_RATE:.2f}",
        "X-Latency": f"{time.time() - t0:.2f}",
        "X-Backend": _backend_name,
    })


if __name__ == "__main__":
    import uvicorn

    warmup()
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("TTS_PORT", "8090")))
