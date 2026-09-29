#!/usr/bin/env bash
###############################################################################
#  步骤11：本地 LLM 后端（llama-server + 本地模型，OpenAI 兼容）
#
#  作用：为 LiveTalking（以及 OpenClaw 的 model provider）提供
#        http://127.0.0.1:${LLM_PORT}/v1 的端点，并保证实时语音对话的速度。
#
#  为什么这些参数是必需的（实测归因，勿随意改）：
#    --load-mode none   模型全量驻留内存，消除按需读盘的冷页延迟
#                       （prefill 270 -> 2074 tok/s @ 22GB Qwen3.6-35B-A3B）
#    --reasoning off    关闭思考链：语音场景下"想得久"等于"答不出来"
#    --batch-size 2048  提高 prefill 吞吐
#    --ctx-size 65536   给 OpenClaw agent 的 Skill/历史留足上下文
#
#  步骤：1) 准备 llama-server（用已有二进制，或从源码构建 CUDA 版）
#        2) 下载模型权重（ModelScope 直连；断点续传 + 低速重试）
#        3) 生成 start-model.sh 与 systemd user 服务
#        4) 启动并自测（健康检查 + 短句延迟 + 长上下文 prefill）
#
#  幂等：可重复执行；已存在的二进制/模型/脚本不会重复处理。
#  前置：env.sh 中的 LLM_* 变量、LOCAL_LLM_KEY_FILE（llama-server 要 --api-key-file）。
###############################################################################
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

mkdir -p "$LLM_BIN_DIR/logs"

# llama-server 用 --api-key-file 做鉴权；文件不存在时生成一个随机 key（只存本机，不入库）
if [ ! -s "$LOCAL_LLM_KEY_FILE" ]; then
  mkdir -p "$(dirname "$LOCAL_LLM_KEY_FILE")"
  (umask 077; head -c 32 /dev/urandom | base64 | tr -d '\n' > "$LOCAL_LLM_KEY_FILE")
  echo "==> 已生成本地 LLM API key: $LOCAL_LLM_KEY_FILE"
fi

# ---------- 1. llama-server ----------
echo "==> [1/4] 准备 llama-server: $LLAMA_SERVER_BIN"
if [ -x "$LLAMA_SERVER_BIN" ]; then
  echo "    使用已有二进制"
  "$LLAMA_SERVER_BIN" --version 2>&1 | head -2 | sed 's/^/    /'
else
  # 注意：本节未在本仓库的部署机上验证（原机用的是自编译二进制，通过 LLAMA_SERVER_BIN 覆盖）。
  # 若构建失败，请改用发行版/第三方提供的 llama-server，并把 LLAMA_SERVER_BIN 指向该文件。
  echo "    未找到二进制，尝试从源码构建 CUDA 版（需要 cmake、nvcc、git）"
  command -v cmake >/dev/null || { echo "!! 缺少 cmake，请先安装或提供 LLAMA_SERVER_BIN"; exit 1; }
  [ -d "$LLAMA_SRC_DIR/.git" ] || git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_SRC_DIR"
  cmake -S "$LLAMA_SRC_DIR" -B "$LLAMA_SRC_DIR/build" \
    -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES=native -DLLAMA_CURL=OFF
  cmake --build "$LLAMA_SRC_DIR/build" --target llama-server -j "$(nproc)"
  LLAMA_SERVER_BIN="$LLAMA_SRC_DIR/build/bin/llama-server"
  [ -x "$LLAMA_SERVER_BIN" ] || { echo "!! 构建未产出 llama-server"; exit 1; }
fi

# ---------- 2. 模型权重 ----------
echo "==> [2/4] 下载模型权重 -> $LLM_MODEL_DIR"
mkdir -p "$LLM_MODEL_DIR"
MODEL_URL_BASE="https://modelscope.cn/models/${LLM_MODEL_REPO}/resolve/master"

# 单文件下载：已存在则跳过；断点续传；低于 1MB/s 持续 180s 则重连
fetch_model() {
  local file="$1"
  [ -n "$file" ] || return 0
  if [ -s "$LLM_MODEL_DIR/$file" ]; then
    echo "    已存在: $file ($(stat -c%s "$LLM_MODEL_DIR/$file") bytes)"
    return 0
  fi
  echo "    开始下载: $file"
  ( cd "$LLM_MODEL_DIR" && curl -fL -C - --retry 30 --retry-delay 5 --retry-all-errors \
      --connect-timeout 20 --speed-time 180 --speed-limit 1048576 \
      -o "$file" "$MODEL_URL_BASE/$file" ) &
}

# 大文件走后台并行下载（ModelScope 直连实测 20MB/s+；hf-mirror 已慢到不可用）
fetch_model "$LLM_MMPROJ_FILE"
fetch_model "$LLM_MODEL_FILE"
wait
for f in "$LLM_MODEL_FILE" "$LLM_MMPROJ_FILE"; do
  [ -n "$f" ] && [ -s "$LLM_MODEL_DIR/$f" ] || { echo "!! 模型文件缺失: $f"; exit 1; }
done
echo "    模型就绪: $(du -sh "$LLM_MODEL_DIR" | cut -f1)"

# ---------- 3. 启动脚本与 systemd 服务 ----------
echo "==> [3/4] 生成 start-model.sh 与 systemd user 服务"
START_SH="$LLM_BIN_DIR/start-model.sh"
THREADS=$(( $(nproc) * 3 / 5 ))
[ "$THREADS" -lt 4 ] && THREADS=4

# DFlash 投机解码：默认开启（与演示机一致）。草稿模型需手动放到 LLM_DRAFT_FILE，本脚本不下载；
# 变量为空（关闭）或文件不存在时都不加 --spec-type。放好文件或改了变量后重跑本脚本即可。
USE_DRAFT=0
if [ -n "$LLM_DRAFT_FILE" ]; then
  if [ -f "$LLM_DRAFT_FILE" ]; then
    USE_DRAFT=1
    echo "    DFlash 投机解码：开启（草稿模型 $LLM_DRAFT_FILE）"
  else
    echo "    警告：找不到 DFlash 草稿模型 $LLM_DRAFT_FILE，本次跳过投机解码。" >&2
    echo "          本脚本不会下载草稿模型：需要时手动放到该路径后重跑本脚本；不想用请在 env.local.sh 写 LLM_DRAFT_FILE=" >&2
  fi
else
  echo "    DFlash 投机解码：关闭（LLM_DRAFT_FILE 为空）"
fi

{
  echo '#!/usr/bin/env bash'
  echo '# 由 11_setup_local_llm.sh 生成：修改 env.sh 后重跑该脚本即可覆盖本文件'
  echo 'set -euo pipefail'
  echo "exec \"$LLAMA_SERVER_BIN\" \\"
  echo "  --model \"$LLM_MODEL_DIR/$LLM_MODEL_FILE\" \\"
  if [ -n "$LLM_MMPROJ_FILE" ]; then
    echo "  --mmproj \"$LLM_MODEL_DIR/$LLM_MMPROJ_FILE\" \\"
  fi
  echo "  --alias \"$LLM_MODEL_ALIAS\" \\"
  echo "  --host 127.0.0.1 --port $LLM_PORT --api-key-file \"$LOCAL_LLM_KEY_FILE\" \\"
  echo "  --ctx-size $LLM_CTX --parallel 1 --n-gpu-layers all --flash-attn on \\"
  echo "  --threads $THREADS --threads-batch $(nproc) --batch-size 2048 --ubatch-size 512 \\"
  echo "  --load-mode none --cache-ram 0 \\"
  echo "  --temp 0.7 --top-p 0.8 --top-k 20 --min-p 0 --repeat-penalty 1.0 \\"
  echo "  --reasoning off \\"
  if [ "$USE_DRAFT" = 1 ]; then
    echo "  --spec-type draft-dflash -md \"$LLM_DRAFT_FILE\" \\"
  fi
  echo "  --metrics"
} > "$START_SH"
chmod +x "$START_SH"
echo "    已生成: $START_SH（旧版 llama-server 若不支持 --reasoning，可改用 --chat-template-kwargs '{\"enable_thinking\":false}'）"

SERVICE="$HOME/.config/systemd/user/${LLM_SERVICE_NAME}.service"
mkdir -p "$(dirname "$SERVICE")"
cat > "$SERVICE" <<EOF
[Unit]
Description=Local LLM backend (${LLM_MODEL_ALIAS}) for LiveTalking
After=network.target
StartLimitIntervalSec=600
StartLimitBurst=3

[Service]
Type=simple
ExecStart=${START_SH}
WorkingDirectory=${LLM_BIN_DIR}
Restart=on-failure
RestartSec=15
TimeoutStopSec=60
UMask=0077
OOMScoreAdjust=500
StandardOutput=append:${LLM_BIN_DIR}/logs/model-server.log
StandardError=append:${LLM_BIN_DIR}/logs/model-server.log

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable "${LLM_SERVICE_NAME}.service" >/dev/null
echo "    已启用服务: ${LLM_SERVICE_NAME}.service"

# ---------- 4. 启动与自测 ----------
echo "==> [4/4] 启动并自测（首次加载会读盘，耐心等待）"
systemctl --user restart "${LLM_SERVICE_NAME}.service"
for _ in $(seq 1 120); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 --noproxy '*' "http://127.0.0.1:${LLM_PORT}/health" || echo 000)
  [ "$code" = "200" ] && break
  sleep 5
done
echo "    /health -> $code ；服务状态: $(systemctl --user is-active "${LLM_SERVICE_NAME}.service")"
if [ "$code" != "200" ]; then
  echo "!! 服务未就绪，查看日志: ${LLM_BIN_DIR}/logs/model-server.log"
  tail -n 20 "${LLM_BIN_DIR}/logs/model-server.log" 2>/dev/null | sed 's/^/    /'
  exit 1
fi

KEY=""
[ -f "$LOCAL_LLM_KEY_FILE" ] && KEY="$(cat "$LOCAL_LLM_KEY_FILE")"
ENDPOINT="http://127.0.0.1:${LLM_PORT}/v1/chat/completions"

echo "==> 自测 A：短问句端到端延迟（实时对话的关键指标）"
printf '{"model":"%s","messages":[{"role":"system","content":"你是预问诊助手，回复简短口语化"},{"role":"user","content":"我这两天胃不舒服，有点胀"}],"stream":true,"max_tokens":120}' "$LLM_MODEL_ALIAS" > /tmp/llm_smoke_short.json
curl -sN -o /tmp/llm_smoke_short.out \
  -w "    total=%{time_total}s http=%{http_code}\n" -m 180 --noproxy '*' \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d @/tmp/llm_smoke_short.json "$ENDPOINT"
grep -o '"timings":{[^}]*}' /tmp/llm_smoke_short.out | tail -1 | sed 's/^/    /'
echo "    参考值：total < 2s、predicted_per_second > 40 才算达标；明显更慢请看 README「已知坑」"

echo "==> 自测 B：长上下文 prefill（OpenClaw agent 每轮会带较长上下文）"
LLM_MODEL_ALIAS="$LLM_MODEL_ALIAS" python3 - <<'PY' > /tmp/llm_smoke_long.json
import json, os
ctx = ("以下是预问诊知识库片段，仅用于压测 prompt 长度。" * 700)[:12000]
print(json.dumps({
    "model": os.environ["LLM_MODEL_ALIAS"],
    "messages": [{"role": "system", "content": ctx},
                 {"role": "user", "content": "我这两天胃不舒服，有点胀"}],
    "stream": True, "max_tokens": 80}, ensure_ascii=False))
PY
curl -sN -o /tmp/llm_smoke_long.out \
  -w "    total=%{time_total}s http=%{http_code}\n" -m 300 --noproxy '*' \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d @/tmp/llm_smoke_long.json "$ENDPOINT"
grep -o '"timings":{[^}]*}' /tmp/llm_smoke_long.out | tail -1 | sed 's/^/    /'
echo "    参考值：prompt_per_second > 1000（--load-mode none 生效）；~200 说明模型没驻留内存"

echo "==> 完成。服务名 ${LLM_SERVICE_NAME}.service，端点 127.0.0.1:${LLM_PORT}/v1，模型名 ${LLM_MODEL_ALIAS}"
echo "    下一步：bash 12_setup_openclaw.sh（把 OpenClaw 的 provider 指到这个端点）"
