# gh + Issue 驱动的多人/多 Agent 协同开发模式

> 本文沉淀自既有竞赛项目，并已从“仅适配 Claude Code”更新为**通用编码 Agent 协作规范**。本项目以根目录 `AGENTS.md` 作为仓库宪法。

## 一、模式总览

```text
成员开工 → git pull --rebase ──┬→ AGENTS.md（仓库宪法）
                                └→ docs/看板.md（按人待办）→ 领取 Issue
                                         ↑
                    GitHub Actions：Issue/评论变化后自动重建

成员响应 → 编码 Agent 用 gh 读取 Issue 全文 → 人员确认立场 → gh 回帖
         → 分支开发 → 测试 → PR → 提出方/下发方验收关闭
```

核心思想：**Issue 是唯一正式存档，自动看板负责拉取式触达，`AGENTS.md` 是行为宪法，`gh` CLI 是自动化入口。**群聊只承担紧急提醒，不承担决策存档。

## 二、核心组件

### 1. `AGENTS.md` 仓库宪法

`AGENTS.md` 应包含：

- 项目目标与禁止事项；
- 成员、GitHub 登录名、职责和文件归属；
- 公共契约的唯一属主和变更流程；
- Git/PR 红线；
- Issue 类型和响应纪律；
- 每次编码 Agent 会话的标准工作流；
- 安全、隐私和领域约束。

不同工具加载规则可能不同，成员应在提示词中明确要求编码 Agent 先读 `AGENTS.md`。如使用支持该文件自动发现的 Agent，则会自动生效。子目录可增加更具体的 `AGENTS.md`，但不得放宽根目录安全红线。

### 2. `gh` CLI 全员标配

安装并授权：

```bash
# Windows
winget install --id GitHub.cli -e

# macOS
brew install gh

gh auth login --web
gh auth status
```

常用命令：

```bash
gh issue list
gh issue view 12 --comments
gh issue comment 12 --body "..."
gh pr create --fill
gh pr checks
gh issue close 12
```

登录授权必须由账号本人完成。Agent 不得将 token 写入仓库、日志或评论。

### 3. 三类 Issue

| 类型 | 用途 | 谁表态 | 关闭条件 |
|---|---|---|---|
| `[会签]` | 多方对齐口径、接口、方案 | 全部会签方 | 达成一致，由提出方总结结论并关闭 |
| `[裁决]` | 公共契约、职责冲突、纪律解释 | 相关方陈述，唯一属主拍板 | 裁决落档且对应变更完成后关闭 |
| `[任务]` | 可验收的执行事项 | 负责人完成，审阅者验收 | 验收标准满足，由下发方关闭 |

模板位于 `.github/ISSUE_TEMPLATE/`。模块、阶段、优先级、风险和类型用标签表达，避免只在标题中编码信息。

### 4. 自动看板

`.github/workflows/issues-board.yml` 监听 Issue 和评论事件，重建 `docs/看板.md` 并提交回 `main`。

按人待办应优先展示：

1. 被指派的 Issue；
2. 正文或评论中被 `@` 的 Issue；
3. 自己提出且仍未关闭的 Issue。

状态至少区分：

- `待你首次回应`；
- `有新动态待你看`；
- `你已回应，等待对方`。

看板只是快照，正式上下文仍以 `gh issue view <N> --comments` 为准。

### 5. 响应流程

成员可对自己的编码 Agent 使用如下提示：

> 先读取 `AGENTS.md` 并执行 `git status`、`git pull --rebase`。查看 `docs/看板.md` 中我名下待办，再用 `gh issue view <N> --comments` 读取全文。结合相关代码和文档起草意见；代表我立场的评论必须先让我确认。确认后发布评论，并按 Issue 验收标准开发和验证。

纪律：

- 表态、会签、裁决类评论必须由本人过目；
- 完成通报可由 Agent 发布，但必须包含改动、测试证据、commit/PR 和剩余风险；
- 群聊共识由提出方搬回 Issue 后才算正式结论；
- 不把草稿标题、内部推理或密钥原样贴入 GitHub。

### 6. 通知分级

普通事项依赖 Issue、GitHub 通知和开工时拉取看板，不额外群 @。仅以下情形群内提醒：

1. 阻塞他人开工；
2. 存在明确硬截止；
3. 必须当日回应。

GitHub 登录名必须通过本人或 GitHub API 核实；提交作者名不等于登录名。

## 三、本项目的落地约束

本项目涉及医疗场景，除一般协作纪律外还必须遵守：

- 禁止提交真实患者身份信息、病历、音视频；
- 红旗信号和医疗安全规则变更必须经过领域专家复核；
- LLM 输出不能覆盖确定性安全规则；
- 跨阶段数据模型、API 和安全声明属于公共契约，必须走 `[裁决]` Issue；
- 情感信号只能辅助沟通，不得自动诊断、拒诊或降低医疗风险级别。

详见根目录 [`AGENTS.md`](AGENTS.md) 和 [`docs/safety-and-privacy.md`](docs/safety-and-privacy.md)。

## 四、常见教训

1. 写在文档里的请求如果不开 Issue，就无法被稳定跟踪。
2. 看板表示“相关面”，状态才表示当前球权；不要混淆相关数量和待办数量。
3. 自动看板是快照，不代表评论刚刚发生。
4. Agent 代贴评论前应清除草稿抬头、内部备注和不必要上下文。
5. commit 中不要误写 `closes #N`，除非确实希望合并后自动关闭。
6. 公共契约集中在唯一属主时容易形成瓶颈，应定期清理裁决队列。
7. 自动化修改 `main` 后，成员推送被拒是正常情况；使用 `git pull --rebase`，不要 force push。
8. 医疗原型“能回答”不等于“安全”；红旗、拒答、模型失效和删除数据都必须有测试。

## 五、新项目落地清单

- [x] 根目录建立 `AGENTS.md`；
- [x] 创建会签、裁决、任务 Issue 模板；
- [x] 创建 PR 模板、CODEOWNERS 和基础 CI；
- [x] 创建自动看板 workflow；
- [x] 通过 GitHub API 核实全员 GitHub 登录名；
- [ ] 配置分支保护和 required checks；
- [ ] 创建首批里程碑、标签和 Issue；
- [ ] 跑通一次“提出 → 看板 → 响应 → PR → 验收 → 关闭”的完整链路；
- [ ] 在 DGX Spark 实机验证本地模型与离线演示。