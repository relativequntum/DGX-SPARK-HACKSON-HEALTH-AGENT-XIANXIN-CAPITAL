#!/usr/bin/env bash
# LiveTalking 部署公共环境变量（方案A：宿主机 venv）
# 用法：source env.sh
# 说明：本文件不含任何密钥。代理与路径可按实际机器覆盖。

# ---- 本机覆盖（可选）：与本文件同目录的 env.local.sh，已被 .gitignore 忽略，不入库 ----
# 放本机专属值（TURN_REALM、PROXY 等）；它先于下方默认值加载，所以其中的值优先生效。
_ENV_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$_ENV_SH_DIR/env.local.sh" ]; then
  # shellcheck source=/dev/null
  source "$_ENV_SH_DIR/env.local.sh"
fi
unset _ENV_SH_DIR

# ---- 网络代理（需要代理才能访问 PyPI/GitHub/HF 时在 env.local.sh 设置；download.pytorch.org 必须直连）----
: "${PROXY:=}"
if [ -n "$PROXY" ]; then
  export http_proxy="$PROXY"
  export https_proxy="$PROXY"
  export HTTP_PROXY="$PROXY"
  export HTTPS_PROXY="$PROXY"
fi
# download.pytorch.org 走代理会返回 403，必须直连；国内镜像同样必须直连（走代理不通或极慢）
export NO_PROXY="download.pytorch.org,mirrors.aliyun.com,mirrors.cloud.tencent.com,pypi.tuna.tsinghua.edu.cn,mirrors.tuna.tsinghua.edu.cn,hf-mirror.com,www.modelscope.cn,localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"

# ---- 国内镜像（该机走代理下载境外源普遍只有几十~几百 KB/s，镜像直连可达数 MB/s~20MB/s）----
# pip：files.pythonhosted.org 经该机代理仅 ~3KB/s，必须换镜像
: "${PIP_MIRROR:=https://mirrors.aliyun.com/pypi/simple/}"
: "${PIP_TRUSTED:=mirrors.aliyun.com}"
: "${PIP_TIMEOUT:=60}"
: "${PIP_RETRIES:=10}"
# HuggingFace：hf-mirror.com 为国内镜像，huggingface_hub / 直链下载都会用到
: "${HF_ENDPOINT:=https://hf-mirror.com}"
export HF_ENDPOINT
# torch 轮子：由 00_fetch_torch.sh 预先下载到本地
: "${TORCH_WHEEL:=$HOME/torch-2.9.1+cu130-cp312-aarch64.whl}"
: "${SEGMENTS:=16}"

# ---- 路径 ----
: "${APP_DIR:=$HOME/LiveTalking}"          # 源码目录
: "${VENV:=$HOME/livetalking-venv}"        # 虚拟环境目录
: "${MODEL_DIR:=$APP_DIR/models}"
: "${AVATAR_DIR:=$APP_DIR/data/avatars}"

# ---- 全本地链路：TTS 与 LLM 都跑在 GB10 上，禁止云端 API ----
# TTS：独立 venv 里的 ChatTTS，只监听 127.0.0.1，由 LiveTalking 通过 tts/localtts.py 调用
: "${TTS_VENV:=$HOME/tts-venv}"
: "${TTS_PORT:=8090}"
: "${TTS_SERVICE_URL:=http://127.0.0.1:$TTS_PORT/tts}"
: "${TTS:=localtts}"
: "${TTS_TIMEOUT:=120}"
# LLM：默认走同机 OpenClaw Gateway 的 OpenAI 兼容 agent 端点（问诊 Skill 与会话状态在 agent 侧）；
# OpenClaw 失败时由 llm.py 自动降级到同机 llama-server。密钥只从本机文件读取，不入库。
: "${LLM_PROVIDER:=openclaw}"
: "${OPENCLAW_BASE_URL:=http://127.0.0.1:18789/v1}"
: "${OPENCLAW_MODEL:=openclaw/tcm}"
: "${OPENCLAW_KEY_FILE:=$HOME/openclaw-spark/secrets/gateway-token}"
: "${LLM_FALLBACK_PROVIDER:=local}"
: "${LOCAL_LLM_BASE_URL:=http://127.0.0.1:8080/v1}"
: "${LOCAL_LLM_MODEL:=qwen3.6-35b-a3b}"
: "${LOCAL_LLM_KEY_FILE:=$HOME/qwen-spark/secrets/model-api-key}"

# ---- 本地 LLM 后端（11_setup_local_llm.sh 使用；以下默认值需按机器确认）----
: "${LLM_BIN_DIR:=$HOME/qwen36}"                                  # 启动脚本与日志目录
: "${LLM_SERVICE_NAME:=qwen36}"                                   # systemd user 服务名
: "${LLM_PORT:=8080}"                                             # OpenAI 兼容端点端口（须与 LOCAL_LLM_BASE_URL 一致）
: "${LLAMA_SERVER_BIN:=$HOME/llama.cpp/build/bin/llama-server}"   # 已有的 llama-server 二进制
: "${LLAMA_SRC_DIR:=$HOME/llama.cpp}"                             # 无二进制时从源码构建
: "${LLM_MODEL_DIR:=$HOME/models/Qwen3.6-35B-A3B-GGUF}"
: "${LLM_MODEL_REPO:=unsloth/Qwen3.6-35B-A3B-GGUF}"               # ModelScope / HF 仓库名
: "${LLM_MODEL_FILE:=Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf}"
: "${LLM_MMPROJ_FILE:=mmproj-BF16.gguf}"                          # 视觉投影（多模态）；留空则不加载
: "${LLM_MODEL_ALIAS:=qwen3.6-35b-a3b}"                           # OpenAI 请求里的 model 名
: "${LLM_CTX:=65536}"
# DFlash 投机解码草稿模型：默认开启（与演示机一致）；文件不存在时 11 自动跳过。脚本不下载它，需手动放置。
# 关闭：在 env.local.sh 写 LLM_DRAFT_FILE= （这里用 "=" 而非 ":="，显式置空才不会被默认值覆盖）
: "${LLM_DRAFT_FILE=$HOME/models/Qwen3.6-DFlash/Qwen3.6-35B-A3B-DFlash-q8_0.gguf}"

# ---- OpenClaw agent（12_setup_openclaw.sh 使用）----
: "${OPENCLAW_CONFIG:=$HOME/.openclaw/openclaw.json}"
: "${OPENCLAW_PROVIDER:=spark-local}"                             # provider 名（写入 OpenClaw 配置）
: "${OPENCLAW_AGENT_ID:=tcm}"                                     # 数字人默认调用的 agent id
: "${OPENCLAW_WORKSPACE:=$HOME/.openclaw/workspace-tcm}"          # agent 工作区（含 Skill 与 AGENTS.md）

# ---- WebRTC over TCP：公网不放通 UDP 时，媒体全部经 TURN 的 TCP 通道中继 ----
# coturn 跑在 docker（host 网络），浏览器 iceTransportPolicy=relay，TURN 在本机用 UDP 转发给 LiveTalking
: "${TURN_ENABLE:=1}"
: "${TURN_PORT:=3478}"
: "${TURN_REALM:=}"                                                # 必填（08 用）：浏览器访问本机用的域名，写在 env.local.sh
: "${TURN_CONTAINER:=coturn}"
: "${LOCAL_TURN_PORT:=$TURN_PORT}"                                  # /api/turn 生成 URL 时用的端口
: "${LOCAL_TURN_SECRET_FILE:=$HOME/livetalking-deploy/secrets/turn-auth-secret}"
: "${LOCAL_TURN_TTL:=3600}"                                         # 临时凭据有效期（秒）
: "${LOCAL_TURN_URLS:=}"                                            # 留空=按访问域名拼 turn:<host>:<port>?transport=tcp；
                                                                    # 走 SSH 隧道时填 turn:127.0.0.1:13478?transport=tcp
# 服务端 ICE 只暴露这一个地址（默认=默认路由出口网卡的 IP）。
# 必须收窄：候选里出现 docker0(172.17.0.1)、隧道网卡、或 STUN 拿到的公网 srflx 时，
# TURN 会向这些不可达地址发 UDP 并报 "udp send: Operation not permitted"，ICE 直接 failed。
: "${ICE_HOST:=$(hostname -I | awk '{print $1}')}"

# ---- 医生端控制台（doctor_service.py：会话列表 / 对话转写 / 医生参考版总结）----
# 与患者端一样只跑本机：页面由本服务静态托管，数据来自本机落盘文件与 LiveTalking 回环接口
: "${DOCTOR_PORT:=8110}"
: "${DOCTOR_HOST:=0.0.0.0}"                                    # 医生工作站不在同机时放通该端口即可
: "${DOCTOR_VENV:=$HOME/doctor-venv}"                          # 只装 fastapi + uvicorn，与其它服务隔离
: "${DOCTOR_DIR:=$HOME/livetalking-deploy}"                    # doctor_service.py 的部署位置
: "${DOCTOR_WEB_DIR:=$HOME/livetalking-deploy/web}"            # doctor.html/css/js 所在目录
: "${DOCTOR_RECORD_DIR:=$HOME/livetalking-logs/consultations}" # 问诊转写落盘目录（与 LiveTalking 共用）
: "${DOCTOR_ACTIVE_WINDOW:=900}"                               # 超过多久没新消息就不再算"正在问诊"（秒）
: "${DOCTOR_LT_ADMIN_URL:=http://127.0.0.1:8010/api/admin/sessions}"
: "${DOCTOR_RECORD:=1}"                                        # 0 = 暂停问诊记录落盘（一旦涉及隐私演练）
# 患者页「摄像头观察」：浏览器只上传关键点数值，doctor_service 追加写到这里（与阶段三 spark.env 的 EMOTION_OBS_DIR 必须相同）
: "${DOCTOR_OBS_DIR:=$HOME/livetalking-logs/observations}"
: "${DOCTOR_OBSERVE:=1}"                                       # 0 = 不收摄像头观察数据（接口返回 404，患者页照常问诊）

# ---- 摄像头观察的网页端资源（15_setup_camera_assets.sh 使用）----
: "${CAM_TASKS_VISION_VERSION:=1.0.1}"                          # @mediapipe/tasks-vision，与阶段三 mediapipe==1.0.1 同版本
# npm 登记的 tgz 校验值；换版本时一起改：npm view @mediapipe/tasks-vision@<版本> dist.integrity
: "${CAM_TASKS_VISION_INTEGRITY:=sha512-rvRE2FmAZ6ZxKSw7wq+e+jQDpN3t1B/tD2mJz9SmAzb1msoDkd4dMoE4wAh8Z30Um0PQwLiHr9QtomhmXk3aUQ==}"
: "${CAM_NPM_REGISTRY:=https://registry.npmmirror.com}"         # 国内 npm 镜像，直连；不通时 15 改走官方源 + PROXY

# ---- 运行时 ----
: "${MODEL:=wav2lip}"                      # 数字人模型：wav2lip / musetalk / ultralight
: "${AVATAR_ID:=wav2lip_nurse}"
: "${MODELRES:=256}"                       # wav2lip256 必须为 256（默认 192 会导致维度不匹配）
: "${LLM_MAX_SPEAK_CHARS:=0}"              # 单轮最多朗读字数，0 = 不限：完整念完，由用户发声打断（/interrupt_talk）
                                           # 不再按字数截断——截断会把剩余正文一起丢掉，导致对话框显示不全
: "${LLM_TIMEOUT:=180}"                    # 单轮 LLM 请求超时（秒）：默认 60s 会把长回复（尤其是小结）掐断，
                                           # 表现是"对话框只显示了一部分"
: "${TTS_SEGMENT_CHARS:=12}"               # 送进 TTS 的单段字数上限：ChatTTS 合成耗时与字数成正比
                                           # （实测 15 字 0.88s / 38 字 2.5s），段越短数字人开口越早
: "${TRANSPORT:=webrtc}"                   # webrtc / rtcpush
: "${PORT:=8010}"
: "${LISTEN:=0.0.0.0}"
: "${MAX_SESSION:=16}"                     # 最大并发数字人会话数
: "${SESSION_TIMEOUT:=120}"                # 无心跳会话空闲回收秒数（0=不回收）

# ---- 版本（aarch64 + CUDA13 验证可用）----
: "${TORCH_VERSION:=2.9.1}"
: "${TORCH_INDEX:=https://download.pytorch.org/whl/cu130}"

export APP_DIR VENV MODEL_DIR AVATAR_DIR MODEL AVATAR_ID TRANSPORT PORT LISTEN
export MAX_SESSION SESSION_TIMEOUT
export PIP_MIRROR PIP_TRUSTED PIP_TIMEOUT PIP_RETRIES TORCH_WHEEL SEGMENTS HF_ENDPOINT
export TTS_VENV TTS_PORT TTS_SERVICE_URL TTS TTS_TIMEOUT
export LLM_PROVIDER LLM_FALLBACK_PROVIDER
export OPENCLAW_BASE_URL OPENCLAW_MODEL OPENCLAW_KEY_FILE
export LOCAL_LLM_BASE_URL LOCAL_LLM_MODEL LOCAL_LLM_KEY_FILE
export LLM_BIN_DIR LLM_SERVICE_NAME LLM_PORT LLAMA_SERVER_BIN LLAMA_SRC_DIR
export LLM_MODEL_DIR LLM_MODEL_REPO LLM_MODEL_FILE LLM_MMPROJ_FILE LLM_MODEL_ALIAS LLM_CTX LLM_DRAFT_FILE
export OPENCLAW_CONFIG OPENCLAW_PROVIDER OPENCLAW_AGENT_ID OPENCLAW_WORKSPACE
export TURN_ENABLE TURN_PORT TURN_REALM TURN_CONTAINER
export LOCAL_TURN_PORT LOCAL_TURN_SECRET_FILE LOCAL_TURN_TTL LOCAL_TURN_URLS
export ICE_HOST
export LLM_MAX_SPEAK_CHARS TTS_SEGMENT_CHARS LLM_TIMEOUT
export DOCTOR_PORT DOCTOR_HOST DOCTOR_VENV DOCTOR_DIR DOCTOR_WEB_DIR DOCTOR_RECORD_DIR
export DOCTOR_ACTIVE_WINDOW DOCTOR_LT_ADMIN_URL DOCTOR_RECORD DOCTOR_OBS_DIR DOCTOR_OBSERVE
export CAM_TASKS_VISION_VERSION CAM_TASKS_VISION_INTEGRITY CAM_NPM_REGISTRY
export AIOICE_HOST_ALLOWLIST="$ICE_HOST"
