#!/usr/bin/env bash
# 方案A-步骤10：LLM 通路冒烟（不需要浏览器 / WebRTC）
# 直接调用 LiveTalking 的 llm.py，用假的 avatar_session 收集「推给 TTS 的句子」，
# 因此可以在没有前端连接的情况下验证 provider 是否接通、是否复用 agent 会话。
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

# 凭据只从本机文件读取（与 03_run.sh 保持一致）
if [ -f "$OPENCLAW_KEY_FILE" ]; then
  export OPENCLAW_API_KEY="$(cat "$OPENCLAW_KEY_FILE")"
fi
if [ -f "$LOCAL_LLM_KEY_FILE" ]; then
  export LOCAL_LLM_API_KEY="$(cat "$LOCAL_LLM_KEY_FILE")"
fi

case "$LLM_PROVIDER" in
  openclaw) LLM_MODEL="${OPENCLAW_MODEL}" ;;
  *)        LLM_MODEL="${LOCAL_LLM_MODEL}" ;;
esac

echo "==> provider=${LLM_PROVIDER} model=${LLM_MODEL} session=${LLM_SMOKE_SESSION:-lt-smoke-1}"
echo "==> 第 2 轮会复用同一 session，用来验证 agent 是否跨轮记住上下文"

cd "$APP_DIR"
LLM_SMOKE_PROVIDER="$LLM_PROVIDER" LLM_SMOKE_MODEL="$LLM_MODEL" \
  "$VENV/bin/python" - <<'PY'
import os
import sys
import time

import llm

PROVIDER = os.getenv('LLM_SMOKE_PROVIDER', 'openclaw')
MODEL = os.getenv('LLM_SMOKE_MODEL', '')
SESSION = os.getenv('LLM_SMOKE_SESSION', 'lt-smoke-1')
TURNS = [t for t in os.getenv('LLM_SMOKE_TURNS', '').split('|') if t] or [
    '我这两天胃不舒服，有点胀',
    '上腹，饭后更胀',
]


class Opt:
    def __init__(self, provider, model):
        self.llm_provider = provider
        self.llm_model = model


class FakeAvatar:
    """最小替身：只需要 opt / sessionid / put_msg_txt。"""

    def __init__(self, provider, model, sessionid):
        self.opt = Opt(provider, model)
        self.sessionid = sessionid
        self.count = 0

    def put_msg_txt(self, txt, datainfo=None):
        self.count += 1
        print(f"  [TTS] {txt}")


print('==> registered providers:', list(llm.LLM_PROVIDERS))
fail = 0
for i, msg in enumerate(TURNS, 1):
    avatar = FakeAvatar(PROVIDER, MODEL, SESSION)
    started = time.perf_counter()
    llm.llm_response(msg, avatar)
    elapsed = time.perf_counter() - started
    print(f"==> turn {i} [{msg}] elapsed={elapsed:.2f}s sentences={avatar.count}")
    if avatar.count == 0:
        print('    !! 没有产出任何句子（TTS 会保持静音）')
        fail = 1
sys.exit(fail)
PY
rc=$?
echo "==> 结束（rc=$rc，0=每轮都有话可播）"
exit $rc
