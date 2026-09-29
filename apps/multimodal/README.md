# 阶段二：多模态动态预问诊

负责人：陈科顺 `@keshunchen`。

本目录是阶段二的实现：数字人（LiveTalking + wav2lip）、本地 ASR/TTS/LLM 接入、OpenClaw 预问诊 agent 工作区、患者端预问诊页与医生工作台，已部署在 DGX Spark 上运行（见文末「部署」）。跨阶段事件契约尚未通过 `[裁决]` Issue 冻结。设计约束：

- 麦克风需单独授权；
- 关键转写允许患者确认和修改；
- 语音/头像失败时一键回退文字模式；
- 紧急提示先显示文字，不等待音频；
- 原始录音默认不落盘。

## 前端页面（`web/`）

阶段二的预问诊界面，部署后由 LiveTalking 静态托管（`/triage.html`），**不依赖 jQuery**，只用 LiveTalking 自带的
`web/asr/recorder-core.js` 做录音。

| 文件 | 作用 |
| --- | --- |
| `web/triage.html` | **患者端**：页面结构：左＝数字人画面 + 麦克风控制，右＝文字对话 + 小结 |
| `web/triage.css` | 样式（医疗蓝绿配色，桌面双栏 / 窄屏单栏） |
| `web/triage.js` | 主逻辑：WebRTC、SSE 事件、状态机、对话渲染、小结 |
| `web/mic-asr.js` | 麦克风采集 + 前端 VAD 自动断句 + `/api/asr` WebSocket 客户端 |
| `web/doctor.html` | **医生端**：左＝会话列表，右＝文字版对话 / 预问诊总结 |
| `web/doctor.css` | 医生端样式（与患者端同一套配色变量） |
| `web/doctor.js` | 会话列表轮询、详情渲染、总结与复制；`?demo=1` 可离线预览 |

交互流程：

1. 点「开始问诊」→ 建 WebRTC（有 TURN 时强制 relay）→ 开麦克风 → 连 `/api/asr` → 订阅 `/sse`；
2. 数字人先播开场白（`type:"echo"`，不进 agent 会话历史，保证第一轮问题干净）；
3. 之后自动收音：静音 1.1s 或单轮超 30s 判为说完 → 送 ASR → 文本进对话区 → `POST /human {type:"chat"}`；
4. **回复文字与语音同步**：助手文字不再随 LLM 生成立刻显示（那样会比数字人开口早好几秒，
   出现"字念完了、人还在说上一句"），而是等该段语音真正开始播（`start` 事件）才逐段显示；
   同一轮的多段共用一个气泡，被打断或 TTS 没出声时兜底补上完整正文；
5. 数字人说话时**停止把音频送 ASR**，但麦克风保持采集：一旦检测到用户开口（连续 350ms）
   **自动打断**数字人并接上这一轮（会把开口前 1.2s 的音频补进去，避免丢字）；播完 0.7s 后恢复收音；
   页面没有"打断"按钮——打断完全由麦克风触发；
6. 点右下「结束问诊并生成小结」→ 发 `结束指令` 且带 `tts:{silent:true}`（只显示不朗读）→
   小结以卡片形式落在对话区，可全屏查看/复制。

关键设计：

- **文本先于语音**：LLM 文本通过 SSE `status:"llm_text"` 逐句落到对话区，不等 TTS；
- **状态机不卡死**：`llm_done`/TTS `end` 任一丢失都有看门狗兜底（chat 45s、开场白 15s）后恢复收音；
- **随时可打字**：输入框发送会作废当前轮识别结果，不会被识别两次；
- **麦克风首次无声**：Recorder 在"开始录音前无用户交互"时 AudioContext 停在 `suspended`，采集永远不出数据
  （现象是要点一下暂停再恢复才有声音）；打开麦克风与每次开始采集前都会显式 `resume()`；
- **断线自愈**：ASR 通道或 WebRTC 任一断开，服务端会连坐拆掉整个会话
  （`HumanPlayer Stopping worker thread` → `Connection state is closed`），
  所以前端重建**整个会话**而不是只补一条通道；自动重试 3 次，之后改为手动「重新连接」；
  重连会拿到新的 sessionid，**此前的问诊上下文会重置**；
- **文字与语音同步、以及正文完整性**：文字随语音段逐段显示（`start` 事件），不抢在数字人开口之前；
  一轮回答常被切成多段播报，只有服务端标出的最后一段（`_seg_last`）播完才收尾补全文。
  调 TTS 分段字数/朗读字数时这两处要一起看，否则会出现"文字重复一遍"或"只显示一半"。
- **长回复会被超时掐断**：服务端 `LLM_TIMEOUT` 默认 60s，长小结超时被截断，表现同样是"只显示一部分"，
  现设为 180s；前端 `summaryTimeoutMs` 必须小于它，否则小结卡片会先超时、内容落到气泡里。
- **媒体通道必须走 TURN 中继**：不走中继的直连在跨网环境下典型表现是"连得上、几十秒后掉线"
  （ICE 保活包到不了对端）。页面连通后会自检候选对，未走中继会给出明确提示。
  最常见原因：走 SSH 隧道只转发了 8010，没转发 3478 →
  `ssh -L 8010:127.0.0.1:8010 -L 3478:127.0.0.1:3478 ...`；
- **安全**：页面底部固定免责声明（不诊断、不替代医生、红旗症状请立即就医）。

**自动打断误触发时**（音箱外放被麦克风收进去）：`mic-asr.js` 的 `audioTrackSet` 已显式打开
`echoCancellation`（Recorder 默认是关的）；仍误触发就调大 `bargeInRatio`（3.0）或 `bargeInMs`（350ms）。

**麦克风不出声/不断句时**，先看页面左下音量条；完全不动说明浏览器没拿到音频（授权或输入设备选错，页面 6 秒后会提示）。
断句灵敏度在 `web/mic-asr.js` 顶部 `DEFAULTS` 里调：`silenceMs`（静音多久算说完，默认 1100ms）、
`minLevel`（电平下限）、`noiseRatio`（相对环境噪声的倍数）。
注意 `Recorder` 的 `buffers` 是累积数组，只能取本次新增部分重采样（否则会把同一段音频反复送 ASR）。

`?demo=1` 可打开设计预览（示例对话 + 小结），不连任何后端，便于改样式时快速看效果。

**依赖**：`llm.py` 补丁会推 `llm_text` / `llm_done` 事件（见 `deploy/livetalking/patches/llm.py`）；
未打补丁时数字人仍能正常语音作答，只是右侧不显示数字人的文字。

## 医生端工作台（`web/doctor.html`）

给医生在问诊前/后快速了解情况用，**只读、不做诊断判断**：

1. 左侧会话列表：正在问诊的会排序在前（`正在进行` / `进行中`），已生成总结的显示 `已出总结`，
   超时没有总结的显示 `中断未结`；5 秒自动刷新，可按会话编号或内容搜索；
2. 点开一个会话 → 右侧「对话记录」是这一场问诊的**文字版全文**（区分患者/助手、语音或文字输入、来源模型）；
3. 患者点了「结束问诊」、agent 输出记录后 → 「预问诊总结」页签出现**医生参考版**，
   一键可复制；患者端那段核对文本折叠在下方，便于对照患者实际看到了什么。

数据来源（全部在本机闭环，不到云上）：

- **对话转写**：`deploy/livetalking/patches/consult_recorder.py` 由 `07_patch_livetalking.sh` 装到 LiveTalking，
  `llm.py` 在每一轮问诊时把患者原话与助手回复追加写入 `$DOCTOR_RECORD_DIR/<sessionid>.jsonl`（文件 600、目录 700）。
  放在 `llm.py` 是因为它是唯一必经之处，且会话一旦被空闲回收，内存里的上下文就没了；
- **在线状态**：同机 LiveTalking 的 `/api/admin/sessions`（回环），拿不到就退化为按文件最后更新时间判断；
- **服务**：`deploy/livetalking/doctor_service.py`（FastAPI，默认 `0.0.0.0:8110`），
  提供 `/api/doctor/sessions`、`/api/doctor/sessions/<id>`、`/health`，并同源托管 `doctor.html/css/js`。

患者端页面右上角有「医生工作台」入口（指向 `/doctor.html`）；若页面由 8010 托管，
`doctor.js` 会自动把接口改指向 `:8110`，不用手工配地址。`?demo=1` 可离线预览示例数据。

## 部署（DGX Spark）

LiveTalking（wav2lip 数字人 + WebRTC，方案A：宿主机 venv）的部署脚本、网络注意事项与已知问题见
[`deploy/livetalking/README.md`](deploy/livetalking/README.md)。

当前状态（2026-09-23）：服务已在 DGX Spark 上以 TCP `8010` 运行并通过冒烟验证；
**全本地链路已打通**——ASR（SenseVoiceSmall，`/api/asr`）、LLM（OpenClaw agent `openclaw/tcm`，失败降级到同机 Qwen3.6-35B-A3B）、
TTS（ChatTTS，`127.0.0.1:8090`）三环均在本机，不调用云端 API；6 轮问诊实测稳态 0.70–0.94s、生成记录轮 2.4s。
对外只需放通 TCP `8010`（页面/信令）与 TURN `3478`（`08_setup_turn.sh` 支持仅 TCP），不需要 UDP。


