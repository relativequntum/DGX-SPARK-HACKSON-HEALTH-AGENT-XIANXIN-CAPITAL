#!/usr/bin/env bash
# 方案A-步骤3：启动 LiveTalking 服务（WebRTC，TCP 8010 + UDP 全端口）
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

LOG_DIR="$HOME/livetalking-logs"
mkdir -p "$LOG_DIR"
PID_FILE="$LOG_DIR/app.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "!! 服务已在运行，pid=$(cat "$PID_FILE")。先执行 ./stop.sh"
  exit 1
fi

# 本地 TTS 服务必须先就绪（全本地链路，不允许回落到云端 TTS）
if [ "${TTS}" = "localtts" ]; then
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 --noproxy "*" "http://127.0.0.1:${TTS_PORT}/health" || echo 000)
  if [ "$code" != "200" ]; then
    echo "!! 本地 TTS 服务未就绪（http://127.0.0.1:${TTS_PORT}/health -> $code），请先执行 06_setup_local_tts.sh"
    exit 1
  fi
  echo "==> 本地 TTS 就绪: $TTS_SERVICE_URL"
fi

# 密钥只从本机文件读取，不写入仓库（OpenClaw 网关 token、本地模型 key）
if [ -f "$OPENCLAW_KEY_FILE" ]; then
  export OPENCLAW_API_KEY="$(cat "$OPENCLAW_KEY_FILE")"
fi
if [ -f "$LOCAL_LLM_KEY_FILE" ]; then
  export LOCAL_LLM_API_KEY="$(cat "$LOCAL_LLM_KEY_FILE")"
fi
# 按 provider 选择模型名（OpenClaw 用 agent id，本地用 llama-server 的 alias）
case "$LLM_PROVIDER" in
  openclaw) LLM_MODEL="${OPENCLAW_MODEL}" ;;
  *)        LLM_MODEL="${LOCAL_LLM_MODEL}" ;;
esac

cd "$APP_DIR"
echo "==> 启动: model=$MODEL avatar=$AVATAR_ID transport=$TRANSPORT port=$PORT tts=$TTS llm=$LLM_PROVIDER"
nohup "$VENV/bin/python" app.py \
  --transport "$TRANSPORT" \
  --model "$MODEL" \
  --avatar_id "$AVATAR_ID" \
  --modelres "${MODELRES:-256}" \
  --listenport "$PORT" \
  --tts "${TTS}" \
  --REF_FILE "${REF_FILE:-zh-CN-YunxiaNeural}" \
  --llm_provider "${LLM_PROVIDER}" \
  --llm_model "${LLM_MODEL}" \
  --max_session "${MAX_SESSION:-16}" \
  --session_timeout "${SESSION_TIMEOUT:-120}" \
  > "$LOG_DIR/app.log" 2>&1 &
echo $! > "$PID_FILE"
echo "==> pid=$(cat "$PID_FILE")，日志: $LOG_DIR/app.log"
echo "==> 访问: http://<服务器IP>:$PORT/index.html"
