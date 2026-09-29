#!/usr/bin/env bash
# 方案A-步骤4：冒烟验证（HTTP 可达性、权重加载、GPU 占用、日志报错）
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

LOG_DIR="$HOME/livetalking-logs"
PID_FILE="$LOG_DIR/app.pid"
fail=0

echo "==> [1] 进程状态"
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "OK 运行中 pid=$(cat "$PID_FILE")"
else
  echo "FAIL 进程未运行"; fail=1
fi

echo "==> [2] HTTP /index.html"
code=$(curl -s -o /dev/null -w "%{http_code}" -m 10 --noproxy "*" "http://127.0.0.1:${PORT}/index.html" || echo 000)
echo "HTTP $code"
[ "$code" = "200" ] || { echo "FAIL 首页不可达"; fail=1; }

echo "==> [3] 权重与 avatar 文件"
[ -f "$MODEL_DIR/wav2lip.pth" ] && echo "OK $MODEL_DIR/wav2lip.pth ($(stat -c%s "$MODEL_DIR/wav2lip.pth") bytes)" || { echo "FAIL 缺少权重"; fail=1; }
[ -d "$AVATAR_DIR/$AVATAR_ID" ] && echo "OK avatar: $AVATAR_DIR/$AVATAR_ID" || echo "WARN avatar 不存在: $AVATAR_DIR/$AVATAR_ID"

echo "==> [4] GPU 显存"
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader

echo "==> [5] 日志尾部（最后 20 行）"
tail -n 20 "$LOG_DIR/app.log" 2>/dev/null

echo "==> [6] 日志中的异常"
if grep -qiE "Traceback|ModuleNotFoundError|CUDA error|out of memory" "$LOG_DIR/app.log" 2>/dev/null; then
  echo "FAIL 日志存在异常:"; grep -inE "Traceback|ModuleNotFoundError|CUDA error|out of memory" "$LOG_DIR/app.log" | head -5
  fail=1
else
  echo "OK 未见异常"
fi

exit $fail
