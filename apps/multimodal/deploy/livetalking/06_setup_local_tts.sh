#!/usr/bin/env bash
# 方案A-步骤6：本地 TTS（ChatTTS）——独立 venv + 127.0.0.1 回环服务，替换云端 edgetts
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

LOG_DIR="$HOME/livetalking-logs"
PID_FILE="$LOG_DIR/tts.pid"
mkdir -p "$LOG_DIR"

echo "==> [1/5] 创建独立 venv: $TTS_VENV"
[ -d "$TTS_VENV" ] || python3 -m venv "$TTS_VENV"
PY="$TTS_VENV/bin/python"
PIPOPT=(-i "$PIP_MIRROR" --trusted-host "$PIP_TRUSTED" --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES")
# 该机经代理访问 PyPI 只有 ~300KB/s，装包必须绕开代理直连国内镜像
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

"$PY" -m pip install -q -U pip wheel setuptools "${PIPOPT[@]}"

echo "==> [2/5] 安装 torch（优先离线轮子，避免被 pip 解析成 CPU 版）"
TORCH_CANON="$HOME/wheels/torch-${TORCH_VERSION}+cu130-cp312-cp312-manylinux_2_28_aarch64.whl"
if [ -f "$TORCH_CANON" ]; then
  if compgen -G "$HOME/wheels/nvidia_*.whl" > /dev/null; then
    "$PY" -m pip install -q --no-index --find-links "$HOME/wheels" \
      nvidia-cuda-nvrtc nvidia-cuda-runtime nvidia-cuda-cupti nvidia-cudnn-cu13 \
      nvidia-cublas nvidia-cufft nvidia-curand nvidia-cusolver nvidia-cusparse \
      nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvshmem-cu13 nvidia-nvtx \
      nvidia-nvjitlink nvidia-cufile
  fi
  "$PY" -m pip install --no-deps "$TORCH_CANON"
else
  "$PY" -m pip install "torch==${TORCH_VERSION}" --index-url "$TORCH_INDEX" "${PIPOPT[@]}"
fi

echo "==> [3/5] 安装 torchaudio（必须与 torch 同版本，否则 pip 会连带换掉 torch）"
mkdir -p "$HOME/tts-wheels"
"$PY" -m pip download --no-deps -q -d "$HOME/tts-wheels" "torchaudio==${TORCH_VERSION}" "${PIPOPT[@]}"
"$PY" -m pip install --no-deps "$HOME"/tts-wheels/torchaudio-*.whl

echo "==> [4/5] 安装 ChatTTS 与依赖（锁版本，防止依赖解析覆盖 torch）"
# ChatTTS 用到 transformers 5.x 的 DynamicCache.layers，低版本会报 AttributeError
"$PY" -m pip install "transformers==5.17.0" "${PIPOPT[@]}"
"$PY" -m pip install numba "${PIPOPT[@]}"
"$PY" -m pip install --no-deps vocos vector_quantize_pytorch pybase16384 tqdm einops encodec \
  scipy soundfile librosa einx frozendict sympy mpmath torch_einops_utils lazy_loader cffi soxr "${PIPOPT[@]}"
"$PY" -m pip install --no-deps ChatTTS "${PIPOPT[@]}"
"$PY" -m pip install fastapi uvicorn "${PIPOPT[@]}"
"$PY" -c "import torch, torchaudio, ChatTTS; assert torch.cuda.is_available(); print('torch=%s torchaudio=%s cuda=True' % (torch.__version__, torchaudio.__version__))"

echo "==> [5/5] 启动本地 TTS 服务（127.0.0.1:${TTS_PORT}）"
cp -f ./tts_service.py "$HOME/tts_service.py"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "    服务已在运行 pid=$(cat "$PID_FILE")"
else
  export TTS_PORT
  export HF_ENDPOINT
  nohup "$TTS_VENV/bin/python" "$HOME/tts_service.py" > "$LOG_DIR/tts.log" 2>&1 &
  echo $! > "$PID_FILE"
  echo "==> pid=$(cat "$PID_FILE")，日志: $LOG_DIR/tts.log（首次启动会拉权重并 warmup）"
fi

for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 --noproxy "*" "http://127.0.0.1:${TTS_PORT}/health" || echo 000)
  [ "$code" = "200" ] && break
  sleep 5
done
echo "==> /health: $(curl -s -m 5 --noproxy "*" "http://127.0.0.1:${TTS_PORT}/health")"

echo "==> 完成。TTS 服务仅监听 127.0.0.1，不对外暴露"
