#!/usr/bin/env bash
# 方案A-步骤13：部署阶段二预问诊前端页面（apps/multimodal/web）到 LiveTalking 静态目录
#
# 只拷贝静态文件，不重启服务（aiohttp 的 add_static 每次请求都读磁盘）。
# 幂等：可重复执行。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

WEB_SRC="${WEB_SRC:-}"
if [ -z "$WEB_SRC" ]; then
  # 仓库内：deploy/livetalking/../../web；租机平铺拷贝：同目录 ./web
  if [ -d ../../web ]; then
    WEB_SRC="$(cd ../../web && pwd)"
  elif [ -d ./web ]; then
    WEB_SRC="$(cd ./web && pwd)"
  else
    echo "!! 找不到前端源码目录，请显式指定：WEB_SRC=/path/to/apps/multimodal/web bash 13_deploy_web.sh"
    exit 1
  fi
fi
DEST="$APP_DIR/web"
FILES=(triage.html triage.css triage.js mic-asr.js camera-metrics.js camera-observe.js doctor.html doctor.css doctor.js)
# 页面通过这些上游文件实现录音（Recorder 库），缺失则语音交互不可用
DEPS=(asr/recorder-core.js asr/pcm.js)

echo "==> 部署预问诊前端：$WEB_SRC -> $DEST"
for f in "${FILES[@]}"; do
  [ -f "$WEB_SRC/$f" ] || { echo "!! 缺少源文件 $WEB_SRC/$f"; exit 1; }
done

mkdir -p "$DEST"
for f in "${FILES[@]}"; do
  cp -f "$WEB_SRC/$f" "$DEST/$f"
  echo "    $f"
done

echo "==> 依赖自检"
for dep in "${DEPS[@]}"; do
  if [ -f "$DEST/$dep" ]; then
    echo "    OK   $dep"
  else
    echo "    !!   缺少 $DEST/$dep（录音/识别会不可用，请先确认上游 LiveTalking 源码完整）"
  fi
done
if [ -f "$DEST/vendor/mediapipe/vision_bundle.js" ]; then
  echo "    OK   vendor/mediapipe（摄像头观察，版本 $(cat "$DEST/vendor/mediapipe/VERSION" 2>/dev/null || echo 未知)）"
else
  echo "    --   没有 vendor/mediapipe：患者页的「摄像头观察」会显示不可用，问诊不受影响（装它跑 15_setup_camera_assets.sh）"
fi

echo "==> 完成"
echo "    设计预览（不连后端）：http://<host>:$PORT/triage.html?demo=1"
echo "    正式使用：          http://<host>:$PORT/triage.html"
echo "    医生工作台入口：    http://<host>:$PORT/doctor.html（接口自动指向 :$DOCTOR_PORT）"
echo "    提示：页面自带 TURN relay 逻辑（不依赖 index.html 的 STUN 复选框），"
echo "          走 SSH 隧道时用 LOCAL_TURN_URLS 指定本地 TURN 端口后重启 03_run.sh 生效。"
