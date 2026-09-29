#!/usr/bin/env bash
###############################################################################
#  TURN over TCP 冒烟：容器 → 监听 → 凭据接口 → TCP 中继收发
###############################################################################
set -uo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BASE_DIR/env.sh"

TURN_PORT="${TURN_PORT:-3478}"
TURN_CONTAINER="${TURN_CONTAINER:-coturn}"
rc=0
ok()   { echo "OK   $*"; }
bad()  { echo "FAIL $*"; rc=1; }

echo "==> [1/4] coturn 容器状态"
if docker ps --filter "name=$TURN_CONTAINER" --format '{{.Names}}' 2>/dev/null | grep -qx "$TURN_CONTAINER"; then
  ok "$(docker ps --filter "name=$TURN_CONTAINER" --format '{{.Names}}: {{.Status}}')"
else
  bad "容器 $TURN_CONTAINER 未运行（先跑 08_setup_turn.sh）"; exit 1
fi

echo "==> [2/4] TCP $TURN_PORT 是否监听"
if ss -ltn 2>/dev/null | grep -q ":$TURN_PORT "; then
  ok "监听 $(ss -ltn 2>/dev/null | grep ":$TURN_PORT " | awk '{print $4}' | tr '\n' ' ')"
else
  bad "$TURN_PORT 未监听"; exit 1
fi

echo "==> [3/4] /api/turn 临时凭据"
CREDS="$(curl -s -m 5 --noproxy "*" "http://127.0.0.1:${PORT}/api/turn" || true)"
U="$(echo "$CREDS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["iceServers"][0]["username"])' 2>/dev/null || true)"
C="$(echo "$CREDS" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["iceServers"][0]["credential"])' 2>/dev/null || true)"
if [ -n "$U" ] && [ -n "$C" ]; then
  ok "username=$U"
else
  bad "/api/turn 未返回有效凭据（LiveTalking 是否重启过？）"; exit 1
fi

echo "==> [4/4] TCP 中继收发（-T 表示客户端到 TURN 走 TCP）"
OUT="$(docker run --rm --network host coturn/coturn \
  turnutils_uclient -T -p "$TURN_PORT" -u "$U" -w "$C" 127.0.0.1 2>&1 | tail -3)"
echo "$OUT" | sed 's/^/     /'
if echo "$OUT" | grep -q "Cannot complete Allocation"; then
  bad "TURN 分配失败（凭据或配置有误）"
else
  ok "TURN over TCP 可用"
fi

echo
[ "$rc" -eq 0 ] && echo "==> TURN 冒烟通过" || echo "==> TURN 冒烟失败"
exit "$rc"
