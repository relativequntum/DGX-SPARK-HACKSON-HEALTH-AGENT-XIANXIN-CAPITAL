# 第三方声明

本仓库自身代码以 Apache License 2.0 发布（见 [`LICENSE`](LICENSE)）。本文列出仓库中改编自第三方的文件，以及部署时用到、但**不随本仓库分发**的主要上游项目。

许可名称均于 2026-09-29 从上游仓库或模型页只读核对；核对不到的写「以上游仓库为准」。使用或再分发时，请以上游当前的许可文本为准。

## 一、仓库中改编自第三方的文件

| 本仓库文件 | 上游来源 | 上游许可 | 说明 |
| --- | --- | --- | --- |
| `apps/multimodal/deploy/livetalking/patches/llm.py` | [lipku/LiveTalking](https://github.com/lipku/LiveTalking) 的 `llm.py`（提交 `b3e7490a20e7a6330492f8a6ea8200a5d50279d1`） | Apache-2.0 | 本项目修改过，文件头注明了来源、许可和改动 |
| `apps/multimodal/deploy/livetalking/patches/idle-session-reaper.patch` | 针对同一上游提交的 `app.py` 等文件的差异补丁 | Apache-2.0 | 补丁里含少量上游上下文行 |
| `apps/emotion/judge/backends/jev_cloud.py` | [rezoch340/jev-chat-JARVIS-windows](https://github.com/rezoch340/jev-chat-JARVIS-windows) 的 `core/jev_client.py` | MIT | 本项目删改过；文件头保留了上游版权声明和 MIT 许可全文 |

`jev_cloud.py` 的上游版权声明：

> Copyright (c) 2026 rezoch340 and the jev-chat contributors
> Portions Copyright (c) 2026 Finderchangchang and the jev-chat contributors (Jev 聊天助手, https://github.com/jev-chat/jev-chat-jarvis)

## 二、随仓库保存、许可待确认的内容

- `apps/multimodal/deploy/openclaw/workspace-tcm/`：Spark 上 OpenClaw agent 工作区的快照。其中的中医预问诊 Skill `tcm-preconsultation` 由外部合作者提供，按原样保存；作者署名与许可：[待确认：Skill 作者署名与许可]。

## 三、部署时使用、不随仓库分发的上游项目

部署脚本在目标机器上下载或安装以下项目；本仓库不包含它们的源码或模型权重。

| 项目 | 在本项目中的用途 | 许可 |
| --- | --- | --- |
| [LiveTalking](https://github.com/lipku/LiveTalking) | 实时数字人与 WebRTC 框架（部署时 clone 固定提交并打补丁） | Apache-2.0 |
| [Wav2Lip](https://github.com/Rudrabha/Wav2Lip) | 口型驱动的模型结构与权重（权重由 `02_fetch_models.sh` 从 Hugging Face 下载） | 上游仓库没有 LICENSE 文件，README 声明仅限个人、研究、非商业用途；以上游仓库为准 |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | `llama-server` 本地推理 | MIT |
| [Qwen3.6-35B-A3B GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF)（Unsloth 量化，基于 [Qwen/Qwen3.6-35B-A3B](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)） | 本地大模型权重 | Apache-2.0（Hugging Face 模型页标注） |
| DFlash 草稿模型（`Qwen3.6-35B-A3B-DFlash-q8_0.gguf`，手动放置） | `llama-server` 投机解码的草稿模型（默认开启，文件不存在时跳过） | 来源与许可：[待补：DFlash 草稿模型来源]；以上游为准 |
| [OpenClaw](https://github.com/openclaw/openclaw) | agent 运行时与 Gateway | MIT |
| [FunASR](https://github.com/modelscope/FunASR) | 语音识别推理框架 | 代码 MIT；预训练模型另有 `MODEL_LICENSE`，以上游仓库为准 |
| [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)（`iic/SenseVoiceSmall`，经 ModelScope 下载） | 语音识别模型 | 代码仓库 MIT；模型权重以上游为准 |
| [ChatTTS](https://github.com/2noise/ChatTTS) | 本地语音合成 | 代码 AGPL-3.0（上游写作 AGPLv3+）；模型 CC BY-NC 4.0（上游 README） |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | 面部与姿态关键点（阶段三 `face_body`） | Apache-2.0 |
| [coturn](https://github.com/coturn/coturn) | TURN 中继（docker 镜像） | BSD 三条款式许可（上游 LICENSE 原文） |
