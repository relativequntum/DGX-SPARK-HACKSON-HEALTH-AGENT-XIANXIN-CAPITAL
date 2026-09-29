#!/usr/bin/env bash
# 方案A-步骤14：部署医生端控制台（会话列表 / 文字版对话 / 医生参考版总结）
#
# 组成：
#   1. doctor_service.py —— 独立 venv 的 FastAPI 服务（默认监听 0.0.0.0:8110），
#      既提供 /api/doctor/* 只读接口，也静态托管 doctor.html/css/js（同源，无需跨域配置）；
#   2. patches/consult_recorder.py —— 由 07_patch_livetalking.sh 装到 LiveTalking，
#      llm.py 每轮问诊把患者原话与助手回复追加写入 DOCTOR_RECORD_DIR/<sessionid>.jsonl。
#
# 前置：先执行 07_patch_livetalking.sh 并重启 03_run.sh，否则不会有问诊记录落盘。
# 幂等：可重复执行（会重启本服务，不影响 LiveTalking）。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

LOG_DIR="$HOME/livetalking-logs"
PID_FILE="$LOG_DIR/doctor.pid"
mkdir -p "$LOG_DIR" "$DOCTOR_DIR" "$DOCTOR_WEB_DIR"

# 仓库内：deploy/livetalking/../../web；租机平铺拷贝：同目录 ./web
WEB_SRC="${WEB_SRC:-}"
if [ -z "$WEB_SRC" ]; then
  if [ -d ../../web ]; then
    WEB_SRC="$(cd ../../web && pwd)"
  elif [ -d ./web ]; then
    WEB_SRC="$(cd ./web && pwd)"
  else
    echo "!! 找不到前端源码目录，请显式指定：WEB_SRC=/path/to/web bash 14_setup_doctor_console.sh"
    exit 1
  fi
fi

FILES=(doctor.html doctor.css doctor.js)
for f in "${FILES[@]}"; do
  [ -f "$WEB_SRC/$f" ] || { echo "!! 缺少源文件 $WEB_SRC/$f"; exit 1; }
done

echo "==> [1/5] 部署医生端页面：$WEB_SRC -> $DOCTOR_WEB_DIR"
if [ "$WEB_SRC" = "$DOCTOR_WEB_DIR" ]; then
  echo "    源目录即部署目录，跳过复制（租机平铺部署时常见）"
else
  for f in "${FILES[@]}"; do
    cp -f "$WEB_SRC/$f" "$DOCTOR_WEB_DIR/$f"
    echo "    $f"
  done
fi

echo "==> [2/5] 准备独立 venv: $DOCTOR_VENV"
if [ ! -d "$DOCTOR_VENV" ]; then
  python3 -m venv "$DOCTOR_VENV"
fi
PIPOPT=(-i "$PIP_MIRROR" --trusted-host "$PIP_TRUSTED" --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES")
# 该机经代理访问 PyPI 只有 ~300KB/s，装包必须绕开代理直连国内镜像
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
"$DOCTOR_VENV/bin/python" -m pip install -q -U pip "${PIPOPT[@]}"
"$DOCTOR_VENV/bin/python" -m pip install -q fastapi uvicorn "${PIPOPT[@]}"

echo "==> [3/5] 准备问诊记录目录：$DOCTOR_RECORD_DIR（权限 700）"
mkdir -p "$DOCTOR_RECORD_DIR"
chmod 700 "$DOCTOR_RECORD_DIR"

echo "==> [4/5] 启动医生端服务（${DOCTOR_HOST}:${DOCTOR_PORT}）"
if [ "$(pwd)" = "$DOCTOR_DIR" ]; then
  echo "    服务已在部署目录，跳过复制"
else
  cp -f ./doctor_service.py "$DOCTOR_DIR/doctor_service.py"
fi
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  sleep 1
fi
export DOCTOR_PORT DOCTOR_HOST DOCTOR_WEB_DIR DOCTOR_RECORD_DIR DOCTOR_RECORD
export DOCTOR_LT_ADMIN_URL DOCTOR_ACTIVE_WINDOW
nohup "$DOCTOR_VENV/bin/python" "$DOCTOR_DIR/doctor_service.py" > "$LOG_DIR/doctor.log" 2>&1 &
echo $! > "$PID_FILE"
echo "    pid=$(cat "$PID_FILE")，日志: $LOG_DIR/doctor.log"

echo "==> [5/5] 健康检查"
code=000
for _ in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 --noproxy "*" "http://127.0.0.1:${DOCTOR_PORT}/health" || echo 000)
  [ "$code" = "200" ] && break
  sleep 1
done
echo "    /health HTTP $code"
curl -s -m 5 --noproxy "*" "http://127.0.0.1:${DOCTOR_PORT}/health"
echo

echo "==> 完成"
echo "    医生工作台：http://<host>:${DOCTOR_PORT}/"
echo "    示例数据（不连后端）：http://<host>:${DOCTOR_PORT}/?demo=1"
echo "    停止服务：kill \$(cat $PID_FILE)"
echo "    注意：若仍拿不到会话，确认 07_patch_livetalking.sh 已执行并重启过 LiveTalking（03_run.sh）。"
