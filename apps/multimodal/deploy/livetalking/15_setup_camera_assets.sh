#!/usr/bin/env bash
# 方案A-步骤15：患者页「摄像头观察」用的静态资源（MediaPipe Tasks Vision 网页版 + 两个模型）
#
# 装到 $APP_DIR/web/vendor/mediapipe/（LiveTalking 的静态目录，按请求读磁盘，不需要重启服务）：
#   vision_bundle.js（经典脚本，定义全局 Vision；患者页用它）、vision_bundle.mjs、wasm/*、package.json、VERSION、
#   face_landmarker.task、pose_landmarker_full.task
# 来源：
#   - 网页版：npm pack @mediapipe/tasks-vision@$CAM_TASKS_VISION_VERSION，先走 $CAM_NPM_REGISTRY（国内镜像，直连），
#     失败再走 npm 官方源（用 env.local.sh 的 PROXY）；两条都不通时在开发机下载 tgz 离线装：
#       CAM_ASSETS_TGZ=<mediapipe-tasks-vision-版本.tgz> bash 15_setup_camera_assets.sh
#     不管哪种来源，都按 CAM_TASKS_VISION_INTEGRITY（npm 登记的 sha512）校验；
#   - 模型：从阶段三的模型目录 $CAM_MODEL_DIR（默认 ~/emotion-models/mediapipe）复制，按 face_body/models.py 的 sha256 校验。
# 这些文件不进仓库（第三方二进制、体积大；.gitignore 已挡住 web/vendor/）。幂等：已装同版本就跳过下载。
# 自检（CAM_SELFTEST=0 跳过）：LiveTalking 在 :$PORT 运行时，用 curl 确认 4 个文件返回 200，并打印 Content-Type。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

: "${CAM_MODEL_DIR:=$HOME/emotion-models/mediapipe}"
: "${CAM_ASSETS_TGZ:=}"
: "${CAM_SELFTEST:=1}"
DEST="$APP_DIR/web/vendor/mediapipe"
# 与 apps/emotion/face_body/models.py 的登记一致
FACE_SHA=64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
POSE_SHA=5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

integrity_of() { echo "sha512-$(openssl dgst -sha512 -binary "$1" | base64 | tr -d '\n')"; }

echo "==> [1/4] MediaPipe Tasks Vision 网页版 $CAM_TASKS_VISION_VERSION → $DEST"
mkdir -p "$DEST/wasm"
if [ -z "$CAM_ASSETS_TGZ" ] && [ -f "$DEST/vision_bundle.js" ] && [ -f "$DEST/VERSION" ] &&
   [ "$(cat "$DEST/VERSION")" = "$CAM_TASKS_VISION_VERSION" ]; then
  echo "    已是该版本，跳过下载（要重装先删 $DEST/VERSION）"
else
  tgz="$work/pkg.tgz"
  if [ -n "$CAM_ASSETS_TGZ" ]; then
    cp "$CAM_ASSETS_TGZ" "$tgz"
    echo "    离线安装：$CAM_ASSETS_TGZ"
  else
    command -v npm >/dev/null ||
      { echo "!! 没有 npm：在开发机 npm pack @mediapipe/tasks-vision@$CAM_TASKS_VISION_VERSION，再用 CAM_ASSETS_TGZ=<tgz> 离线安装"; exit 1; }
    pkg="@mediapipe/tasks-vision@$CAM_TASKS_VISION_VERSION"
    if ! (cd "$work" && env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
          npm pack "$pkg" --registry "$CAM_NPM_REGISTRY" >/dev/null 2>&1); then
      echo "    镜像 $CAM_NPM_REGISTRY 不通，改走 npm 官方源${PROXY:+（代理 $PROXY）}"
      (cd "$work" && npm pack "$pkg" --registry https://registry.npmjs.org/ \
          ${PROXY:+--proxy "$PROXY" --https-proxy "$PROXY"} >/dev/null)
    fi
    mv "$work"/mediapipe-tasks-vision-*.tgz "$tgz"
  fi
  got="$(integrity_of "$tgz")"
  if [ "$got" != "$CAM_TASKS_VISION_INTEGRITY" ]; then
    echo "!! tgz 校验失败：$got"
    echo "   应为 CAM_TASKS_VISION_INTEGRITY=$CAM_TASKS_VISION_INTEGRITY（换版本时两个变量一起改）"
    exit 1
  fi
  tar -xzf "$tgz" -C "$work"
  cp -f "$work/package/vision_bundle.js" "$work/package/vision_bundle.mjs" "$work/package/package.json" "$DEST/"
  rm -f "$DEST"/wasm/*
  cp -f "$work"/package/wasm/* "$DEST/wasm/"
  echo "$CAM_TASKS_VISION_VERSION" > "$DEST/VERSION"
  echo "    已安装（许可 Apache-2.0，见 $DEST/package.json）"
fi

echo "==> [2/4] 模型：$CAM_MODEL_DIR → $DEST（sha256 校验）"
for spec in "face_landmarker.task:$FACE_SHA" "pose_landmarker_full.task:$POSE_SHA"; do
  name="${spec%%:*}"
  want="${spec#*:}"
  if [ ! -f "$DEST/$name" ] || [ "$(sha256sum "$DEST/$name" | cut -d' ' -f1)" != "$want" ]; then
    src="$CAM_MODEL_DIR/$name"
    [ -f "$src" ] || { echo "!! 缺 $src：先在阶段三下载模型（apps/emotion/deploy/setup_spark.sh 第 2 步，或 python -m apps.emotion.face_body fetch-models --models $CAM_MODEL_DIR）"; exit 1; }
    [ "$(sha256sum "$src" | cut -d' ' -f1)" = "$want" ] || { echo "!! $src sha256 不对：重跑 fetch-models"; exit 1; }
    cp -f "$src" "$DEST/$name"
  fi
  echo "    OK   $name"
done

echo "==> [3/4] 自检（LiveTalking :$PORT 的静态路由）"
if [ "$CAM_SELFTEST" = "1" ]; then
  base="http://127.0.0.1:$PORT/vendor/mediapipe"
  fail=0
  for f in vision_bundle.js wasm/vision_wasm_internal.wasm face_landmarker.task pose_landmarker_full.task; do
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 --noproxy '*' "$base/$f" || echo 000)"
    echo "    HTTP $code  /vendor/mediapipe/$f"
    [ "$code" = "200" ] || fail=1
  done
  for f in vision_bundle.js wasm/vision_wasm_internal.wasm; do
    ctype="$(curl -sI -m 10 --noproxy '*' "$base/$f" | tr -d '\r' | awk -F': ' 'tolower($1)=="content-type"{print $2}')"
    echo "    Content-Type  $f: ${ctype:-（无）}"
  done
  echo "    （.wasm 不是 application/wasm 时，浏览器会退回非流式编译，只是首次加载慢一点，不影响使用）"
  [ "$fail" = 0 ] || { echo "!! 有文件取不到：确认 LiveTalking 在运行（03_run.sh）、静态目录是 $APP_DIR/web"; exit 1; }
else
  echo "    跳过（CAM_SELFTEST=0）"
fi

echo "==> [4/4] 完成"
echo "    再跑 13_deploy_web.sh 同步 camera-observe.js / camera-metrics.js / triage.*，14_setup_doctor_console.sh 重启医生端服务"
echo "    患者页：http://<host>:$PORT/triage.html → 开始问诊后点「摄像头观察」"
