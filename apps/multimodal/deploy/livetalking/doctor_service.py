#!/usr/bin/env python3
"""医生端控制台服务：会话列表 / 文字版对话内容 / 医生参考版总结。

数据来源（全部在本机，不出网）：

1. `consult_recorder` 落盘的问诊记录（`DOCTOR_RECORD_DIR/<sessionid>.jsonl`），
   由 LiveTalking 的 `llm.py` 在每一轮问诊时写入 —— 对话正文与总结都从这里来；
2. LiveTalking 的 `/api/admin/sessions`（127.0.0.1 回环）判断会话是否仍然在线，
   拉不到（服务未启动/接口缺失）就退化为按文件最后更新时间判断。

对外接口（同时静态托管 `web/doctor.html`）：

    GET  /health                      服务与数据源自检
    GET  /api/doctor/sessions         会话列表（筛选 status / 关键词 q）
    GET  /api/doctor/sessions/<id>    单个会话：HEADER 元信息 + messages + summary
    GET  /api/doctor/sessions/<id>/highlights
                                      阶段三 judge 标出的「重点」（只读；还没生成时 ready=false）

安全边界：只读本机磁盘与回环接口；不做任何诊断判断，也不修改问诊内容。
"""
import json
import os
import time
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

RECORD_DIR = os.path.expanduser(
    os.getenv("DOCTOR_RECORD_DIR", "~/livetalking-logs/consultations"))
LT_ADMIN_URL = os.getenv("DOCTOR_LT_ADMIN_URL", "http://127.0.0.1:8010/api/admin/sessions")
LT_CACHE_TTL = float(os.getenv("DOCTOR_LT_CACHE_TTL", "3"))
# 超过多久没有新消息就不再算"正在问诊"（默认 15 分钟）。
# LiveTalking 120s 就回收空闲会话，在线与否以 /api/admin/sessions 为准，
# 这个窗口主要兜住"服务重启过、还不在线但没有总结"的中间态。
ACTIVE_WINDOW = float(os.getenv("DOCTOR_ACTIVE_WINDOW", "900"))
LIST_LIMIT = int(os.getenv("DOCTOR_LIST_LIMIT", "200"))
# 阶段三 judge 的自动判断服务（emotion-judge-watch）在问诊结束、大模型空闲时，
# 把每次问诊的「重点」写成 <sessionid>.judge.json 放在这里；本服务只读、不触发判断。
JUDGE_DIR = os.path.expanduser(
    os.getenv("DOCTOR_JUDGE_DIR", "~/spark-Hackson/outputs/judge/consult"))
_HIT_FIELDS = ("t", "turn_index", "text", "question", "group", "group_label",
               "importance", "risk", "labels", "evidence", "source")

_LT_CACHE = {"at": 0.0, "data": {}}
app = FastAPI(title="doctor-console")
# 页面可能从另一个端口打开（如 LiveTalking 的 8010），同源策略会被触发；
# 该服务只在本机/内网使用，故放开跨域读取。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


_WEB_DIR_CACHE = [""]


def _web_dir() -> str:
    """静态页面目录：优先环境变量，其次与本文件同级的 ../web 或 ./web。"""
    global _WEB_DIR_CACHE
    if _WEB_DIR_CACHE[0]:
        return _WEB_DIR_CACHE[0]
    here = os.path.dirname(os.path.abspath(__file__))
    env = os.getenv("DOCTOR_WEB_DIR", "").strip()
    for cand in (env, os.path.join(os.path.dirname(here), "web"), os.path.join(here, "web")):
        if cand and os.path.isfile(os.path.join(cand, "doctor.html")):
            _WEB_DIR_CACHE[0] = cand
            return cand
    raise HTTPException(500, "找不到 doctor.html，请用 DOCTOR_WEB_DIR 指定页面目录（web/）")


def _recorder_disabled() -> bool:
    return os.getenv("DOCTOR_RECORD", "1") == "0"


def _iter_session_files():
    if not os.path.isdir(RECORD_DIR):
        return []
    out = []
    for name in os.listdir(RECORD_DIR):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(RECORD_DIR, name)
        if os.path.isfile(path):
            out.append((name[:-len(".jsonl")], path))
    return out


def _lt_sessions() -> dict:
    """在线会话表 sessionid -> idle 秒。失败返回空表，不影响列表本身。"""
    now = time.time()
    if now - _LT_CACHE["at"] < LT_CACHE_TTL:
        return _LT_CACHE["data"]
    data = {}
    try:
        # 显式绕过代理：接口在同机回环，走 env 里的代理会超时
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(LT_ADMIN_URL, timeout=2.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        rows = ((payload or {}).get("data") or {}).get("sessions") or []
        data = {row.get("sessionid", ""): row.get("idle")
                for row in rows if row.get("sessionid")}
    except Exception:  # noqa: BLE001 - 拿不到在线状态就退化，不报错
        data = {}
    _LT_CACHE.update(at=now, data=data)
    return data


def _read_events(path: str):
    events = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue  # 写了一半的行：跳过，不影响其余内容
    except OSError:
        return []
    return events


def _session_brief(sid: str, path: str, online: dict):
    events = _read_events(path)
    now = time.time()
    brief = {
        "id": sid,
        "title": sid[:8],
        # 没有任何事件（刚连上还没说话）也用文件时间兜底
        "started_at": events[0].get("t") if events else os.path.getmtime(path),
        "updated_at": events[-1].get("t") if events else os.path.getmtime(path),
        "ended_at": None,
        "turns": 0,
        "summary_ready": False,
        "provider": "",
        "preview": "",
        "online": sid in online,
        "idle": online.get(sid),
    }
    last_text = ""
    for ev in events:
        kind = ev.get("kind")
        if kind == "user":
            brief["turns"] += 1
            if ev.get("text"):
                last_text = "患者：" + ev["text"]
        elif kind == "assistant":
            if ev.get("provider"):
                brief["provider"] = ev["provider"]
            if ev.get("text") and not last_text.startswith("助手"):
                last_text = "助手：" + ev["text"]
        elif kind == "summary":
            brief["ended_at"] = ev.get("t")
            brief["summary_ready"] = bool((ev.get("doctor") or "").strip())
            if ev.get("provider"):
                brief["provider"] = ev["provider"]
            last_text = "已生成预问诊记录"
    brief["preview"] = last_text[:60]
    if brief["ended_at"]:
        status = "ended"
    elif brief["online"]:
        status = "live"
    elif now - brief["updated_at"] <= ACTIVE_WINDOW:
        status = "active"
    else:
        status = "stale"
    brief["status"] = status
    return brief


def _rank(item) -> int:
    return {"live": 0, "active": 1, "stale": 2, "ended": 3}.get(item["status"], 9)


@app.get("/health")
def health():
    files = _iter_session_files()
    return {
        "ok": True,
        "record_dir": RECORD_DIR,
        "record_dir_exists": os.path.isdir(RECORD_DIR),
        "record_enabled": not _recorder_disabled(),
        "sessions": len(files),
        "web_dir": _WEB_DIR_CACHE[0] or "(未指定)",
        "judge_dir": JUDGE_DIR,
        "judge_dir_exists": os.path.isdir(JUDGE_DIR),
        "live_talking_reachable": bool(_lt_sessions()),
    }


@app.get("/api/doctor/sessions")
def list_sessions(status: str = "", q: str = ""):
    online = _lt_sessions()
    items = []
    for sid, path in _iter_session_files():
        items.append(_session_brief(sid, path, online))
    # 在线但还没有问诊记录的会话也要能看到（刚点开始、还没说话）
    for sid in online:
        if sid in {i["id"] for i in items}:
            continue
        items.append({
            "id": sid, "title": sid[:8], "started_at": time.time(),
            "updated_at": time.time(), "ended_at": None, "turns": 0,
            "summary_ready": False, "provider": "", "preview": "已连接，暂无对话内容",
            "online": True, "idle": online.get(sid), "status": "live",
        })

    if status:
        items = [i for i in items if i["status"] == status]
    q = (q or "").strip()
    if q:
        ql = q.lower()
        items = [i for i in items
                 if ql in i["id"].lower() or ql in i["preview"].lower()]

    items.sort(key=lambda i: (_rank(i), -i["updated_at"]))
    return {
        "items": items[:LIST_LIMIT],
        "total": len(items),
        "active_window_sec": ACTIVE_WINDOW,
        "generated_at": time.time(),
    }


@app.get("/api/doctor/sessions/{sid}")
def get_session(sid: str):
    if "/" in sid or "\\" in sid or sid.startswith("."):
        raise HTTPException(400, "非法会话标识")
    path = os.path.join(RECORD_DIR, "%s.jsonl" % sid)
    online = _lt_sessions()
    messages = []
    summary = None
    if os.path.isfile(path):
        for ev in _read_events(path):
            kind = ev.get("kind")
            if kind == "user":
                messages.append({"role": "user", "text": ev.get("text", ""),
                                 "t": ev.get("t"), "source": ev.get("source", "")})
            elif kind == "assistant":
                messages.append({"role": "assistant", "text": ev.get("text", ""),
                                 "t": ev.get("t"), "provider": ev.get("provider", "")})
            elif kind == "summary":
                summary = {"doctor": ev.get("doctor", ""), "patient": ev.get("patient", ""),
                           "provider": ev.get("provider", ""), "t": ev.get("t")}
    else:
        raise HTTPException(404, "会话不存在或已清除")
    brief = _session_brief(sid, path, online)
    return {"session": brief, "messages": messages, "summary": summary}


@app.get("/api/doctor/sessions/{sid}/highlights")
def get_highlights(sid: str):
    """阶段三 judge 对这次问诊标出的「重点」（值得医生先看的患者回答），只读。

    问诊进行中、大模型忙、或阶段三服务没装时还没有结果，返回 ready=false；
    结果生成之后对话又有更新，返回 stale=true（阶段三会自动重判）。
    每条命中带问诊记录里的事件时间 t，页面靠它跳回对话原句。
    """
    if "/" in sid or "\\" in sid or sid.startswith("."):
        raise HTTPException(400, "非法会话标识")
    path = os.path.join(JUDGE_DIR, "%s.judge.json" % sid)
    if not os.path.isfile(path):
        return {"ready": False, "hits": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"ready": False, "hits": [], "error": "重点结果暂时读不了"}
    record = os.path.join(RECORD_DIR, "%s.jsonl" % sid)
    stale = os.path.isfile(record) and os.path.getmtime(record) > os.path.getmtime(path)
    hits = [{k: h.get(k) for k in _HIT_FIELDS}
            for h in (data.get("hits") or []) if isinstance(h, dict)]
    return {
        "ready": True,
        "stale": stale,
        "hits": hits,
        "generated_at": data.get("generated_at"),
        "review_notice": data.get("review_notice") or "",
        "schema_version": data.get("schema_version") or "",
        "errors": data.get("errors") or 0,
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(_web_dir(), "doctor.html"))


@app.get("/doctor.html")
def page():
    return FileResponse(os.path.join(_web_dir(), "doctor.html"))


@app.get("/doctor.css")
def css():
    return FileResponse(os.path.join(_web_dir(), "doctor.css"),
                        media_type="text/css; charset=utf-8")


@app.get("/doctor.js")
def js():
    return FileResponse(os.path.join(_web_dir(), "doctor.js"),
                        media_type="application/javascript; charset=utf-8")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("DOCTOR_HOST", "127.0.0.1"),
                port=int(os.getenv("DOCTOR_PORT", "8110")))
