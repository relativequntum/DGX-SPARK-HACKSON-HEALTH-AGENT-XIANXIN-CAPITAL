#!/usr/bin/env bash
# 方案A-步骤0：并发分段下载 aarch64/cu130 的 torch 轮子
# 背景：该机到 download.pytorch.org 单连接仅 ~75KB/s，走代理被 403；
#       并发 8~16 段可到 ~750KB/s+，512MB 轮子约 10 分钟。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

: "${TORCH_WHEEL:=$HOME/torch-2.9.1+cu130-cp312-aarch64.whl}"
: "${SEGMENTS:=16}"

if [ -f "$TORCH_WHEEL" ]; then
  echo "==> 轮子已存在: $TORCH_WHEEL ($(stat -c%s "$TORCH_WHEEL") bytes)"
  exit 0
fi

URL="https://download.pytorch.org/whl/cu130/torch-2.9.1%2Bcu130-cp312-cp312-manylinux_2_28_aarch64.whl"
SIZE=$(curl -sI -m 30 --noproxy "*" "$URL" | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r')
if [ -z "$SIZE" ]; then
  echo "!! 无法获取文件大小，请检查 download.pytorch.org 直连"
  exit 1
fi
echo "==> 目标大小: $SIZE bytes，分段: $SEGMENTS"

TMP=$(mktemp -d)
CHUNK=$(( (SIZE + SEGMENTS - 1) / SEGMENTS ))
for i in $(seq 0 $((SEGMENTS - 1))); do
  s=$((i * CHUNK)); e=$((s + CHUNK - 1))
  [ "$e" -ge "$SIZE" ] && e=$((SIZE - 1))
  [ "$s" -ge "$SIZE" ] && break
  curl -s --noproxy "*" --retry 5 --retry-delay 2 -r "${s}-${e}" -o "$TMP/part.$i" "$URL" &
done
wait

cat $(ls -v "$TMP"/part.* 2>/dev/null || ls "$TMP"/part.* | sort -t. -k2 -n) > "$TORCH_WHEEL"
rm -rf "$TMP"

GOT=$(stat -c%s "$TORCH_WHEEL")
echo "==> 下载完成: $GOT bytes"
if [ "$GOT" -ne "$SIZE" ]; then
  echo "!! 大小不一致（期望 $SIZE），删除后重试"
  rm -f "$TORCH_WHEEL"; exit 1
fi
echo "OK $TORCH_WHEEL"
