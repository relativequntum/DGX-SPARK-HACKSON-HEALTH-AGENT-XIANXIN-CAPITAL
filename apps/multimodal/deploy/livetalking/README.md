# LiveTalking 数字人部署（方案A：宿主机 venv）

> **目标读者**：要在**另一台机器**上复现"多模态预问诊数字人"的工程师，或代替人类执行的 AI agent。
> 本目录脚本按编号顺序执行即可完成部署：**全部幂等、可单步重跑、每步带自测**。
> 已在 DGX Spark（GB10 / aarch64 / Ubuntu 24.04 / CUDA 13 / 驱动 580.82.09）验证。

## 0. 部署总览（先读这一节）

**执行顺序与依赖：**

```
00(可选预下载) → 01 → 02 → 06 → 07 → 11 → 12 → 03(启动) → 13(预问诊页面) → 14(医生端控制台)
                              └─ 08(TURN) 仅在"公网不放通 UDP"时必须
验证：04(数字人) / 05(ASR) / 09(TURN) / 10(LLM 通路，不需要浏览器)
```

| 顺序 | 脚本 | 作用 | 预计耗时 | 自测 |
| --- | --- | --- | --- | --- |
| 前置 | — | 装 `docker`(TURN 用)、`git`、`curl`、`jq`；确认 NVIDIA 驱动/CUDA 可用 | — | `nvidia-smi` |
| 前置 | — | 上游源码**固定版本**（与 Spark 一致，`07` 的补丁锚点按此版本对齐）：`git clone https://github.com/lipku/LiveTalking.git ~/LiveTalking && git -C ~/LiveTalking checkout b3e7490a20e7a6330492f8a6ea8200a5d50279d1` | 1–3min | `git -C ~/LiveTalking rev-parse HEAD` |
| 0 | `00_fetch_torch.sh` `00b_fetch_nvidia.sh` `00c_fetch_reqs.sh` | 把 torch/nvidia/依赖大包预下载到 `~/wheels`（**在慢网机器上强烈建议**，否则装包会卡几十分钟） | 10–30min | `ls ~/wheels` |
| 1 | `01_setup_venv.sh` | 建 `~/livetalking-venv`，装 torch(cu13)+项目依赖+ASR 依赖 | 10–20min | 结尾自带 torch/CUDA 校验 |
| 2 | `02_fetch_models.sh` | 下载 wav2lip 权重、ASR 模型（并热加载）、准备 avatar | 5–15min | 结尾自带权重结构校验 |
| 3 | `06_setup_local_tts.sh` | 本地 TTS：`~/tts-venv` + ChatTTS 服务（`127.0.0.1:8090`） | 10–20min | 轮询 `/health` |
| 4 | `07_patch_livetalking.sh` | 打补丁：`tts/localtts.py` 并在 `avatars/base_avatar.py` 注册 `localtts`（缺这一步默认 `--tts localtts` 无声） + `llm.py`（openclaw provider、会话复用、失败降级、TTS 文本清理）+ `consult_recorder.py`（每轮问诊落盘给医生端） | <1min | 校验 `base_avatar.py`/`llm.py` 语法与 provider |
| 5 | `11_setup_local_llm.sh` | 本地 LLM 后端：llama-server + 模型 + systemd 服务 | 20–60min（含下载 ~22GB） | 输出短句延迟与长上下文 prefill 数据 |
| 6 | `12_setup_openclaw.sh` | OpenClaw 配置：开启端点、注册 provider/agent、关 thinking、导出 token、同步 agent 工作区（[`../openclaw/workspace-tcm`](../openclaw/README.md)）、注入 agent 规则 | 2–5min | 输出 agent 一轮真实回复 |
| 7 | `08_setup_turn.sh` | WebRTC over TCP：coturn + 前端强制 relay | 2–5min | 之后跑 `09_turn_smoke_test.sh` |
| 8 | `03_run.sh` | 启动数字人（`8010`） | 30s | `04_smoke_test.sh` |
| 9 | `13_deploy_web.sh` | 部署阶段二预问诊页面（`triage.html/css/js` + `mic-asr.js`，同时带上 `doctor.html/css/js` 作为入口） | <1min | 自检录音依赖 `web/asr/recorder-core.js` |
| 10 | `14_setup_doctor_console.sh` | 医生端控制台：独立 venv 起 `doctor_service.py`（`0.0.0.0:8110`），静态托管 `doctor.*` 并提供 `/api/doctor/*` | 1–3min | 轮询 `/health`，输出访问地址 |

**AI 执行要点：**

1. 先对照第 2 节把「必须按机器确认」的参数写进 `env.local.sh`（或直接改 `env.sh`），**再**开始跑脚本。
2. 每步失败先看该步输出的最后 20 行日志与日志文件路径，不要把失败步骤跳过去做下一步。
3. 第 5、6 步的顺序不能反：`12` 依赖 `11` 起的端点。
4. 只需数字人能说话（不接 OpenClaw）：把 `env.sh` 的 `LLM_PROVIDER` 改成 `local` 即可跳过第 6 步。
5. 每一步都可重复执行；脚本内部用「文件已存在则跳过」「锚点已注入则跳过」保证幂等。

## 1. 环境要求

| 项 | 要求 |
| --- | --- |
| 系统 | Ubuntu 24.04 `aarch64`（x86_64 亦可，注意轮子架构） |
| GPU | 支持 CUDA 13 的 NVIDIA 卡；数字人 + LLM + TTS 合计需显存/统一内存 ≥ 40GB（模型 22GB + ChatTTS ~3GB + wav2lip 缓冲） |
| 权限 | 全流程**不需要 sudo**（除装 docker/驱动外） |
| 网络 | 需要能访问 PyPI 镜像、ModelScope、HuggingFace 镜像之一；公网部署还需放通 TCP 端口 |

选择「宿主机 venv」而不是 Docker 的原因：Docker GPU runtime 配置要 sudo，而本方案希望部署全程不依赖 sudo；
aarch64 上 `torch-2.9.1+cu130-cp312` 官方轮子可用；`torchvision==0.24.1` 无 cp312/aarch64 轮子，但只有 musetalk/ultralight 用到，wav2lip 路线不需要。

## 2. 必须先按机器确认的参数（`env.sh`）

脚本全部 `source env.sh` 取参数，**改这里即可，不用改脚本**。

**本机专属值放 `env.local.sh`**（与 `env.sh` 同目录，已被 `.gitignore` 忽略、不入库）：`env.sh` 开头若发现它就先 `source`，
其中的值优先于默认值。至少写 `TURN_REALM`（跑 `08` 必填）；需要代理时写 `PROXY`；其它按机器不同的路径、端口也放这里。
写法与 `env.sh` 一致即可，例如 `: "${TURN_REALM:=turn.example.com}"`（这样命令行临时传入的同名变量仍可覆盖它）。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROXY` | 空 | **按机器设**（`env.local.sh`）。访问 PyPI/GitHub/HF 需走代理时填 `http://<代理地址>:<端口>`；留空则不设置代理变量 |
| `PIP_MIRROR` / `HF_ENDPOINT` | 阿里云 / `hf-mirror.com` | 国内加速；境外机器可换回官方源 |
| `APP_DIR` / `VENV` | `~/LiveTalking` / `~/livetalking-venv` | 源码与虚拟环境路径 |
| `TTS_PORT` | `8090` | 本地 ChatTTS 端口（仅监听回环） |
| `TTS_SPK_FILE` / `TTS_SPK_SEED` | `~/livetalking-deploy/secrets/chattts-spk.txt` / `2024` | 固定音色：首次按种子采样后落盘复用；默认种子为**女声**（与默认数字人形象配对），换音色改种子或换文件 |
| `LLM_PORT` | `8080` | 本地 LLM 端口（须与 `LOCAL_LLM_BASE_URL` 一致） |
| `LLAMA_SERVER_BIN` | `~/llama.cpp/build/bin/llama-server` | **按机器改**：指向已有的 llama-server；找不到时 `11` 会尝试源码编译 |
| `LLM_MODEL_REPO` / `LLM_MODEL_FILE` | `unsloth/Qwen3.6-35B-A3B-GGUF` / `...UD-Q4_K_XL.gguf` | 换更小/更大模型时改这里（见第 12 节对速度的影响） |
| `LLM_MODEL_ALIAS` | `qwen3.6-35b-a3b` | OpenAI 请求里的 `model` 名 |
| `LLM_SERVICE_NAME` | `qwen36` | systemd user 服务名 |
| `LLM_DRAFT_FILE` | `~/models/Qwen3.6-DFlash/Qwen3.6-35B-A3B-DFlash-q8_0.gguf` | DFlash 投机解码草稿模型（需手动放置）；文件不存在时 `11` 跳过；置空即关闭（见第 4 节） |
| `LLM_PROVIDER` | `openclaw` | `openclaw`=走 agent；`local`=直连 LLM（跳过第 6 步） |
| `OPENCLAW_AGENT_ID` | `tcm` | 数字人调用的 agent id |
| `OPENCLAW_WORKSPACE` | `~/.openclaw/workspace-tcm` | agent 工作区（含 Skill 包与 `AGENTS.md`）；不存在时 `12` 从仓库副本 `../openclaw/workspace-tcm` 新建 |
| `TURN_REALM` | 空 | **必填**（`env.local.sh`）：`<你的域名>`；为空时 `08` 直接报错退出 |
| `MAX_SESSION` / `SESSION_TIMEOUT` | `16` / `120` | 并发会话上限 / 空闲回收秒数 |
| `DOCTOR_PORT` / `DOCTOR_HOST` | `8110` / `0.0.0.0` | 医生端控制台监听地址（医生不在同机才放通该端口） |
| `DOCTOR_RECORD_DIR` | `~/livetalking-logs/consultations` | 问诊转写落盘目录，LiveTalking 与医生端服务**必须用同一个** |
| `DOCTOR_ACTIVE_WINDOW` | `900` | 超过这个秒数没有新消息就不再算"正在问诊" |
| `DOCTOR_RECORD` | `1` | 置 `0` 暂停问诊记录落盘（隐私演练/排障用） |

## 3. 全本地链路（部署完成后的形态）

```
浏览器麦克风 → WebRTC(TURN/TCP) → 本地 ASR(SenseVoice)
   → OpenClaw agent（预问诊 Skill + 会话状态）
   → 本地 TTS(ChatTTS:8090) → wav2lip 口型 → 浏览器
```

| 环节 | 实现 | 位置 |
| --- | --- | --- |
| ASR | funasr + `iic/SenseVoiceSmall` + `fsmn-vad`（GPU） | LiveTalking 进程内，`/api/asr` |
| LLM | OpenClaw Gateway 的 OpenAI 兼容 agent 端点；失败自动降级到同机 `llama-server` | `127.0.0.1:18789/v1`；降级 `127.0.0.1:8080/v1` |
| TTS | ChatTTS（独立 venv `~/tts-venv`） | `127.0.0.1:8090`，仅监听回环 |
| 口型 | wav2lip | LiveTalking 进程内 |

**不调用任何云端 API**：断网时链路仍可完整工作（模型权重全部落地）。

## 4. OpenClaw 对话接入（第 12 步做了什么）

让 agent 承载预问诊 Skill（问题库、危险症状规则、记录模板）与会话状态，数字人只负责听说与形象。

- 端点：`POST http://127.0.0.1:18789/v1/chat/completions`，`model` 传 `openclaw/<agentId>`；
  该端点在 OpenClaw 里**默认关闭**，`12_setup_openclaw.sh` 会写入
  `gateway.http.endpoints.chatCompletions.enabled = true` 并重启 gateway；
- 会话：`llm.py` 把 LiveTalking 的 `sessionid` 作为 OpenAI `user` 字段传入，**一个数字人会话对应一个 agent 会话**；
  不带该字段时 Gateway 每次请求都新建会话，问诊状态无法跨轮累积；
- 凭据：Gateway token 由 `12` 导出到 `OPENCLAW_KEY_FILE`（600），`03_run.sh` 读入 `OPENCLAW_API_KEY`，**不入库**；
- 降级链：`openclaw` 抛错 → `local`（直连 `127.0.0.1:8080/v1`）→ 固定话术 `LLM_FALLBACK_LINE`，不会静默无声；
- `llm.py` 会把 Markdown/emoji（`**`、`⚠️`、表格线等）从送 TTS 的文本里清掉，避免数字人念符号。

**agent 工作区**（`AGENTS.md`、`SOUL.md`、`IDENTITY.md`、`tcm-preconsultation` Skill）在仓库
[`apps/multimodal/deploy/openclaw/workspace-tcm/`](../openclaw/README.md) 留有 Spark 快照（2026-09-29），
`12` 第 6 步把它同步到 `OPENCLAW_WORKSPACE`：只新增/覆盖副本里有的文件，覆盖前备份为 `<文件>.bak-<时间戳>`，
`records/`、`memory/` 等其他文件不动；副本位置可用 `OPENCLAW_WS_SRC` 指定。

**agent 侧 `AGENTS.md` 的三条必备规则**（快照已包含；`12` 第 7 步检查到已存在即跳过，缺失时自动注入，锚点对不上时请手工对齐）：

| 规则 | 为什么必须 |
| --- | --- |
| **语音优先**：一轮一个核心问题、选项最多读 3 项、1-2 句话说清、不用 Markdown 表格 | 回复长度直接决定延迟。实测加这条后回复从 260-310 tokens 降到 30-60，稳态延迟减半 |
| **会话隔离**：目录名用 `session_status` 的会话标识，且只读写该目录 | 否则新会话会沿用 `records/` 里上一次的病历（实测新会话开口就说出了上一次的"上腹部胀痛、饭后加重"） |
| **降低写盘频率**：每 3 轮、或停止/生成记录、或新增事实≥3 条时才写 `draft.json` | 每轮写整份草稿要生成 500-960 tokens，占 10-16s |

**实测延迟（GB10，6 轮问诊）：**

| 轮次 | 耗时 |
| --- | --- |
| 第 1 轮（新会话：读 Skill + 建记录目录） | 4.1s |
| 第 2-5 轮（稳态） | 0.70 / 0.94 / 0.85 / 0.85s |
| 生成记录轮（医生版+患者版+草稿） | 2.4s |
| 端到端合计 | 9.9s |

达标缺一不可的五个前提：①后端模型 ~22GB 且 `--load-mode none` 全量驻留内存（prefill 2074 tok/s）；
②服务端 `--reasoning off` 且 OpenClaw `thinkingDefault="off"`；③agent 降低写盘频率；
④LiveTalking 侧用 `sessionid` 复用 agent 会话（KV cache 前缀命中）；⑤agent 按语音规则作答。
稳态每轮只有 1 次模型调用：增量 prefill ~150 tokens（0.35s）+ 生成 30-60 tokens（60-105 tok/s）。

**已知限制：** Gateway 的 `/v1/chat/completions` 返回内容是**整段一次性推送**（非逐 token SSE），
`llm.py` 收到后按标点切句送 TTS，因此首句出声时间 ≈ 整段生成完成时间。

**投机解码（DFlash）：默认开启，与演示机一致。** `11` 在草稿模型文件存在时给 `llama-server` 加
`--spec-type draft-dflash -md <草稿模型>`。草稿模型为 421 MB 的 q8_0 GGUF，默认路径
`~/models/Qwen3.6-DFlash/Qwen3.6-35B-A3B-DFlash-q8_0.gguf`（`LLM_DRAFT_FILE`），来源：[待补：DFlash 草稿模型来源]；
**脚本不下载它，需手动放置**。文件不存在时 `11` 打印警告并跳过投机解码，其余照常。
关闭：在 `env.local.sh` 写 `LLM_DRAFT_FILE=`，再重跑 `11`。
历史记录：早先一次实测接受率仅 24%、收益有限，当时仓库默认不启用；现按演示机的实际配置改为默认开启。

## 5. WebRTC over TCP（公网只放通 TCP 时必读）

租机在 NAT 后、公网不放通 UDP 时，WebRTC 媒体流（SRTP/UDP）连不通：页面能开但看不到画面。
`08_setup_turn.sh` 用 TURN 的 **TCP** 通道绕过：

```
浏览器 ──TCP──> TURN(coturn, 3478) ──UDP(本机)──> LiveTalking(aiortc)
```

- coturn 跑在 docker（`--network host`），**不需要 sudo**；配置写在 `~/livetalking-deploy/turnserver.conf`（600，含密钥），
  容器内必须 `--user root` 才读得到，否则会静默退回"无配置"启动（`Cannot find config file`）；
- 凭据用 HMAC 临时凭据（`use-auth-secret`），由 LiveTalking 新增的 `/api/turn` 签发，密钥只在 `secrets/turn-auth-secret`，不入库、不进命令行；
- 前端补丁（`web/turn.js` + `iceTransportPolicy='relay'`）：官方页面把 `iceServers` 包在"使用 STUN"复选框里，
  补丁改成**有 TURN 就无条件走 TURN 并强制 relay**；
- 只需放通 **TCP 3478（TURN）+ TCP 8010（页面/信令）**，不需要任何 UDP；
- 实测（本地经 SSH 隧道的 Chrome）：`iceConnectionState=connected`、浏览器侧候选 `localType=relay`、
  视频 512×512、10s 内 `bytesReceived` 从 816KB 涨到 1.46MB；`turnutils_uclient -T` 10/10 报文、0 丢包；
- 本机验证隧道：`ssh -L 8010:127.0.0.1:8010 -L 3478:127.0.0.1:3478 <host>`，
  浏览器打开 `http://127.0.0.1:8010/index.html`（TURN URL 自动拼成 `turn:127.0.0.1:3478?transport=tcp`）；
  端口不同时用 `LOCAL_TURN_URLS=turn:127.0.0.1:<本地端口>?transport=tcp` 覆盖。

**服务端 ICE 候选必须收窄（ICE failed 的头号原因）**：浏览器侧强制 relay 还不够，
服务端 `aiortc` 默认会把**所有网卡**都作为候选，还会向 STUN 查询公网 srflx 候选。
只要候选里出现不可达地址（`docker0` 172.17.0.1、隧道网卡、或出网 UDP 被禁时的公网 srflx），
TURN 就会向它们发 UDP 并失败，日志表现为：

```
coturn:  ERROR udp send: Operation not permitted
app.log: Connection state is connecting → failed
```

`07_patch_livetalking.sh` 第 5 步做两件事：禁用服务端 STUN（`rtc_manager.py`），
并让 `aioice` 只把 `AIOICE_HOST_ALLOWLIST`（`env.sh` 的 `ICE_HOST`，默认主网卡 IP）放进候选。
修复后 coturn 日志里应只剩一个 peer（即 `ICE_HOST`），页面 `pc.connectionState=connected`。

## 6. 端口与访问

| 端口 | 用途 | 放通建议 |
| --- | --- | --- |
| `8010` TCP | 页面与信令 | 需放通 |
| `3478` TCP | TURN（仅 TCP 场景） | 需放通 |
| `8110` TCP | 医生端控制台（页面 + 只读接口） | 医生不在同机时才放通 |
| `8080` / `8090` / `18789` | 本地 LLM / TTS / OpenClaw | **只监听 127.0.0.1，不要放通** |
| UDP 1-65535 | 原生 WebRTC（有 TURN 时不需要） | 可全部不放通 |

## 7. 会话上限与空闲回收

- `MAX_SESSION`（默认 16）→ `--max_session`：并发数字人会话上限，每个会话独立加载形象 + 渲染线程；
- `SESSION_TIMEOUT`（默认 120 秒）→ `--session_timeout`：无心跳会话会被自动回收，`0` = 关闭；回收器每 30s 扫描一次；
- 心跳接口：`GET/POST /api/ping?sessionid=...`；`/human`、`/humanaudio`、`/interrupt_talk`、`/record` 等带 sessionid 的请求也会刷新活跃时间；
- 前端 `web/client.js`（`dashboard.html`、`webrtcapi.html`、`webrtcapi-asr.html`）每 30s 心跳一次；
  其它入口（如 `index-whep.html`）需自行接入 `/api/ping`，否则会被按空闲回收；
- 观测：`GET /api/admin/sessions` 返回每个会话的 `idle` 秒数；回收日志关键字 `Reaping idle session`；
- 这些改动改的是 `~/LiveTalking` 上游源码（不在仓库内），补丁保存在 `patches/idle-session-reaper.patch`。

## 8. 本地 ASR（SenseVoiceSmall）

`01_setup_venv.sh` 安装 `funasr` + `kaldi-native-fbank` 后，LiveTalking 自动注册 `/api/asr`
（日志出现 `[ASR] Local SenseVoice ASR endpoint enabled at /api/asr`，否则为 `funasr not installed ... disabled`）。

- 模型：`iic/SenseVoiceSmall` + `vad_model="fsmn-vad"`（`server/asr_server.py` 内硬编码），由 `02_fetch_models.sh` 预取；
- 实测（GB10）：5.4s 中文语音经 `/api/asr` 转写文本完全一致，稳态 0.10–0.16s；
- `05_asr_smoke_test.sh` 自查端点注册状态并用合成语音走完整链路（可给 `ASR_TEST_WAV=/path/16k.wav` 跳过合成）；
- 音频只在内存中用于推理，不落盘。

## 9. 网络注意（慢网机器上的坑）

- 该租机访问 PyPI / GitHub / HuggingFace 必须走代理；`download.pytorch.org` 走代理会返回 **403**，必须直连（`env.sh` 用 `NO_PROXY` 处理）；
- 装 Python 包必须绕开代理直连国内镜像：经代理只有 ~300KB/s，直连 20MB/s+；
- `files.pythonhosted.org` 经该机代理仅 ~3KB/s，会直接超时；
- **模型下载源实测**：`hf-mirror.com` 61KB/s、`huggingface.co` 经代理 2.1MB/s（都不可用），**ModelScope 直连 23MB/s**；
  用 `curl -L` 跟重定向，否则只拿到 366 字节的跳转响应；
- 大轮子（torch 512MB、nvidia-* 共 2.5GB）优先用 `00*_fetch_*.sh` 预先拉取，再由 pip 离线装。

## 10. 已知坑与限制

- `wav2lip256` 必须带 `--modelres 256`（默认 192 会维度不匹配），且 `modelres` 与 avatar 的 `img_size` 必须一致；
- `funasr` 特征提取必须有 fbank 后端：aarch64 上无匹配 `torch 2.9.1+cu130` 的 `torchaudio` 轮子，改用 `kaldi-native-fbank`；
- ChatTTS 需约 3GB 显存，且**必须有显存**：`TTS_BACKEND=auto` 在空闲显存 <3GB 时回退 `piper`（CPU），
  而 piper 中文走 espeak 音素化、本机数据不匹配会输出空音频；ChatTTS 在 CPU 上约 20s/句，不能用于实时对话；
- 同机同时跑大模型时注意显存/统一内存：模型 + TTS + 数字人合计超限会把 TTS 挤到 OOM；
- **音色必须固化**：ChatTTS 的 `infer` 不传 `spk_emb` 时每次请求随机采样音色（`Speaker._sample_random` 就是 `torch.randn`），
  而 `llm.py` 会把一段回答按标点切成多句分别合成 → 一句话里男女声交替。
  `tts_service.py` 启动时按 `TTS_SPK_SEED` 采样一次并写入 `TTS_SPK_FILE`，之后所有请求复用（重启也一致）。
  实测（2026-09-23，4 句样本）谱包络两两相似度：随机 0.941（最差 0.890）→ 固定 0.978（最差 0.961）。
  默认种子 `2024` 实测为稳定女声（6 句 F0 196-232Hz，均值约 220Hz）；种子 `8888`/`31415` 只在个别句子上偏高，换句就掉回 150Hz，不可用；
- `torch 2.9.1` 对 GB10（sm_121）会打印 `cuda capability 12.1 ... (8.0)-(12.0)` 警告，实测推理正常；
- 旧版 llama-server 若无 `--reasoning` 参数，改用 `--chat-template-kwargs '{"enable_thinking":false}'`；
- `11_setup_local_llm.sh` 的「源码编译 llama.cpp」分支**未在本仓库验证过**（原机用的是自编译二进制），
  构建失败时请改用发行版二进制并设置 `LLAMA_SERVER_BIN`；
- 演示前建议清空 agent 的 `records/` 目录（`12` 已保证新会话不读旧记录，但演示需要干净起点）；
- **页面能打开但数字人连不上时**，按此顺序排查：①`docker logs coturn` 有无 `udp send: Operation not permitted`（有=候选未收窄，重跑 `07`（第 5 步）并重启）；
  ②`/api/turn` 返回的 TURN 地址浏览器是否可达（走 SSH 隧道时 8010 与 3478 都要映射）；
  ③本机开了系统代理/VPN 客户端时，Chrome 可能把 TURN over TCP 也走代理，必要时给浏览器加 `--no-proxy-server`；
  ④用官方 `index.html` 做对照——它同样连不上就说明不是新页面的问题。

## 11. 预问诊页面（`13_deploy_web.sh`）

把仓库里 `apps/multimodal/web/` 的四个文件拷到 `$APP_DIR/web/`（静态目录，**不需要重启服务**）：

```bash
# 在仓库内（web 目录与 deploy/livetalking 同级）
bash 13_deploy_web.sh

# 在租机上（只有 ~/livetalking-deploy 一份平铺拷贝时）
WEB_SRC=$HOME/livetalking-deploy/web bash 13_deploy_web.sh
```

- 访问：`http://<host>:8010/triage.html`（设计预览加 `?demo=1`，不连后端）；
- 页面自带 **强制 relay** 逻辑，不依赖 `index.html` 那个"使用 STUN"复选框；走 SSH 隧道时同样可用；
- 页面每 30s 调 `/api/ping` 心跳，不会被空闲回收；
- `07_patch_livetalking.sh` 装的 `llm.py` 会向 SSE 推 `llm_text`（逐句）与 `llm_done`，
  前端据此把数字人的回答实时显示在右侧；改动 `llm.py` 后**必须重启 `03_run.sh`** 才生效；
- 页面与链路的设计说明见 [`apps/multimodal/README.md`](../../README.md)。

**冒烟方法（2026-09-23 实测通过）**：本地 `ssh -L 8010:127.0.0.1:8010 -L 3478:127.0.0.1:3478 <host>`，
无头 Chrome（加 `--use-fake-device-for-media-stream`）打开 `triage.html` 自动点击开始并打字提问，
页面状态依次 `connecting → echo 播报 → listening → thinking(chat) → speaking → listening`，
服务端 `~/livetalking-logs/app.log` 出现 `notify:{'status': 'llm_text', ...}` 与 `llm_done`，
右侧气泡文本随流式事件增长。真实麦克风需在有图形界面的浏览器里人工确认。

## 12. 医生端控制台（`14_setup_doctor_console.sh`）

给医生看的一侧：**正在问诊的会话列表 → 文字版对话记录 → 问诊结束后的医生参考版总结**。

**必须第 4 步先打了补丁、并重启过 `03_run.sh`**，`llm.py` 才会把每轮问诊写进 `DOCTOR_RECORD_DIR`；
否则接口能用但永远是空的列表。

```bash
bash 14_setup_doctor_console.sh
# 服务：0.0.0.0:8110（页面同源托管，无需跨域配置）
# 医生工作台：http://<host>:8110/
# 示例数据（不连后端）：http://<host>:8110/?demo=1
# 停止：kill $(cat ~/livetalking-logs/doctor.pid)；日志：~/livetalking-logs/doctor.log
```

链路与数据：

```
患者端 triage.html ──说话──▶ LiveTalking ──▶ OpenClaw agent
                              │
                              └─ consult_recorder.py（07 步补丁）
                                   每轮写 $DOCTOR_RECORD_DIR/<sessionid>.jsonl
                                    （患者原话 / 助手回复 / 小结的医生版+患者版）
                                          │
                                          ▼
             医生端 doctor_service.py（只读）+ /api/admin/sessions（在线状态）
                                          │
                                          ▼
                                  doctor.html（5s 轮询）
```

要点：

- **在线与否以 `/api/admin/sessions` 为准**：这条信息只在 LiveTalking 侧有，
  用文件时间推不出来（会话被回收的那一刻没有任何落盘动作）；
  接口拉不到时退化为按文件最后更新时间判断，超过 `DOCTOR_ACTIVE_WINDOW`（默认 15 分钟）记为"中断未结"；
- **总结完全来自本机落盘文件**：含「医生参考版」标题的那一轮回复会被拆成医生版与患者版分别存，
  页面上默认只展开医生版，患者端核对版折叠在下方供对照；
- 记录文件权限 `600`、目录 `700`，`DOCTOR_RECORD=0` 可整体停写；
- 页面上不做任何诊断判断，顶部/底部保留免责声明，内容须医生当面核实；
- 原始录音依然不落盘，这里只有文字（与第 13 节的隐私约束一致）。

## 13. 阶段二约束（部署侧）

- 服务默认把原始音频仅用于推理、不落盘；若开启录制功能需单独评估隐私影响；
- 默认 TTS 为 `localtts`（本地 ChatTTS，失败只静音、**不回落云端**）；如需云端 `edgetts` 须显式指定并接受外网依赖；
- 权重、密钥、患者音视频不进仓库；本目录脚本只含下载逻辑，不含任何凭据；
- 记不得任何"患者身份"：`sessionid` 只是会话标识，不要把它与真实身份绑定后再落盘。
