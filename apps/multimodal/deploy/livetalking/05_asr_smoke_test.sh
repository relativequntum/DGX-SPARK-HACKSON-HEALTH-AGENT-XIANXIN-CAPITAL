#!/usr/bin/env bash
# 方案A-步骤5：本地 ASR（SenseVoice）端到端冒烟 —— 走 /api/asr WebSocket 真实转写
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

LOG_DIR="$HOME/livetalking-logs"
PID_FILE="$LOG_DIR/app.pid"
fail=0

echo "==> [1/4] 服务进程"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "OK 运行中 pid=$(cat "$PID_FILE")"
else
  echo "FAIL 服务未运行，请先执行 03_run.sh"; exit 1
fi

echo "==> [2/4] ASR 端点注册状态"
if grep -q "Local SenseVoice ASR endpoint enabled" "$LOG_DIR/app.log" 2>/dev/null; then
  echo "OK /api/asr 已注册"
else
  echo "FAIL 日志未见端点启用（funasr 是否已安装？）"; fail=1
fi

echo "==> [3/4] 准备测试音频"
WAV="${ASR_TEST_WAV:-$HOME/asr_smoke.wav}"
if [ -f "$WAV" ]; then
  echo "OK 复用已有音频: $WAV"
else
  TEXT="${ASR_TEST_TEXT:-我最近两天有点头痛，还伴随轻微咳嗽，没有发烧。}"
  MP3="$HOME/asr_smoke.mp3"
  echo "    用 edge-tts 合成测试句（需外网，走代理）: $TEXT"
  if http_proxy="$PROXY" https_proxy="$PROXY" "$VENV/bin/edge-tts" \
      --voice "${REF_FILE:-zh-CN-YunxiaNeural}" --text "$TEXT" --write-media "$MP3"; then
    "$VENV/bin/python" - "$MP3" "$WAV" <<'PY'
import sys, subprocess, imageio_ffmpeg
subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                "-i", sys.argv[1], "-ar", "16000", "-ac", "1", sys.argv[2]], check=True)
print("OK 已转码 16kHz 单声道 wav:", sys.argv[2])
PY
  else
    echo "FAIL edge-tts 合成失败；可改为提供 ASR_TEST_WAV=/path/to/16k.wav 重跑"; exit 1
  fi
fi

echo "==> [4/4] WebSocket /api/asr 转写"
"$VENV/bin/python" - "$WAV" "$PORT" <<'PY'
import sys, json, asyncio, time
import numpy as np, soundfile as sf, aiohttp

wav, port = sys.argv[1], sys.argv[2]

async def main():
    audio, sr = sf.read(wav)
    pcm = (audio * 32767).astype(np.int16).tobytes()
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://127.0.0.1:%s/api/asr" % port) as ws:
            await ws.send_str(json.dumps({"is_speaking": True, "mode": "offline", "itn": True}))
            for i in range(0, len(pcm), 640):          # 20ms/帧 送入，模拟浏览器录音
                await ws.send_bytes(pcm[i:i + 640])
            t0 = time.time()
            await ws.send_str(json.dumps({"is_speaking": False}))
            msg = await asyncio.wait_for(ws.receive(), timeout=180)
            data = json.loads(msg.data)
            print("text   :", data.get("text"))
            print("latency: %.2fs" % (time.time() - t0))
            return 0 if data.get("text") else 1

sys.exit(asyncio.run(main()))
PY
[ $? -eq 0 ] || { echo "FAIL 转写为空或失败"; fail=1; }

exit $fail
