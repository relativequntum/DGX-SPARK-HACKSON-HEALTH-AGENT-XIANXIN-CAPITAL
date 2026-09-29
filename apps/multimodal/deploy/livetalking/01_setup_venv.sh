#!/usr/bin/env bash
# 方案A-步骤1：在宿主机创建 venv 并安装 PyTorch(aarch64+cu130) 与项目依赖
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

PIPOPT=(-i "$PIP_MIRROR" --trusted-host "$PIP_TRUSTED" --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES")
echo "==> [1/6] 创建虚拟环境: $VENV"
python3 -m venv "$VENV"
PY="$VENV/bin/python"

# 本地轮子目录（torch + nvidia-* 大包，避免走代理/低带宽源）
[ -d "$HOME/wheels" ] && PIPOPT+=(--find-links "$HOME/wheels")

echo "==> [2/6] 升级 pip"
"$PY" -m pip install -q -U pip wheel setuptools "${PIPOPT[@]}"

echo "==> [3/6] 安装 torch==${TORCH_VERSION} (aarch64/cu130)"
# pip 要求 wheel 文件名符合规范（name-version-python-abi-platform），本地文件名需规范化
WHEEL_CANON="$HOME/wheels/torch-${TORCH_VERSION}+cu130-cp312-cp312-manylinux_2_28_aarch64.whl"
if [ -f "$TORCH_WHEEL" ] && [ "$TORCH_WHEEL" != "$WHEEL_CANON" ]; then
  mkdir -p "$HOME/wheels"
  cp -f "$TORCH_WHEEL" "$WHEEL_CANON"
fi
if [ -f "$WHEEL_CANON" ]; then TORCH_WHEEL="$WHEEL_CANON"; fi

if [ -f "$TORCH_WHEEL" ]; then
  echo "    使用本地轮子: $TORCH_WHEEL"
  # nvidia-* 大包（约 2.5GB）优先离线安装：联网拉取在该机上非常慢
  if compgen -G "$HOME/wheels/nvidia_*.whl" > /dev/null; then
    echo "    离线安装 nvidia-* 依赖（--no-index --find-links ~/wheels）"
    "$PY" -m pip install --no-index --find-links "$HOME/wheels" \
      nvidia-cuda-nvrtc nvidia-cuda-runtime nvidia-cuda-cupti nvidia-cudnn-cu13 \
      nvidia-cublas nvidia-cufft nvidia-curand nvidia-cusolver nvidia-cusparse \
      nvidia-cusparselt-cu13 nvidia-nccl-cu13 nvidia-nvshmem-cu13 nvidia-nvtx \
      nvidia-nvjitlink nvidia-cufile
  else
    echo "    ~/wheels 无 nvidia 轮子，改为联网安装（该机较慢，建议先跑 00b_fetch_nvidia.sh）"
    "$PY" -m pip install "torch==${TORCH_VERSION}" "${PIPOPT[@]}"
    TORCH_WHEEL=""
  fi
  if [ -n "$TORCH_WHEEL" ]; then
    "$PY" -m pip install --no-deps "$TORCH_WHEEL" "${PIPOPT[@]}"
  fi
else
  echo "    未找到本地轮子，改为联网拉取（该机直连 pytorch 很慢，建议先跑 00_fetch_torch.sh）"
  "$PY" -m pip install "torch==${TORCH_VERSION}" --index-url "$TORCH_INDEX" "${PIPOPT[@]}"
fi

echo "==> [4/6] 安装项目依赖"
# 这里只访问国内镜像，必须绕开代理（该机经代理访问 PyPI 只有 ~300KB/s，直连 20MB/s+）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
cd "$APP_DIR"
if [ -f "$HOME/wheels/req-urls.txt" ]; then
  echo "    离线安装（--no-index --find-links ~/wheels）"
  "$PY" -m pip install --no-index --find-links "$HOME/wheels" -r requirements.txt
else
  echo "    ~/wheels 无依赖清单，改为联网安装（慢，建议先跑 00c_fetch_reqs.sh）"
  "$PY" -m pip install -r requirements.txt "${PIPOPT[@]}"
fi

echo "==> [5/6] 安装 ASR 依赖（funasr + fbank 后端）"
# LiveTalking 的 /api/asr 需要 funasr；funasr 做特征提取必须有 fbank 后端，
# aarch64 上拿不到与 torch 2.9.1+cu130 匹配的 torchaudio 轮子（download.pytorch.org 无 aarch64 版），
# 因此改用 kaldi-native-fbank（有 cp312 aarch64 轮子）。
# imageio-ffmpeg 仅用于 ASR 冒烟时把测试音频转成 16k wav。
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
"$PY" -m pip install -q funasr kaldi-native-fbank imageio-ffmpeg "${PIPOPT[@]}"
"$PY" -c "import funasr, kaldi_native_fbank; print('funasr=%s knf=%s' % (funasr.__version__, kaldi_native_fbank.__version__))"

echo "==> [6/6] 校验 torch 与 CUDA（依赖解析可能覆盖 torch，此处兜底重装）"
if ! "$PY" - <<'PY'
import sys, torch
ok = torch.cuda.is_available() and torch.version.cuda is not None
print("torch=%s cuda=%s available=%s" % (torch.__version__, torch.version.cuda, torch.cuda.is_available()))
print("device:", torch.cuda.get_device_name(0) if ok else "N/A")
sys.exit(0 if ok else 1)
PY
then
  echo "!! torch 被依赖覆盖为 CPU 版，重装 torch==${TORCH_VERSION}"
  "$PY" -m pip install --force-reinstall --no-deps "torch==${TORCH_VERSION}" --index-url "$TORCH_INDEX"
  "$PY" -c "import torch;print('torch=%s cuda=%s available=%s' % (torch.__version__, torch.version.cuda, torch.cuda.is_available()))"
fi

echo "==> 完成。环境: $VENV"
