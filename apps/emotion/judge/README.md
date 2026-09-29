# judge · 预问诊对话重点判断（阶段三）

会话结束后对整段预问诊对话跑一次，把**医生开诊前值得先看的患者回答**找出来、分类、按重要度排序，
输出 JSON + 一页静态 HTML。不写摘要、不下诊断、不替代确定性红旗规则。设计依据见 [设计决策.md](设计决策.md)。

判断结构借鉴 [Jev](https://github.com/rezoch340/jev-chat-JARVIS-windows)（TypeSafe 决策模型）的用法：
固定题目 + 类型化答案（布尔概率 / 单选带置信度 / 0–9 评分）+ 任意 state，判断先于生成。
题目是我们自己的（[questions_emotion.py](questions_emotion.py)、[questions_medical.py](questions_medical.py)），
本地大模型答题；Jev 云端只是显式开关。

## 怎么跑

```bash
# 仓库根目录。默认本机 Ollama + qwen3-vl:8b（Ollama 0.34 实测）
python -m apps.emotion.judge run apps/emotion/judge/samples/s01_胃胀失眠.json
# → outputs/judge/s01_胃胀失眠.judge.json + .judge.html（outputs/ 已被 .gitignore 挡住）

# Spark 上走阶段二的 llama-server（OpenAI 兼容 /v1）。key 从 LOCAL_LLM_KEY_FILE 指向的文件读，
# 地址、模型、key 文件都在 apps/emotion/deploy/spark.env 里（与阶段二 env.sh 同名变量）
source apps/emotion/deploy/spark.env
python -m apps.emotion.judge run s.json --backend openai

# 直接判断数字人 consult_recorder 落盘的问诊记录（Spark 上 ~/livetalking-logs/consultations/<会话>.jsonl）
python -m apps.emotion.judge run ~/livetalking-logs/consultations/<会话>.jsonl --backend openai

# 跑全部虚构样本并对照金标准打分
python -m apps.emotion.judge.eval.run_eval

# 测试（不联网、不需要模型）
python -m pytest apps/emotion/judge/tests -q
```

依赖：Python ≥ 3.10，标准库即可跑 Ollama 路径；`--backend openai` 需要 `pip install openai`。

会话文件格式：

```json
{"session_id": "s01", "turns": [
  {"role": "agent",   "text": "最近睡眠怎么样？", "question_id": "sleep"},
  {"role": "patient", "text": "还行吧……其实经常半夜醒。"}
]}
```

`question_id` 是阶段一问题树的题号，判断结果会挂到「当时在答哪一题」上；阶段一定了会话契约后再对齐字段。

也接受数字人 consult_recorder 的 `.jsonl`（每行 `{"t", "kind": "user"|"assistant"|"summary", "text"}`）：
user 当患者、assistant 当问诊 Agent，summary 与空行跳过（见 `sources.py`）。这类记录可能是真人说的话，
只在 Spark 本机用本地模型判断，结果不拷出、不入库、不开 `--cloud`。

## 问诊结束后自动判断（Spark）

Spark 上的 systemd 用户服务 `emotion-judge-watch` 常驻运行 `python -m apps.emotion.judge.watch`，
由 `apps/emotion/deploy/setup_spark.sh` 安装：

- 盯着数字人的问诊记录目录；记录里出现总结，或 3 分钟没有新内容，就判断这次问诊；
- 每发一次请求前，先等 llama-server 空闲、数字人没有在线会话，最多等 10 分钟，不和实时问诊抢唯一的并发槽；
- 结果写到 `outputs/judge/consult/<会话>.judge.json`，阶段二医生控制台的「重点」页签读它。
  每条命中带问诊记录里的时间 `t`，控制台靠它跳回对话原句；
- 判断期间记录又变了，下一轮重判；全部请求失败时不写结果，10 分钟后再试；
  部分请求失败时先写出判到的部分（`errors` 字段记出错次数），10 分钟后整段重判，判全了才不再判；
  服务重启后，磁盘上 `errors > 0` 或写坏的结果也会重判；
- 单条记录出错（比如写了半行）只让这一条退避重试，其余会话照常判断，服务不退出；
- 只用本地模型，没有云端选项；日志只写会话编号前 8 位、命中数和耗时。

## 输出

`*.judge.json`（`schema_version: judge-0.1`）：

- `turns[]`：每轮原文；患者轮带 `judgments.{emotion,medical}`，含每题归一化答案（`value / confidence / unknown`）、
  中文 `labels`、`importance`、`risk`、`source`（`local:<模型>` 或 `jev-cloud:<模型>`）、`evidence`（模型引用的原话）。
- `hits[]`：达到阈值或标了风险的 (轮次, 题组)，已排序——**风险线索永远在最前**，其余按重要度。
- `errors`：后端出错次数（单轮出错不中断整段）。

`*.judge.html`：左侧对话全文、命中句按组着色；右侧排序清单，每条写类别、置信度、来源、依据，点击跳原句；
顶部固定「待医务人员确认」。不引用任何外部资源，断网可开。

## 两组题

| 组 | 题 | 问什么 |
|---|---|---|
| 情绪 / 沟通 | answer_adequacy · literal_answer · tension_level · inconsistency · wants_from_agent · worth_flagging | 回答方式：充分度、有无潜台词、措辞紧张度 0–9、前后矛盾、向医生要什么、值不值得医生留意 |
| 医疗信息 | contains_key_info · info_category · risk_clue · urgency · specificity · needs_followup | 有没有医生该亲眼看的信息、哪类、有无风险措辞、多急 0–9、够不够具体、要不要追问 |

口径：**不出情绪标签**（决策记录第 11 条）；百分比是模型自报置信度，不是情绪评分；单选题都带 `unknown`。
题目待博士审阅，改了直接替换文件（改 key 要同步 `CHOICE_LABELS`）。

## 安全与隐私边界

- **风险线索只抬不压**：`risk_clue` 有疑问就答 true，命中永远置顶；代码里不做「未命中即安全」的推论。
  确定性红旗规则（`docs/safety-and-privacy.md`）另有其层，本模块不替代、不影响它。
- **默认零出网**：Ollama / llama-server 都在本机；`--cloud` 且环境变量 `JEV_API_KEY` 存在才调 Jev，
  只发最近 N 轮文字（`state.chat`），不发 `channels`、不带任何身份信息；云端失败自动退本地；结果标来源。
- **样本全部虚构**：`samples/` 里的人物、症状、用药均为编造；不要把真实录音或转写稿放进仓库或发给云端。
- 输出固定标注「待医务人员确认」；错误文本一律脱敏，key 不进日志。

## Spark 评测（2026-09-26，Qwen3.6-35B-A3B，DGX Spark 上阶段二的 llama-server）

| 样本 | 应命中 | 命中 | 误报 | 漏报 | 风险抓到 | 耗时 |
|---|---|---|---|---|---|---|
| s01_胃胀失眠 | 7 | 7 | 0 | 0 | 1/1 | 40s |
| s02_头痛用药矛盾 | 6 | 6 | 0 | 0 | – | 40s |
| s03_焦虑回避 | 6 | 5 | 0 | 1 | – | 34s |
| s04_平稳对照 | 3 | 3 | 0 | 0 | – | 34s |
| s05_胸闷急重 | 4 | 4 | 0 | 0 | 2/2 | 28s |

合计 precision 1.00 · recall 0.96 · 风险召回 3/3，5 段共 177 秒。只漏了 s03 第 3 轮「都还好」的情绪组。
同一台 Spark 上对数字人落盘的 2 段问诊记录各跑一次，0 次后端出错。
部署方法见 `apps/emotion/deploy/README.md`。

## 本机评测（2026-09-24，qwen3-vl:8b，RTX 5070）

| 样本 | 应命中 | 命中 | 误报 | 漏报 | 风险抓到 | 耗时 |
|---|---|---|---|---|---|---|
| s01_胃胀失眠 | 7 | 7 | 0 | 0 | 1/1 | 31s |
| s02_头痛用药矛盾 | 6 | 6 | 0 | 0 | – | 26s |
| s03_焦虑回避 | 6 | 4 | 0 | 2 | – | 22s |
| s04_平稳对照 | 3 | 3 | 0 | 0 | – | 22s |
| s05_胸闷急重 | 4 | 3 | 0 | 1 | 2/2 | 19s |

合计 precision 1.00 · recall 0.88 · 风险召回 3/3。漏的是 s03 开头两句极简回答（「就是……最近状态不太好」「都还好」）
和 s05 的「早上忘了吃」。金标准由人标注、待博士审，分数只用来比较题目与模型的改动，不是临床指标。

## 已知限制

- 概率是模型自报的，不是 logprobs；Spark 上换 llama-server 后可在 `backends/prompt.py::to_jev_answers` 换概率来源，接口不变。
- Ollama 的 `/v1` 端点不认 `think:false`，本机必须走 `--backend ollama`（原生 `/api/chat`）；
  qwen3-vl 关思考后正文会落在 `message.thinking`，后端已兼容。
- 每条回答两次调用、串行；20 轮对话约 1–2 分钟。实时判断（影响下一问）留给决赛。
- Spark 上的 llama-server 只有 1 个并发槽，与数字人实时对话共用：有人在演示数字人时别跑批量评测。
- `state.channels` 只是预留字段，语音 / 面部观察条目尚未接入。

## 目录

```text
questions_emotion.py / questions_medical.py   两组题（Jev 格式，中文标签）
state.py        对话 → state（最近 N 轮 + 当时在答哪一题 + 预留 channels）
answers.py      归一化、unknown 判定、重要度、风险（只抬不压）
rank.py         风险永远最前，其余按重要度
engine.py       analyze_session()：唯一入口
render_html.py  医生视图
__main__.py     命令行 run
backends/       base（协议、退回）· prompt（共用 schema/prompt）· ollama_native · local_openai · jev_cloud
sources.py      会话来源：.json 会话 / 数字人问诊记录 .jsonl（保留事件时间 t）
watch.py        问诊结束后自动判断（Spark 常驻服务）
samples/        5 段虚构对话        eval/  gold.json · metrics · run_eval        tests/  73 个测试
```
