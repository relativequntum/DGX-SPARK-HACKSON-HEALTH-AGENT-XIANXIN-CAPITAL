#!/usr/bin/env bash
# 阶段三（judge / face_body）在 DGX Spark 上的安装与自检。幂等、可重复执行、不需要 sudo。
#
#   bash setup_spark.sh                          # 在已部署的 $EMOTION_HOME 上重跑安装与自检
#   bash setup_spark.sh --install-from <目录>    # deploy_spark.sh 用：先把 <目录>/apps/emotion/* 换进 $EMOTION_HOME
#
# 步骤：1 venv 与依赖  2 MediaPipe 模型  3 单元测试  4 本地大模型通路  5 输出浏览服务（127.0.0.1:$VIEWER_PORT）
#       6 自动判断服务（问诊结束后跑 judge，给阶段二医生控制台的「重点」页签）
# 参数：spark.env 随部署整体替换；在 Spark 上要改的参数写进 ~/.config/emotion/spark.local.env（spark.env 先读它）。
# --install-from 换完目录后，把 deploy_spark.sh 带来的清单追加进 $EMOTION_HOME/DEPLOYED_REFS（模块 提交号 时间 ref）。
# 不碰阶段二的任何服务和文件：只读 llama-server 的 key 文件路径、问诊记录目录和数字人的在线会话接口。
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$here/spark.env"

if [ "${1:-}" = "--install-from" ]; then
  incoming="${2:?--install-from 需要目录}"
  mkdir -p "$EMOTION_HOME/apps/emotion"
  for d in "$incoming"/apps/emotion/*/; do
    m="$(basename "$d")"
    rm -rf "${EMOTION_HOME:?}/apps/emotion/$m"
    mv "$d" "$EMOTION_HOME/apps/emotion/$m"
    echo "==> 更新 apps/emotion/$m"
  done
  # 只追加、不覆盖：手工部署也可能往里写过「模块 提交号 时间」的行，前三列与这里一致
  if [ -s "$incoming/DEPLOYED_REFS.pending" ]; then
    echo "==> 记录部署版本 → $EMOTION_HOME/DEPLOYED_REFS"
    now="$(date -Iseconds)"
    while read -r m sha ref; do
      printf '%s %s %s %s\n' "$m" "$sha" "$now" "$ref"
    done < "$incoming/DEPLOYED_REFS.pending" | tee -a "$EMOTION_HOME/DEPLOYED_REFS" | sed 's/^/    /'
  fi
  rm -rf "$incoming"
  exec bash "$EMOTION_HOME/apps/emotion/deploy/setup_spark.sh"
fi

if [ -f "$EMOTION_LOCAL_ENV" ]; then
  echo "==> 用了本机覆盖参数：$EMOTION_LOCAL_ENV"
fi

cd "$EMOTION_HOME"
PY="$EMOTION_VENV/bin/python"
proxy_args=()
[ -n "$PROXY" ] && proxy_args=(--proxy "$PROXY")

echo "==> [1/6] venv 与依赖：$EMOTION_VENV"
[ -x "$PY" ] || python3 -m venv "$EMOTION_VENV"
"$PY" -m pip install -q --disable-pip-version-check -i "$PIP_MIRROR" "${proxy_args[@]}" -r "$here/requirements-spark.txt"
# mediapipe 依赖 opencv-contrib-python；同一 venv 再有 opencv-python-headless 会互相覆盖 cv2，清掉并重装 contrib
if "$PY" -m pip show opencv-python-headless >/dev/null 2>&1; then
  "$PY" -m pip uninstall -y -q opencv-python-headless
  "$PY" -m pip install -q --disable-pip-version-check --force-reinstall --no-deps -i "$PIP_MIRROR" \
    "${proxy_args[@]}" "opencv-contrib-python==$("$PY" -c 'import importlib.metadata as m; print(m.version("opencv-contrib-python"))')"
fi
"$PY" -c "import mediapipe, cv2, numpy, PIL, openai; print('    mediapipe', mediapipe.__version__, '| opencv', cv2.__version__, '| numpy', numpy.__version__)"

echo "==> [2/6] MediaPipe 模型：$FACE_BODY_MODEL_DIR"
if [ -d apps/emotion/face_body ]; then
  "$PY" -m apps.emotion.face_body fetch-models --models "$FACE_BODY_MODEL_DIR" "${proxy_args[@]}" | sed 's/^/    /'
else
  echo "    跳过：没有部署 face_body"
fi

echo "==> [3/6] 单元测试（两个模块分开跑）"
for m in judge face_body; do
  if [ -d "apps/emotion/$m/tests" ]; then
    printf '    %-10s ' "$m"
    "$PY" -m pytest -q -p no:cacheprovider "apps/emotion/$m/tests" | tail -1
  fi
done

echo "==> [4/6] judge → 本地大模型：$LOCAL_LLM_BASE_URL（$LOCAL_LLM_MODEL）"
if [ -d apps/emotion/judge ]; then
  if curl -sf -m 5 "${LOCAL_LLM_BASE_URL%/v1}/health" >/dev/null && [ -r "$LOCAL_LLM_KEY_FILE" ]; then
    echo "    llama-server 在线，key 文件可读"
  else
    echo "!!  llama-server 不在线或 key 文件不可读：先启动阶段二的 qwen36 服务，或 judge 改用 --backend ollama"
  fi
fi

echo "==> [5/6] 输出浏览服务：127.0.0.1:$VIEWER_PORT → $EMOTION_OUT"
mkdir -p "$EMOTION_OUT/judge" "$EMOTION_OUT/face_body"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"
sed -e "s|@PORT@|$VIEWER_PORT|g" -e "s|@DIR@|$EMOTION_OUT|g" "$here/emotion-viewer.service" > "$unit_dir/emotion-viewer.service"
systemctl --user daemon-reload
systemctl --user enable -q emotion-viewer.service
systemctl --user restart emotion-viewer.service
for _ in 1 2 3 4 5 6; do
  curl -sf -m 2 "http://127.0.0.1:$VIEWER_PORT/" >/dev/null && break
  sleep 1
done
if curl -sf -m 2 "http://127.0.0.1:$VIEWER_PORT/" >/dev/null; then
  echo "    在线。本机：ssh 加 -L $VIEWER_PORT:127.0.0.1:$VIEWER_PORT，然后打开 http://127.0.0.1:$VIEWER_PORT/"
else
  echo "!!  浏览服务没起来：journalctl --user -u emotion-viewer -n 20"
  exit 1
fi

echo "==> [6/6] 自动判断服务：问诊结束后跑 judge → $EMOTION_OUT/judge/consult/（医生控制台「重点」页签读这里）"
if [ -f apps/emotion/judge/watch.py ]; then
  mkdir -p "$EMOTION_OUT/judge/consult"
  sed -e "s|@EMOTION_HOME@|$EMOTION_HOME|g" -e "s|@DEPLOY_DIR@|$here|g" \
    "$here/emotion-judge-watch.service" > "$unit_dir/emotion-judge-watch.service"
  systemctl --user daemon-reload
  systemctl --user enable -q emotion-judge-watch.service
  systemctl --user restart emotion-judge-watch.service
  sleep 3
  if systemctl --user is-active -q emotion-judge-watch.service; then
    echo "    在线。日志：journalctl --user -u emotion-judge-watch -f（只有会话编号和命中数，没有对话内容）"
  else
    echo "!!  自动判断服务没起来：journalctl --user -u emotion-judge-watch -n 20"
    exit 1
  fi
else
  echo "    跳过：部署的 judge 里没有 watch.py"
fi
echo "==> 完成。日常命令见 apps/emotion/deploy/README.md"
