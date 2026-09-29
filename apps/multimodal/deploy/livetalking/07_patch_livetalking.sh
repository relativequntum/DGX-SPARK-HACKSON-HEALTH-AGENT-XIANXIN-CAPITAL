#!/usr/bin/env bash
# 方案A-步骤7：给 LiveTalking 打本地化补丁（本地 TTS 适配器 + OpenClaw/本地 LLM 接入）
# 说明：只做最小侵入修改，且可重复执行（幂等）。补丁文件同目录保留，便于重建机器时复用。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck disable=SC1091
source ./env.sh

echo "==> [1/6] 安装本地 TTS 适配器 -> $APP_DIR/tts/localtts.py"
cp -f ./patches/tts_localtts.py "$APP_DIR/tts/localtts.py"

# 上游按 avatars/base_avatar.py 里的 _tts_modules 表 import TTS 模块；表里没有 localtts 时
# 只打一行 "TTS module localtts not found." 且不创建 TTS，默认的 --tts localtts 直接失效（数字人不出声）。
echo "==> [2/6] 在 avatars/base_avatar.py 注册 localtts（--tts localtts -> tts.localtts）"
"$VENV/bin/python" - "$APP_DIR" <<'PY'
import os, sys

app_dir = sys.argv[1]
p = os.path.join(app_dir, "avatars/base_avatar.py")
s = open(p, encoding="utf-8").read()
if "'localtts': 'tts.localtts'" in s:
    print("    base_avatar.py: localtts 注册已打过")
else:
    old = """            'omnitts': 'tts.omnitts'
        }"""
    new = """            'omnitts': 'tts.omnitts',
            'localtts': 'tts.localtts',
        }"""
    assert old in s, "base_avatar.py _tts_modules 锚点未找到（上游版本变化？请手工对齐）"
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("    base_avatar.py: 已注册 localtts")
PY
"$VENV/bin/python" -c "import ast; ast.parse(open('$APP_DIR/avatars/base_avatar.py', encoding='utf-8').read()); print('==> base_avatar.py 语法 OK')"

echo "==> [3/6] 安装 llm.py（openclaw provider + 会话复用 + 失败降级 + TTS 文本清理）"
if [ -f "$APP_DIR/llm.py" ] && [ ! -f "$APP_DIR/llm.py.bak-pre-openclaw" ]; then
  cp -a "$APP_DIR/llm.py" "$APP_DIR/llm.py.bak-pre-openclaw"
  echo "    已备份原 llm.py -> $APP_DIR/llm.py.bak-pre-openclaw"
fi
cp -f ./patches/llm.py "$APP_DIR/llm.py"

"$VENV/bin/python" -c "import ast; ast.parse(open('$APP_DIR/llm.py', encoding='utf-8').read()); print('==> llm.py 语法 OK')"
grep -q '"openclaw"' "$APP_DIR/llm.py" && echo "==> openclaw provider 已就绪" || { echo "!! 未找到 openclaw provider"; exit 1; }

# 问诊转写落盘：llm.py 会 import 它，缺失时对话照常、医生端只是没有记录
echo "==> [4/6] 安装 consult_recorder.py（每轮问诊落盘，供医生端 doctor_service.py 读取）"
cp -f ./patches/consult_recorder.py "$APP_DIR/consult_recorder.py"
"$VENV/bin/python" -c "import ast; ast.parse(open('$APP_DIR/consult_recorder.py', encoding='utf-8').read()); print('==> consult_recorder.py 语法 OK')"
mkdir -p "$DOCTOR_RECORD_DIR"
chmod 700 "$DOCTOR_RECORD_DIR"
echo "    记录目录: $DOCTOR_RECORD_DIR"

echo "==> [5/6] WebRTC ICE 补丁：禁用 STUN，只把 $ICE_HOST 作为服务端候选"
"$VENV/bin/python" - "$APP_DIR" <<'PY'
import os, sys

app_dir = sys.argv[1]

# 1) rtc_manager.py：不再向 STUN 查询 srflx 候选
#    租机出网 UDP 常被禁，srflx/pub 候选会让 TURN 向不可达的公网地址发 UDP
#    （coturn 日志: udp send: Operation not permitted），ICE 直接 failed。
p = os.path.join(app_dir, "server/rtc_manager.py")
s = open(p, encoding="utf-8").read()
if "LIVETALKING_DISABLE_STUN" in s:
    print("    rtc_manager.py: 已打过补丁")
else:
    old = """        ice_server = RTCIceServer(urls=self.opt.stun)
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=[ice_server])
        )"""
    new = """        # 禁用 STUN：只保留本机 host 候选，媒体经本机 TURN 中继
        _stun = (getattr(self.opt, "stun", "") or "").strip()
        if os.getenv("LIVETALKING_DISABLE_STUN", "1") != "0":
            _stun = ""
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=[RTCIceServer(urls=_stun)] if _stun else [])
        )"""
    assert old in s, "rtc_manager.py 锚点未找到（上游版本变化？请手工对齐）"
    if "import os" not in s.split("\n\n")[0]:
        s = s.replace("import json", "import os\nimport json", 1)
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("    rtc_manager.py: STUN 已禁用")

# 2) aioice：只把 AIOICE_HOST_ALLOWLIST 列出的地址放进 ICE 候选
#    docker0(172.17.0.1)、隧道网卡等在 TURN 中继场景下不可达，同样会拖垮 ICE。
import aioice
p = os.path.join(os.path.dirname(aioice.__file__), "ice.py")
s = open(p, encoding="utf-8").read()
if "AIOICE_HOST_ALLOWLIST" in s:
    print("    aioice/ice.py: 已打过补丁")
else:
    old = """            elif use_ipv6 and ip.ip[0] != "::1" and ip.ip[2] == 0:
                addresses.append(ip.ip[0])
    return addresses"""
    new = """            elif use_ipv6 and ip.ip[0] != "::1" and ip.ip[2] == 0:
                addresses.append(ip.ip[0])
    # 只保留显式允许的地址：docker0 / 隧道网卡的候选在 TURN 中继场景下不可达
    import os as _os
    _allow = [x.strip() for x in _os.getenv("AIOICE_HOST_ALLOWLIST", "").split(",") if x.strip()]
    if _allow:
        addresses = [a for a in addresses if a in _allow]
    return addresses"""
    assert old in s, "aioice/ice.py 锚点未找到（版本变化？请手工对齐）"
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("    aioice/ice.py: 候选白名单已启用")
PY
"$VENV/bin/python" -c "import ast; ast.parse(open('$APP_DIR/server/rtc_manager.py', encoding='utf-8').read()); print('==> rtc_manager.py 语法 OK')"

# 6) /offer 支持客户端指定 sessionid：一次问诊固定一个 ID，断线重连后复用。
#    不打这个补丁的话，每次 WebRTC 重连都会拿到新随机 ID：
#    医生端同一次问诊被拆成多条记录，OpenClaw agent 的问诊上下文也会丢。
echo "==> [6/6] /offer 接受客户端会话 ID（断线重连保持同一次问诊）"
"$VENV/bin/python" - "$APP_DIR" <<'PY'
import os, sys

app_dir = sys.argv[1]
p = os.path.join(app_dir, "server/rtc_manager.py")
s = open(p, encoding="utf-8").read()
if "LT_CLIENT_SESSIONID" in s:
    print("    rtc_manager.py: 客户端会话 ID 补丁已打过")
else:
    old = """        try:
            sessionid = await session_manager.create_session(params)
        except MaxSessionError as e:"""
    new = """        # LT_CLIENT_SESSIONID: 客户端（triage 页面）可携带固定会话 ID。
        # 只接受安全字符，防止把 ID 拼进记录文件路径时注入。
        client_sid = str(params.get("sessionid") or "")
        if not (8 <= len(client_sid) <= 64) or not all(c.isalnum() or c in "_-" for c in client_sid):
            client_sid = None
        try:
            if client_sid and session_manager.has_session(client_sid):
                # 同 ID 重建（断线重连）：先清掉残留旧会话，再建新的
                session_manager.remove_session(client_sid)
            sessionid = await session_manager.create_session(params, sessionid=client_sid)
        except MaxSessionError as e:"""
    assert old in s, "rtc_manager.py handle_offer 锚点未找到（上游版本变化？请手工对齐）"
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("    rtc_manager.py: /offer 已支持客户端会话 ID")
PY
"$VENV/bin/python" -c "import ast; ast.parse(open('$APP_DIR/server/rtc_manager.py', encoding='utf-8').read()); print('==> rtc_manager.py 语法 OK（offer 补丁后）')"
echo "==> 完成。启动方式：03_run.sh（默认 --tts localtts --llm_provider openclaw，失败自动降级到 local）"
