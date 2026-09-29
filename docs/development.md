# 开发准备指南

项目对外介绍见根目录 [`README.md`](../README.md)；本文件面向参与开发的成员和编码 Agent。

## 三阶段分工

| 阶段 | 名称 | 负责人 | 计划方向 |
|---|---|---|---|
| 1 | 动态文字预问诊系统 | 史静宇 `@relativequntum` | 动态问题选择、会话状态、预问诊摘要 |
| 2 | 多模态动态预问诊系统 | 陈科顺 `@keshunchen` | 语音交互、语音生成、动态头像 |
| 3 | 情感识别问诊系统 | 曹昶皓 `@ari1206`、李虹雨 `@hongyu` | 语音情感与面部表情识别 |

其他成员以专业领域专家身份参与医疗流程、问题内容、安全边界和演示结果评审，不分配固定开发任务。

## 基础工具

- Git
- GitHub CLI `gh`
- 各成员选择的编码 Agent
- 后续由技术方案决定的语言、运行时和依赖工具

阶段二、三已有可运行实现，运行与部署方式见各自目录的 README 和 `deploy/` 说明；全项目统一的技术栈尚未冻结。

## 首次参与

```bash
git clone https://github.com/relativequntum/spark-Hackson.git
cd spark-Hackson
git config pull.rebase true
gh auth status
```

然后：

1. 阅读根目录 `AGENTS.md`；
2. 查看 `docs/看板.md`；
3. 使用 `gh issue list` 查看开放事项；
4. 使用 `gh issue view <N> --comments` 阅读任务全文；
5. 在开始编码前确认 Issue 中已有范围和验收标准。

## 协作方式

本项目采用 GitHub Issue 驱动协作。所有开发者和编码 Agent 开工前必须阅读 [`AGENTS.md`](../AGENTS.md)。

基本流程：

1. 从路线图中选取或创建 Issue；
2. 明确负责人、范围、非范围和验收标准；
3. 涉及跨阶段公共契约时先发起 `[裁决]`；
4. 在独立分支开发并通过 PR 提交；
5. 在 PR 中记录实际验证证据和医疗安全影响。

## 分支与提交

```bash
git pull --rebase
git switch -c feat/issue-<N>-short-name
```

提交格式和公共契约规则以 `AGENTS.md` 为准。

## DGX Spark 准备事项

开始模型相关工作前，应通过 Issue 记录：

- 系统架构、驱动、CUDA 和容器工具版本；
- 候选模型来源、许可证、大小和校验值；
- 推理框架与 ARM64/系统兼容性；
- 冷启动、热态延迟、吞吐和内存占用；
- 离线运行方式；
- 多模态模块的资源竞争与降级策略。

实测结果应提交到仓库文档，而不是只记录在群聊。

## 医疗内容开发

问题树、红旗规则、问诊措辞、摘要格式和演示病例都必须在对应 Issue 中标注领域专家审阅要求。禁止使用真实患者数据作为开发或公开演示材料。

## 项目文档

- [产品构想与范围](product.md)
- [架构原则](architecture/overview.md)
- [路线图](roadmap.md)
- [医疗安全与隐私](safety-and-privacy.md)
- [Issue 协作模式](../gh-issue协同开发模式.md)
- [Issue 协作看板](看板.md)
