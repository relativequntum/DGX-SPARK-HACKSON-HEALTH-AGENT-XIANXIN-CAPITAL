#!/usr/bin/env bash
# 方案A-步骤0c：预下载 requirements.txt 的全部轮子
# 背景：该机 pip 经代理/直连混合环境下载只有 ~300KB/s，而 curl 直连镜像可达 20MB/s+。
#       做法：先用 pip --dry-run --report 解析出完整依赖树的下载地址，再用 curl 并发拉取。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

: "${WHEEL_DIR:=$HOME/wheels}"
: "${JOBS:=8}"

# 只访问国内镜像，绕开代理
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

mkdir -p "$WHEEL_DIR"
cd "$APP_DIR"

echo "==> 解析依赖树（--dry-run，不下载大文件）"
"$VENV/bin/python" -m pip install --dry-run --ignore-installed \
  --report "$WHEEL_DIR/report.json" -r requirements.txt \
  -i "$PIP_MIRROR" --trusted-host "$PIP_TRUSTED" > /dev/null

"$VENV/bin/python" - "$WHEEL_DIR" <<'PY'
import json, sys
d = json.load(open(sys.argv[1] + "/report.json"))
urls = []
for item in d.get("download", []):
    info = item.get("download_info") or {}
    u = info.get("url")
    if u:
        urls.append(u)
urls = sorted(set(urls))
open(sys.argv[1] + "/req-urls.txt", "w").write("\n".join(urls) + "\n")
print("解析到 %d 个轮子" % len(urls))
PY

cd "$WHEEL_DIR"
echo "==> 并发下载（$JOBS 路）"
cat req-urls.txt | xargs -P "$JOBS" -n 1 curl -sSL --noproxy "*" -O

echo "==> 完成："
ls -1 "$WHEEL_DIR"/*.whl 2>/dev/null | wc -l
du -sh "$WHEEL_DIR"
