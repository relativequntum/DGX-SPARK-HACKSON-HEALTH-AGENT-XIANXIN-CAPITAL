#!/usr/bin/env bash
# 停止 LiveTalking 服务（并可选停止本地 TTS 服务）
set -uo pipefail
LOG_DIR="$HOME/livetalking-logs"
PID_FILE="$LOG_DIR/app.pid"
if [ -f "$PID_FILE" ]; then
  pid=$(cat "$PID_FILE")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "已停止 pid=$pid"
  else
    echo "进程不存在: $pid"
  fi
  rm -f "$PID_FILE"
else
  echo "无 pid 文件，尝试按命令行匹配清理"
  pkill -f "app.py --transport" && echo "已清理" || echo "无匹配进程"
fi

# STOP_TTS=1 ./stop.sh 时一并停掉本地 TTS 服务
if [ "${STOP_TTS:-0}" = "1" ]; then
  TTS_PID_FILE="$LOG_DIR/tts.pid"
  if [ -f "$TTS_PID_FILE" ]; then
    tpid=$(cat "$TTS_PID_FILE")
    kill -0 "$tpid" 2>/dev/null && kill "$tpid" && echo "已停止本地 TTS pid=$tpid"
    rm -f "$TTS_PID_FILE"
  fi
fi
