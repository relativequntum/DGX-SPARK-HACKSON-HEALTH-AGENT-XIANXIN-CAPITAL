#!/usr/bin/env bash
# 方案A-步骤2：下载 wav2lip 权重并准备数字人形象(avatar)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

mkdir -p "$MODEL_DIR" "$AVATAR_DIR"

# ---------- 1. 权重 ----------
# 默认走国内 HF 镜像（hf-mirror.com，直连 3MB/s+）；境外源可用 HF_ENDPOINT=https://huggingface.co 覆盖
: "${WEIGHT_URL:=$HF_ENDPOINT/CherryOnes/LiveTalking/resolve/main/wav2lip.pth}"
: "${WEIGHT_MIN_BYTES:=200000000}"

echo "==> 下载源: $WEIGHT_URL"
if [ -f "$MODEL_DIR/wav2lip.pth" ]; then
  echo "==> 权重已存在，跳过下载: $MODEL_DIR/wav2lip.pth"
else
  echo "==> 下载权重: $WEIGHT_URL"
  curl -fL --retry 3 --retry-delay 2 -o "$MODEL_DIR/wav2lip.pth.part" "$WEIGHT_URL"
  mv "$MODEL_DIR/wav2lip.pth.part" "$MODEL_DIR/wav2lip.pth"
fi

SIZE=$(stat -c%s "$MODEL_DIR/wav2lip.pth")
echo "==> 权重大小: $SIZE bytes"
if [ "$SIZE" -lt "$WEIGHT_MIN_BYTES" ]; then
  echo "!! 权重异常（小于 $WEIGHT_MIN_BYTES 字节），请检查下载源"
  exit 1
fi

# ---------- 2. 校验权重可被 Wav2Lip 结构加载 ----------
echo "==> 校验权重结构"
"$VENV/bin/python" - "$APP_DIR" "$MODEL_DIR/wav2lip.pth" <<'PY'
import sys, torch
app_dir, weight = sys.argv[1], sys.argv[2]
sys.path.insert(0, app_dir)
from avatars.wav2lip.models import Wav2Lip
model = Wav2Lip()
state = torch.load(weight, map_location="cpu")
state = state.get("state_dict", state)
missing = model.load_state_dict(state, strict=False)
print("missing keys:", len(missing.missing_keys), "unexpected keys:", len(missing.unexpected_keys))
print("OK: 权重与 Wav2Lip 结构匹配" if not missing.unexpected_keys else "WARN: 存在未匹配 key，需人工确认")
PY

# ---------- 3. ASR 模型（SenseVoiceSmall + FSMN-VAD）----------
# LiveTalking 的 server/asr_server.py 用 funasr 加载 iic/SenseVoiceSmall + vad_model="fsmn-vad"。
# 首次推理会自动下载（约 940MB），这里预先拉取并做一次热加载，避免首个用户请求等 20s+。
# modelscope 直连国内源即可（env.sh 已把 www.modelscope.cn 放进 NO_PROXY）
echo "==> 预取 ASR 模型并热加载验证"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
"$VENV/bin/python" - <<'PY'
import time
from modelscope import snapshot_download
for m in ("iic/SenseVoiceSmall", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"):
    print("[fetch]", m, snapshot_download(m), flush=True)

import torch
from funasr import AutoModel
t0 = time.time()
model = AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad",
                  vad_kwargs={"max_single_segment_time": 30000},
                  device="cuda:0" if torch.cuda.is_available() else "cpu",
                  trust_remote_code=True)
print("[warmup] SenseVoiceSmall ready in %.1fs on %s" % (
    time.time() - t0, "cuda:0" if torch.cuda.is_available() else "cpu"))
PY

# ---------- 4. avatar ----------
# 官方 wav2lip256_avatar1.tar.gz 仅提供网盘下载，此处支持两种方式：
#   a) 本地已有 tar.gz：AVATAR_TARBALL=/path/to/wav2lip256_avatar1.tar.gz
#   b) 用一段正面人脸视频生成：AVATAR_VIDEO=/path/to/face.mp4
if [ -n "${AVATAR_TARBALL:-}" ]; then
  echo "==> 解压 avatar: $AVATAR_TARBALL"
  tar -xzf "$AVATAR_TARBALL" -C "$AVATAR_DIR"
elif [ -n "${AVATAR_VIDEO:-}" ]; then
  echo "==> 由视频生成 avatar: $AVATAR_VIDEO"
  cd "$APP_DIR"
  "$VENV/bin/python" - "$AVATAR_VIDEO" "$AVATAR_ID" <<'PY'
import sys
sys.path.insert(0, ".")
from avatars.wav2lip.genavatar import generate_avatar
video, avatar_id = sys.argv[1], sys.argv[2]
generate_avatar(video_path=video, avatar_id=avatar_id, save_path="./data/avatars", img_size=256)
print("avatar generated:", avatar_id)
PY
else
  echo "==> 未提供 AVATAR_TARBALL / AVATAR_VIDEO，跳过 avatar 准备"
  echo "    启动前必须存在: $AVATAR_DIR/$AVATAR_ID"
fi

echo "==> 当前 avatars: $(ls "$AVATAR_DIR" 2>/dev/null | tr '\n' ' ')"
