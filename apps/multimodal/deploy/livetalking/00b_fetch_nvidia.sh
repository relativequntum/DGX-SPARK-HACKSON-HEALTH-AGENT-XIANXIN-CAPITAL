#!/usr/bin/env bash
# 方案A-步骤0b：预下载 torch 的 nvidia-* 大依赖（aarch64）
# 背景：这些包单个 400MB+，总量约 2.5GB；从该机默认的 files.pythonhosted.org 经代理只有 ~300KB/s，
#       而阿里云 PyPI 镜像直连可达 20MB/s+，并发 8 路约 40 秒下完。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

: "${WHEEL_DIR:=$HOME/wheels}"
: "${MIRROR_BASE:=https://mirrors.aliyun.com/pypi}"
: "${JOBS:=8}"

mkdir -p "$WHEEL_DIR"
cd "$WHEEL_DIR"

# 解析每个包的 aarch64 轮子地址（PyPI 路径与阿里云镜像路径一致，直接替换域名）
"${VENV_BIN_PY:-$(command -v python3)}" - "$WHEEL_DIR" <<'PY'
import json, sys, urllib.request
out_dir = sys.argv[1]
pkgs = [("nvidia-cuda-nvrtc","13.0.48"),("nvidia-cuda-runtime","13.0.48"),("nvidia-cuda-cupti","13.0.48"),
("nvidia-cudnn-cu13","9.13.0.50"),("nvidia-cublas","13.0.0.19"),("nvidia-cufft","12.0.0.15"),
("nvidia-curand","10.4.0.35"),("nvidia-cusolver","12.0.3.29"),("nvidia-cusparse","12.6.2.49"),
("nvidia-cusparselt-cu13","0.8.0"),("nvidia-nccl-cu13","2.27.7"),("nvidia-nvshmem-cu13","3.3.24"),
("nvidia-nvtx","13.0.39"),("nvidia-nvjitlink","13.0.39"),("nvidia-cufile","1.15.0.42")]
urls = []
for p, v in pkgs:
    with urllib.request.urlopen("https://pypi.org/pypi/%s/%s/json" % (p, v), timeout=30) as r:
        d = json.load(r)
    hit = [u["url"] for u in d["urls"] if "aarch64" in u["filename"]]
    if not hit:
        print("MISS", p, v); continue
    urls.append(hit[0])
with open("nvidia-urls.txt", "w") as f:
    f.write("\n".join(urls) + "\n")
print("解析到 %d 个轮子" % len(urls))
PY

sed "s|https://files.pythonhosted.org|${MIRROR_BASE}|" nvidia-urls.txt > aliyun-urls.txt
echo "==> 并发下载（$JOBS 路，直连不走代理）"
cat aliyun-urls.txt | xargs -P "$JOBS" -n 1 curl -sSL --noproxy "*" -O

echo "==> 完成，位于 $WHEEL_DIR："
ls -1 "$WHEEL_DIR"/*.whl | wc -l
du -sh "$WHEEL_DIR"
