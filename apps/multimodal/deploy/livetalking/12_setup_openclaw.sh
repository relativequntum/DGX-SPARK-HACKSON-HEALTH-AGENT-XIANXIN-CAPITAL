#!/usr/bin/env bash
###############################################################################
#  步骤12：OpenClaw 配置（把数字人的"对话大脑"接到本机 OpenClaw agent）
#
#  作用（全部幂等，带备份）：
#    1) 开启 Gateway 的 OpenAI 兼容端点 /v1/chat/completions（默认关闭）
#    2) 注册本地模型 provider，指向 11_setup_local_llm.sh 起的 llama-server
#    3) 关闭 thinking/reasoning —— 语音对话里"想得久"等于"答不出来"
#    4) 注册预问诊 agent 并指向其 workspace（含 Skill 与 AGENTS.md）
#    5) 导出 gateway token 到 OPENCLAW_KEY_FILE，供 03_run.sh 使用（不入库）
#    6) 把仓库里的 workspace 副本（apps/multimodal/deploy/openclaw/workspace-tcm）同步到 OPENCLAW_WORKSPACE：
#       只新增/覆盖副本里有的文件，内容不同的先备份为 <文件>.bak-<时间戳>；workspace 里其他文件一律不动
#    7) 向该 workspace 的 AGENTS.md 注入三条必备规则（会话隔离/语音优先/降低写盘频率）
#       ——仓库副本已含这三条，同步后这里只会提示"规则已齐备"
#    8) 重启 gateway 并自测（端点、agent 路由、一次真实调用）
#
#  前置：
#    - OpenClaw 已安装且 gateway 能启动（本脚本不负责安装 OpenClaw 本身）；
#    - agent 的 workspace 用 OPENCLAW_WORKSPACE 指定；不存在时由第 6 步从仓库副本新建
#      （副本位置自动查找，也可用 OPENCLAW_WS_SRC 指定）；
#    - 已执行 11_setup_local_llm.sh（provider 指向的端点必须可用）。
#
#  说明：第 7 步针对的是 tcm 预问诊 Skill 的 AGENTS.md 文本锚点；若你的 workspace
#        结构不同，脚本会跳过该项并提示，请按 README「OpenClaw 对话接入」一节手工对齐。
###############################################################################
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

for cmd in jq curl; do
  command -v "$cmd" >/dev/null || { echo "!! 缺少依赖: $cmd"; exit 1; }
done

OPENCLAW_BIN="$(command -v openclaw || true)"
[ -z "$OPENCLAW_BIN" ] && [ -x "$HOME/.openclaw/bin/openclaw" ] && OPENCLAW_BIN="$HOME/.openclaw/bin/openclaw"
if [ -z "$OPENCLAW_BIN" ]; then
  echo "!! 未找到 openclaw 命令。请先安装 OpenClaw 并完成 onboard，再执行本脚本。"
  exit 1
fi
[ -f "$OPENCLAW_CONFIG" ] || { echo "!! 未找到配置 $OPENCLAW_CONFIG（先运行 openclaw onboard）"; exit 1; }

# agent workspace 的仓库副本（AGENTS.md / SOUL.md / IDENTITY.md / tcm-preconsultation Skill）
# 仓库内：deploy/livetalking/../openclaw/workspace-tcm；租机平铺拷贝：同目录 ./openclaw/workspace-tcm
WS_SRC="${OPENCLAW_WS_SRC:-}"
if [ -z "$WS_SRC" ]; then
  if [ -d ../openclaw/workspace-tcm ]; then
    WS_SRC="$(cd ../openclaw/workspace-tcm && pwd)"
  elif [ -d ./openclaw/workspace-tcm ]; then
    WS_SRC="$(cd ./openclaw/workspace-tcm && pwd)"
  fi
elif [ -d "$WS_SRC" ]; then
  WS_SRC="$(cd "$WS_SRC" && pwd)"
else
  echo "!! OPENCLAW_WS_SRC 不是目录: $WS_SRC"; exit 1
fi
# workspace 不存在时由第 6 步从副本新建；两者都没有才无法继续
if [ -z "$WS_SRC" ] && [ ! -d "$OPENCLAW_WORKSPACE" ]; then
  echo "!! agent workspace 不存在: $OPENCLAW_WORKSPACE，且找不到仓库副本 openclaw/workspace-tcm"
  echo "   请显式指定：OPENCLAW_WS_SRC=/path/to/apps/multimodal/deploy/openclaw/workspace-tcm bash 12_setup_openclaw.sh"
  exit 1
fi

LLM_KEY="$(cat "$LOCAL_LLM_KEY_FILE" 2>/dev/null || echo '')"
[ -n "$LLM_KEY" ] || { echo "!! 读不到本地 LLM 密钥: $LOCAL_LLM_KEY_FILE（先跑 11_setup_local_llm.sh）"; exit 1; }

# ---------- 1~4. 写入 openclaw.json ----------
echo "==> [1/8] 备份并更新 $OPENCLAW_CONFIG"
cp -a "$OPENCLAW_CONFIG" "$OPENCLAW_CONFIG.bak.pre-livetalking"

jq --arg provider "$OPENCLAW_PROVIDER" \
   --arg base "$LOCAL_LLM_BASE_URL" \
   --arg model "$LLM_MODEL_ALIAS" \
   --arg apikey "$LLM_KEY" \
   --arg agent "$OPENCLAW_AGENT_ID" \
   --arg ws "$OPENCLAW_WORKSPACE" \
   --argjson ctx "${LLM_CTX:-65536}" \
'
  .gateway.http.endpoints.chatCompletions.enabled = true
  | .models.mode = "merge"
  | .models.providers[$provider] = {
      "baseUrl": $base,
      "apiKey": $apikey,
      "api": "openai-completions",
      "timeoutSeconds": 1800,
      "models": [{
        "id": $model,
        "name": ($model + " (local)"),
        "reasoning": true,
        "input": ["text", "image"],
        "contextWindow": $ctx,
        "maxTokens": 8192,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "compat": {
          "supportsDeveloperRole": false,
          "supportsStore": false,
          "supportsReasoningEffort": false,
          "supportsTools": true,
          "maxTokensField": "max_tokens",
          "thinkingFormat": "qwen-chat-template",
          "requiresReasoningContentOnAssistantMessages": true
        }
      }]
    }
  | .agents.ownership = "explicit"
  | .agents.defaults.model.primary = ($provider + "/" + $model)
  | .agents.defaults.imageModel.primary = ($provider + "/" + $model)
  | .agents.defaults.models = { ($provider + "/" + $model):
      {"alias": $model, "params": {"temperature": 0.7, "topP": 0.8}} }
  | .agents.defaults.modelPolicy.allow = [($provider + "/" + $model)]
  | .agents.defaults.thinkingDefault = "off"
  | .agents.defaults.reasoningDefault = "off"
  | .agents.entries[$agent].workspace = $ws
  | .agents.entries[$agent].model = ($provider + "/" + $model)
' "$OPENCLAW_CONFIG" > /tmp/openclaw.new.json
cp /tmp/openclaw.new.json "$OPENCLAW_CONFIG"
chmod 600 "$OPENCLAW_CONFIG"
jq -c '{endpoint: .gateway.http.endpoints.chatCompletions.enabled,
        primary: .agents.defaults.model.primary,
        thinking: .agents.defaults.thinkingDefault,
        allow: .agents.defaults.modelPolicy.allow,
        agent: .agents.entries['"$OPENCLAW_AGENT_ID"'].workspace}' "$OPENCLAW_CONFIG" | sed 's/^/    /'

# ---------- 5. 导出 gateway token ----------
echo "==> [5/8] 导出 gateway token -> $OPENCLAW_KEY_FILE"
AUTH_MODE="$(jq -r '.gateway.auth.mode // "none"' "$OPENCLAW_CONFIG")"
if [ "$AUTH_MODE" = "token" ]; then
  mkdir -p "$(dirname "$OPENCLAW_KEY_FILE")"
  chmod 700 "$(dirname "$OPENCLAW_KEY_FILE")"
  (umask 077; jq -r '.gateway.auth.token' "$OPENCLAW_CONFIG" > "$OPENCLAW_KEY_FILE")
  echo "    已写入（600），03_run.sh 会读取它作为 OPENCLAW_API_KEY"
else
  echo "    警告: gateway.auth.mode=$AUTH_MODE，端点不需要 token；03_run.sh 会以空 key 调用"
fi

# ---------- 6. 同步 workspace 仓库副本 ----------
# 只处理副本里有的文件：缺失则新增、内容不同则先备份再覆盖、相同则跳过；
# workspace 里的其他文件（records/ 问诊记录、memory/ agent 记忆等）不删、不改。
echo "==> [6/8] 同步 agent 工作区：${WS_SRC:-（无仓库副本）} -> $OPENCLAW_WORKSPACE"
if [ -z "$WS_SRC" ]; then
  echo "    跳过: 未找到仓库副本，沿用现有 workspace"
else
  if [ ! -d "$OPENCLAW_WORKSPACE" ]; then
    mkdir -p "$OPENCLAW_WORKSPACE"
    chmod 700 "$OPENCLAW_WORKSPACE"   # 之后 records/ 会存问诊内容
    echo "    已新建 workspace（700）"
  fi
  STAMP="$(date +%Y%m%d-%H%M%S)"
  n_new=0; n_upd=0; n_same=0
  while IFS= read -r -d '' src; do
    rel="${src#"$WS_SRC"/}"
    dst="$OPENCLAW_WORKSPACE/$rel"
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
      n_same=$((n_same + 1))
      continue
    fi
    mkdir -p "$(dirname "$dst")"
    if [ -e "$dst" ]; then
      cp -a "$dst" "$dst.bak-$STAMP"
      echo "    更新 $rel（原文件已备份为 $(basename "$dst").bak-$STAMP）"
      n_upd=$((n_upd + 1))
    else
      echo "    新增 $rel"
      n_new=$((n_new + 1))
    fi
    cp "$src" "$dst"
  done < <(find "$WS_SRC" -type f -print0 | sort -z)
  echo "    新增 $n_new / 更新 $n_upd / 未变 $n_same（其他文件未改动）"
fi

# ---------- 7. 注入 AGENTS.md 必备规则 ----------
echo "==> [7/8] 检查 agent 工作区规则（会话隔离 / 语音优先 / 降低写盘频率）"
OPENCLAW_WORKSPACE="$OPENCLAW_WORKSPACE" python3 - <<'PY'
import os
import pathlib
import shutil

ws = pathlib.Path(os.environ["OPENCLAW_WORKSPACE"])
agents_md = ws / "AGENTS.md"
if not agents_md.is_file():
    print("    跳过: 未找到", agents_md)
    raise SystemExit(0)

text = agents_md.read_text(encoding="utf-8")
backup = agents_md.with_suffix(".md.bak-livetalking")
if not backup.exists():
    shutil.copy2(agents_md, backup)
    print("    已备份:", backup.name)

changed = []

# (a) 降低写盘频率：语音场景下每轮写整份草稿要多生成数百 token
old_write = ("每次收到患者或辅助者/看护者的有效回答，先保留原话与修正关系，以 write 工具更新该目录的 draft.json，再提出下一题。")
new_write = ("每次收到患者或辅助者/看护者的有效回答，先在回复中保留原话与修正关系，再提出下一题。"
             "为降低实时对话延迟，draft.json 不必每轮重写：每 3 轮、或收到停止/生成记录/暂停指令、"
             "或本轮新增事实达到 3 条以上时，才用 write 工具更新该目录的 draft.json；其余轮次只在回复里保留事实，不调用 write。")
if "draft.json 不必每轮重写" in text:
    pass
elif old_write in text:
    text = text.replace(old_write, new_write, 1)
    changed.append("降低写盘频率")
else:
    print("    ! 未找到写盘规则锚点，请按 README 手工确认")

# (b) 会话隔离：否则新会话会沿用 records/ 里上一次的病历
old_iso = ("每次新的问诊，在 records/ 下创建本会话独立目录；用 session_status 中的会话标识或本次生成的唯一标识命名，"
           "只使用 ASCII 字母数字短横线下划线。沿用当前会话已建立的目录，不读取其他会话病历。")
new_iso = ("每次新的问诊，先用 session_status 取得本会话标识，在 records/ 下建立目录 `session-<会话标识>`"
           "（只使用 ASCII 字母数字短横线下划线）。只读写这一个目录：目录不存在就新建；"
           "不得读取、沿用或参考 records/ 下任何其他会话的目录与病历；未确定会话标识前不要落盘，"
           "也不要用描述性名字（如 `2026-09-23_胃胀`）建目录。")
if "只读写这一个目录" in text:
    pass
elif old_iso in text:
    text = text.replace(old_iso, new_iso, 1)
    changed.append("会话隔离")
else:
    print("    ! 未找到记录目录命名锚点，请按 README 手工确认")

# (c) 语音优先：把每轮回复压到 1-2 句
anchor = "## 本平台的记录能力"
block = """## 本平台的交互形态（语音优先，务必遵守）

本平台是数字人的**实时语音对话**：患者用说话交互，听到的是语音（TTS），屏幕上同时有文字。
因此一律沿用 skill 的「纯语音」规则作答：

- 一轮只问一个核心问题；需要给选项时最多简短读 3 项，不铺开长列表；
- 回复控制在 1-2 句话说清，先复述关键信息再提问；
- 不要输出 Markdown 标题、表格、分隔线、缩进列表、emoji；编号不超过 3 项；
- 不要长篇解释病因或给出治疗/用药建议，这些留给医生。

"""
if "语音优先" in text:
    pass
elif anchor in text:
    text = text.replace(anchor, block + anchor, 1)
    changed.append("语音优先")
else:
    print("    ! 未找到插入锚点，请按 README 手工为语音场景补充规则")

if changed:
    agents_md.write_text(text, encoding="utf-8")
    print("    已注入:", "、".join(changed))
else:
    print("    规则已齐备，无需改动")
PY

# ---------- 8. 重启并自测 ----------
echo "==> [8/8] 重启 gateway 并自测"
systemctl --user restart openclaw-gateway 2>/dev/null || true
PORT="$(jq -r '.gateway.port // 18789' "$OPENCLAW_CONFIG")"
# 网关端点用 gateway token（第 5 步导出的 OPENCLAW_KEY_FILE），不是 llama-server 的 LLM_KEY；auth.mode=none 时为空
GW_KEY="$(cat "$OPENCLAW_KEY_FILE" 2>/dev/null || true)"
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 3 --noproxy '*' "http://127.0.0.1:${PORT}/v1/models" \
    -H "Authorization: Bearer $GW_KEY" || echo 000)
  [ "$code" = "200" ] && break
  sleep 2
done
echo "    /v1/models -> $code"
curl -s -m 10 --noproxy '*' -H "Authorization: Bearer $GW_KEY" \
  "http://127.0.0.1:${PORT}/v1/models" | jq -r '.data[].id' 2>/dev/null | sed 's/^/    agent 目标: /'

echo "==> 自测：调用 agent 一轮（首个会话会读 Skill，可能 3-10s）"
printf '{"model":"openclaw/%s","messages":[{"role":"user","content":"我这两天胃不舒服，有点胀"}],"stream":true,"user":"setup-smoke-1"}' \
  "$OPENCLAW_AGENT_ID" > /tmp/openclaw_smoke.json
curl -sN -o /tmp/openclaw_smoke.out \
  -w "    total=%{time_total}s http=%{http_code}\n" -m 300 --noproxy '*' \
  -H "Authorization: Bearer $GW_KEY" -H 'Content-Type: application/json' \
  -d @/tmp/openclaw_smoke.json "http://127.0.0.1:${PORT}/v1/chat/completions"
python3 -c "
import json
s = open('/tmp/openclaw_smoke.out', encoding='utf-8').read()
out = []
for line in s.splitlines():
    if line.startswith('data: ') and 'content' in line:
        try:
            d = json.loads(line[6:])
            c = d['choices'][0]['delta'].get('content')
            if c: out.append(c)
        except Exception: pass
print('    agent 回复:', (''.join(out)[:120] or '(空)'))
"
echo "==> 完成。数字人侧配置见 env.sh（LLM_PROVIDER=openclaw, OPENCLAW_MODEL=openclaw/${OPENCLAW_AGENT_ID}）"
