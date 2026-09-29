###############################################################################
#  本地 TTS 适配器 —— 调用同机 tts_service.py（ChatTTS，GB10 本地推理）
#
#  部署：由 07_patch_livetalking.sh 复制到 $APP_DIR/tts/localtts.py
#  使用：--tts localtts
#
#  设计约束：
#  - 不外呼任何云端接口，只访问 127.0.0.1 的本地服务；
#  - 合成失败必须安全降级（打日志 + 静音），不能让数字人崩溃或回落到云端；
#  - 音频仅在内存中处理，不落盘。
###############################################################################

import os
import time
import io
import urllib.request
import urllib.error

import numpy as np
import soundfile as sf

from tts.base_tts import BaseTTS, State
from registry import register
from utils.logger import logger


@register("tts", "localtts")
class LocalTTS(BaseTTS):
    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        self.url = os.getenv("TTS_SERVICE_URL", "http://127.0.0.1:8090/tts")
        self.timeout = float(os.getenv("TTS_TIMEOUT", "120"))
        logger.info(f"[TTS] localtts -> {self.url}")

    def txt_to_audio(self, msg):
        text, textevent = msg
        try:
            req = urllib.request.Request(
                self.url,
                data=__import__("json").dumps({"text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                cost = resp.headers.get("X-Latency")
        except (urllib.error.URLError, OSError) as e:
            logger.error(f"[TTS] 本地合成失败，本句静音（无云端回退）: {e}")
            return

        try:
            audio, sr = sf.read(io.BytesIO(raw), dtype="float32")
        except Exception as e:
            logger.error(f"[TTS] 音频解析失败: {e}")
            return
        if sr != self.sample_rate:
            audio = self._resample(audio, sr, self.sample_rate)

        t = time.time()
        stream = audio
        streamlen = stream.shape[0]
        idx = 0
        while streamlen >= self.chunk and self.state == State.RUNNING:
            eventpoint = {}
            streamlen -= self.chunk
            if idx == 0:
                eventpoint = {"status": "start", "text": text}
            elif streamlen < self.chunk:
                eventpoint = {"status": "end", "text": text}
            eventpoint.update(**textevent)
            self.parent.put_audio_frame(stream[idx:idx + self.chunk], eventpoint)
            idx += self.chunk
        logger.info(f"[TTS] localtts 合成 {len(audio) / self.sample_rate:.2f}s 音频，"
                    f"服务端 {cost}s，切帧耗时 {time.time() - t:.4f}s")

    @staticmethod
    def _resample(audio, src_rate, dst_rate):
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(int(src_rate), int(dst_rate))
        return resample_poly(audio, int(dst_rate) // g, int(src_rate) // g).astype(np.float32)

    def stop_tts(self):
        pass
