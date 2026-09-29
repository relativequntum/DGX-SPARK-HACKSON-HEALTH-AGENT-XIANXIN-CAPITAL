#!/usr/bin/env bash
###############################################################################
#  WebRTC over TCP：部署 coturn（docker host 网络，无需 sudo）+ 前端强制 relay
#
#  背景：租机在 NAT 后且公网未放通 UDP，WebRTC 媒体流（SRTP/UDP）连不通。
#  方案：在租机上跑 TURN 服务，浏览器通过 TURN 的 **TCP** 通道收发媒体
#        （iceTransportPolicy=relay），TURN 再在本机用 UDP 转发给 LiveTalking。
#  结果：只需要放通 TCP 3478（TURN）与 TCP 8010（页面/信令），不需要任何 UDP。
###############################################################################
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$BASE_DIR/env.sh"

TURN_PORT="${TURN_PORT:-3478}"
TURN_REALM="${TURN_REALM:-}"
if [ -z "$TURN_REALM" ]; then
  echo "错误：TURN_REALM 未设置。请在 $BASE_DIR/env.local.sh 中写入 TURN_REALM=<你的域名>（浏览器访问本机所用的域名），再重跑本脚本。" >&2
  exit 1
fi
TURN_CONTAINER="${TURN_CONTAINER:-coturn}"
SECRET_FILE="${LOCAL_TURN_SECRET_FILE:-$HOME/livetalking-deploy/secrets/turn-auth-secret}"
CONF_FILE="$HOME/livetalking-deploy/turnserver.conf"

echo "==> [1/5] 准备 TURN 共享密钥（只存本机文件，不入库）"
mkdir -p "$(dirname "$SECRET_FILE")"
if [ ! -s "$SECRET_FILE" ]; then
  (umask 077; head -c 32 /dev/urandom | base64 | tr -d '\n' > "$SECRET_FILE")
  echo "    已生成: $SECRET_FILE"
else
  echo "    复用已有密钥: $SECRET_FILE"
fi
SECRET="$(cat "$SECRET_FILE")"

echo "==> [2/5] 生成 coturn 配置（密钥写文件，不进 docker 命令行，避免 ps 泄露）"
# 不写 listening-ip 时 coturn 可能只挑到 ::1，公网访问不到；
# 也不能用 hostname -I 的第一个地址（可能是 ConnectX 高速网卡的 10.x），这里取默认路由出口 IP
HOST_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}' | head -1)"
: "${TURN_EXTERNAL_IP:=$HOST_IP}"
umask 077
cat > "$CONF_FILE" <<EOF
listening-port=$TURN_PORT
listening-ip=$HOST_IP
listening-ip=127.0.0.1
relay-ip=$HOST_IP
external-ip=$TURN_EXTERNAL_IP
realm=$TURN_REALM
fingerprint
lt-cred-mech
use-auth-secret
static-auth-secret=$SECRET
no-multicast-peers
min-port=49152
max-port=65535
no-cli
EOF
echo "    已写入: $CONF_FILE"

echo "==> [3/5] 启动 coturn 容器（host 网络）"
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$TURN_CONTAINER"; then
  docker rm -f "$TURN_CONTAINER" >/dev/null
fi
# 配置文件是 600（含密钥），容器内默认非 root 读不到会退回"无配置"启动，因此显式用 root 运行
docker run -d --name "$TURN_CONTAINER" --network host --restart unless-stopped --user root \
  -v "$CONF_FILE":/etc/coturn/turnserver.conf:ro \
  coturn/coturn -c /etc/coturn/turnserver.conf >/dev/null
sleep 3
docker ps --filter "name=$TURN_CONTAINER" --format '    {{.Names}}: {{.Status}}'
if docker logs "$TURN_CONTAINER" 2>&1 | grep -q "Cannot find config file"; then
  echo "    错误: 容器内未加载到 $CONF_FILE（权限或路径问题）" >&2
  exit 1
fi
ss -ltn 2>/dev/null | grep ":$TURN_PORT" | sed 's/^/    监听 /' || echo "    警告: $TURN_PORT 未监听"

echo "==> [4/5] 给 LiveTalking 打补丁（/api/turn 签发临时凭据 + 前端使用 TURN）"
"$VENV/bin/python" - "$APP_DIR" <<'PY'
import os, sys, re

app_dir = sys.argv[1]

# ---------- 1. 服务端：/api/turn ----------
routes = os.path.join(app_dir, "server", "routes.py")
src = open(routes, encoding="utf-8").read()
if "turn_credentials" in src:
    print("    已存在 /api/turn，跳过")
else:
    src = src.replace(
        "import json\nimport asyncio\n",
        "import json\nimport asyncio\nimport time\nimport base64\nimport hashlib\nimport hmac\nimport os\n",
        1,
    )
    handler = '''

async def turn_credentials(request):
    """为浏览器签发 TURN 临时凭据（HMAC-SHA1），密钥只从本机文件读取"""
    secret_file = os.getenv("LOCAL_TURN_SECRET_FILE", "")
    if not secret_file or not os.path.isfile(secret_file):
        return json_error("turn secret file not configured")
    try:
        secret = open(secret_file, "r", encoding="utf-8").read().strip()
    except Exception as e:  # noqa: BLE001
        return json_error("read turn secret failed: %s" % e)

    ttl = int(os.getenv("LOCAL_TURN_TTL", "3600"))
    username = "%d:livetalking" % (int(time.time()) + ttl)
    credential = base64.b64encode(
        hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    urls = os.getenv("LOCAL_TURN_URLS", "")
    if not urls:
        host = request.headers.get("Host") or request.host
        urls = "turn:%s:%s?transport=tcp" % (
            host.split(":")[0], os.getenv("LOCAL_TURN_PORT", "3478"))

    return json_ok(data={
        "iceServers": [{"urls": urls.split(","), "username": username, "credential": credential}],
        "ttl": ttl,
    })


def setup_routes(app):'''
    src = src.replace("\ndef setup_routes(app):", handler, 1)
    src = src.replace(
        '    app.router.add_get("/api/ping", ping)',
        '    app.router.add_get("/api/ping", ping)\n    app.router.add_get("/api/turn", turn_credentials)',
        1,
    )
    open(routes, "w", encoding="utf-8").write(src)
    print("    已加入 /api/turn ->", routes)

# ---------- 2. 前端：加载器 ----------
loader = '''/* 从本机 /api/turn 拉取 TURN 临时凭据；失败则沿用原有 STUN 配置 */
(function () {
    try {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/turn', false);
        xhr.send();
        if (xhr.status === 200) {
            var body = JSON.parse(xhr.responseText);
            window.__LT_TURN__ = (body && body.data) ? body.data : null;
        }
    } catch (e) {
        window.__LT_TURN__ = null;
    }
})();
'''
loader_path = os.path.join(app_dir, "web", "turn.js")
open(loader_path, "w", encoding="utf-8").write(loader)
print("    已写入前端加载器 ->", loader_path)

# ---------- 3. 前端：注入 iceServers（优先 TURN，其次才退回原 STUN） ----------
MARK = "__LT_TURN_V2__"
v2_tpl = (
    "        if (window.__LT_TURN__) {\n"
    "            // %s\n"
    "            config.iceServers = window.__LT_TURN__.iceServers;\n"
    "            config.iceTransportPolicy = 'relay';\n"
    "        } else {\n"
    "            config.iceServers = %s;\n"
    "        }"
)

def patch_js(path, old, stun_default, insert_loader, rollback):
    """把原来的 iceServers 赋值替换成"有 TURN 就强制 relay"的版本"""
    if not os.path.isfile(path):
        return
    s = open(path, encoding="utf-8").read()
    if MARK in s:
        print("    已是最新版，跳过:", os.path.basename(path))
        return
    if rollback and rollback in s:                 # 回滚旧版注入，保证幂等可重跑
        s = s.replace(rollback, old, 1)
    if old not in s:
        print("    未匹配，跳过:", os.path.basename(path))
        return
    new = v2_tpl % (MARK, stun_default)
    s = s.replace(old, new, 1)
    if insert_loader:
        s = loader + "\n" + s
    open(path, "w", encoding="utf-8").write(s)
    print("    已注入 TURN 配置 ->", os.path.basename(path))

html_old = "        config.iceServers = [{ urls: 'stun:stun.l.google.com:19302' }];"
html_v1 = (
    "        config.iceServers = (window.__LT_TURN__ && window.__LT_TURN__.iceServers)\n"
    "            ? window.__LT_TURN__.iceServers : [{ urls: 'stun:stun.l.google.com:19302' }];\n"
    "        if (window.__LT_TURN__) { config.iceTransportPolicy = 'relay'; }"
)
js_old = "        config.iceServers = [{ urls: ['stun:stun.l.google.com:19302'] }];"
js_v1 = (
    "        config.iceServers = (window.__LT_TURN__ && window.__LT_TURN__.iceServers)\n"
    "            ? window.__LT_TURN__.iceServers : [{ urls: ['stun:stun.l.google.com:19302'] }];\n"
    "        if (window.__LT_TURN__) { config.iceTransportPolicy = 'relay'; }"
)

web = os.path.join(app_dir, "web")
for name, old, stun_default, ins, rb in (
    ("client.js", js_old, "[{ urls: ['stun:stun.l.google.com:19302'] }]", True, js_v1),
    ("index.html", html_old, "[{ urls: 'stun:stun.l.google.com:19302' }]", False, html_v1),
    ("index-en.html", html_old, "[{ urls: 'stun:stun.l.google.com:19302' }]", False, html_v1),
    ("index-whep.html", html_old, "[{ urls: 'stun:stun.l.google.com:19302' }]", False, html_v1),
):
    patch_js(os.path.join(web, name), old, stun_default, ins, rb)

# 官方页面把 iceServers 包在"是否使用 STUN"复选框里，未勾选时 TURN 也不生效；
# 这里把条件改成"有 TURN 就用"，避免演示时因为没勾复选框而退化成无法连接的直连/STUN
COND_OLD = "if (document.getElementById('use-stun')?.checked) {"
COND_NEW = "if (window.__LT_TURN__ || document.getElementById('use-stun')?.checked) {  // __LT_TURN_V3__"
for name in ("client.js", "index.html", "index-en.html", "index-whep.html"):
    p = os.path.join(web, name)
    if not os.path.isfile(p):
        continue
    s = open(p, encoding="utf-8").read()
    if "__LT_TURN_V3__" in s:
        continue
    if COND_OLD in s:
        open(p, "w", encoding="utf-8").write(s.replace(COND_OLD, COND_NEW, 1))
        print("    已无条件启用 TURN ->", name)

# html 需显式引入加载器
for name in ("index.html", "index-en.html", "index-whep.html", "webrtcapi.html", "webrtcapi-asr.html"):
    p = os.path.join(web, name)
    if not os.path.isfile(p):
        continue
    s = open(p, encoding="utf-8").read()
    if "turn.js" in s:
        continue
    if "</head>" in s:
        s = s.replace("</head>", '    <script src="/turn.js"></script>\n</head>', 1)
        open(p, "w", encoding="utf-8").write(s)
        print("    已引入 turn.js ->", name)
PY

echo "==> [5/5] 重启 LiveTalking 使补丁生效"
bash "$BASE_DIR/stop.sh"
sleep 3
bash "$BASE_DIR/03_run.sh" | sed 's/^/    /'

echo
echo "==> 完成。公网需要放通：TCP $TURN_PORT（TURN）+ TCP ${PORT}（页面/信令）"
echo "==> 本机验证可走 SSH 隧道：ssh -L 18010:127.0.0.1:${PORT} -L 13478:127.0.0.1:${TURN_PORT} <host>"
echo "    然后浏览器打开 http://127.0.0.1:18010/index.html，并设置 LOCAL_TURN_URLS=turn:127.0.0.1:13478?transport=tcp"
