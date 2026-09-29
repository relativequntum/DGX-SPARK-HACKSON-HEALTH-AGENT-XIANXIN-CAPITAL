# OpenClaw 预问诊 agent 工作区（`workspace-tcm/`）

`workspace-tcm/` 是 DGX Spark 上 OpenClaw 预问诊 agent（agent id `tcm`）工作区 `~/.openclaw/workspace-tcm`
截至 **2026-09-29** 的快照，以机器上实际运行的版本为准，文件内容逐字节原样拷贝。

## 收录范围

| 路径 | 作用 |
| --- | --- |
| `AGENTS.md` | agent 行为规则（已含 `12_setup_openclaw.sh` 要求的三条规则：语音优先 / 会话隔离 / 降低写盘频率） |
| `SOUL.md`、`IDENTITY.md` | agent 的语气与身份 |
| `skills/tcm-preconsultation/` | 预问诊 Skill：`SKILL.md`、`agents/openai.yaml`、`references/`（问法、安全与来源、记录模板、来源索引） |

## 不收录的内容及原因

| 路径 | 原因 |
| --- | --- |
| `records/` | 每次问诊的草稿与记录（`draft.json`、医生参考版、患者核对版），就是问诊内容 |
| `memory/`、`DREAMS.md`、`USER.md` | agent 自动积累的记忆与会话语料，可能夹带问诊内容 |
| `test-01.txt`、`AGENTS.md.bak-*`、`.git/` | 本机调试遗留与历史备份 |

会话记录和 agent 记忆可能含问诊内容，按仓库根目录 `AGENTS.md` §3（不在仓库中提交真实患者信息）一律不入库；
从机器更新本快照时也只拷回上表「收录范围」内的文件。

**已知差异**：Spark 上 `references/` 下 4 个文件名目前是乱码（UTF-8 被误按 CP866 解码，如 `хоЙхЕиф╕ОцЭец║Р.md` 应为 `安全与来源.md`），
`SKILL.md` 里按中文名写的链接因此打不开；仓库按正确中文名入库（内容与机器一致），
`12_setup_openclaw.sh` 同步时会新增这 4 个正确命名的文件，但不会删除乱码文件，确认无误后可手工删除。

## `12_setup_openclaw.sh` 如何使用

第 6 步把本目录 `workspace-tcm/` 同步到 `OPENCLAW_WORKSPACE`（默认 `~/.openclaw/workspace-tcm`），第 7 步再检查规则注入：

- workspace 不存在则新建（因此新机器不必先手工准备 workspace）；
- 只处理本目录里有的文件：目标不存在则新增；内容不同则先备份为 `<文件>.bak-<YYYYmmdd-HHMMSS>` 再覆盖；内容相同则跳过；
- workspace 里的其他文件（`records/`、`memory/`、`USER.md` 等）不删、不改；
- 副本位置默认自动查找（仓库内 `../openclaw/workspace-tcm`，或租机平铺拷贝的 `./openclaw/workspace-tcm`），可用 `OPENCLAW_WS_SRC` 显式指定；
- 本快照的 `AGENTS.md` 已含三条规则，第 7 步只会提示「规则已齐备，无需改动」。

`.gitattributes` 对 `workspace-tcm/**` 关闭了换行转换（`references/来源索引.json` 本身是 CRLF），入库与检出都与机器逐字节一致。
