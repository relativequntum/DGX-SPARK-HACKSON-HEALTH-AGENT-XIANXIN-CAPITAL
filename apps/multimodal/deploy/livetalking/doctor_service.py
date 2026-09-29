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
                                      阶段三 judge 标出的「重点」（只读；还没生成时 ready=false），
                                      并附每条患者回答的摄像头同期观察（observe_segments）
    POST /api/observe/<id>            患者页「摄像头观察」上传的关键点数值（唯一的写接口；DOCTOR_OBSERVE=0 关闭）

安全边界：除 /api/observe 追加写关键点数值外只读本机磁盘与回环接口；不存图像，不做任何诊断判断，也不修改问诊内容。
"""
import json
import math
import os
import re
import threading
import time
import urllib.request

from fastapi import FastAPI, HTTPException, Request
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
# 摄像头观察：患者页只上传关键点数值（blendshape 分数、头姿矩阵、姿态点），追加写到这里；
# 阶段三 emotion-judge-watch 在问诊结束后读它，生成 <JUDGE_DIR>/<会话>.observe.json
OBS_DIR = os.path.expanduser(os.getenv("DOCTOR_OBS_DIR", "~/livetalking-logs/observations"))
OBS_MAX_BODY = 64 * 1024            # 一批请求体上限（约 2 秒、10 帧，实际十几 KB）
OBS_MAX_FRAMES = 50                 # 一批最多帧数
OBS_MAX_FILE = 20 * 1024 * 1024     # 单个会话的 frames 文件上限，超过返回 413
OBS_MAX_TOTAL = 2 * 1024 * 1024 * 1024   # 观察目录所有会话合计上限：换着会话编号发也写不满 Spark 的磁盘
OBS_MAX_AGE_MS = 60_000             # 一帧的采集时刻最多比发送时刻早 60 秒（只用浏览器时钟的差值，不怕两边时钟不齐）
# 与 apps/emotion/face_body/live.py、apps/multimodal/web/camera-metrics.js 三处一致（有测试核对）；
# 本服务的 venv 没有 numpy，不能 import 阶段三，所以复制一份
CAM_BLENDSHAPES = (
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookUpLeft", "eyeLookUpRight", "eyeLookDownLeft", "eyeLookDownRight",
    "eyeBlinkLeft", "eyeBlinkRight",
    "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "browDownLeft", "browDownRight",
    "cheekSquintLeft", "cheekSquintRight", "eyeSquintLeft", "eyeSquintRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthPressLeft", "mouthPressRight", "jawOpen",
)
_CAM_SET = frozenset(CAM_BLENDSHAPES)
_SID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")   # 与 consult_recorder._safe_sid 同一规则：文件名与问诊记录对齐
_OBS_FIELDS = ("t", "interval", "frames", "face_status", "body_status", "gaze_away_ratio", "blink_count",
               "blink_per_min", "head_motion_deg_per_frame", "hand_face_ratio", "body_motion_x1000")
_OBS_MEDIAN_KEYS = ("gaze_away_ratio", "blink_per_min", "head_motion_deg_per_frame",
                    "hand_face_ratio", "body_motion_x1000")
_OBS_LOCK = threading.Lock()

_LT_CACHE = {"at": 0.0, "data": {}}
app = FastAPI(title="doctor-console")
# 页面可能从另一个端口打开（如 LiveTalking 的 8010），同源策略会被触发；
# 该服务只在本机/内网使用，故放开跨域读取。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],   # POST 只有 /api/observe：患者页（8010）跨端口上传关键点数值
    allow_headers=["*"],             # 含 Content-Type（application/json 会触发预检）
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


def _observe_enabled() -> bool:
    """总开关：DOCTOR_OBSERVE=0 时不收摄像头观察数据（接口 404，患者页按上传失败处理，问诊不受影响）。"""
    return os.getenv("DOCTOR_OBSERVE", "1") != "0"


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
        "obs_dir": OBS_DIR,
        "obs_dir_exists": os.path.isdir(OBS_DIR),
        "observe_enabled": _observe_enabled(),
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
    obs = _observe_payload(sid)   # 同期观察可能比 judge 先出来：judge 还没好时也照常带上
    path = os.path.join(JUDGE_DIR, "%s.judge.json" % sid)
    if not os.path.isfile(path):
        return dict({"ready": False, "hits": []}, **obs)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict({"ready": False, "hits": [], "error": "重点结果暂时读不了"}, **obs)
    record = os.path.join(RECORD_DIR, "%s.jsonl" % sid)
    stale = os.path.isfile(record) and os.path.getmtime(record) > os.path.getmtime(path)
    hits = [{k: h.get(k) for k in _HIT_FIELDS}
            for h in (data.get("hits") or []) if isinstance(h, dict)]
    for h in hits:  # 每条命中附上同一句回答的同期观察（按问诊记录的事件时间 t 对齐）
        h["observe"] = _match_segment(h.get("t"), obs["observe_segments"])
    return dict({
        "ready": True,
        "stale": stale,
        "hits": hits,
        "generated_at": data.get("generated_at"),
        "review_notice": data.get("review_notice") or "",
        "schema_version": data.get("schema_version") or "",
        "errors": data.get("errors") or 0,
    }, **obs)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _observe_payload(sid: str) -> dict:
    """<JUDGE_DIR>/<sid>.observe.json → 白名单字段；camera = 这场开过摄像头（有 frames，或 observe 里有帧）。"""
    data = None
    try:
        with open(os.path.join(JUDGE_DIR, "%s.observe.json" % sid), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = None
    segments = [{k: s.get(k) for k in _OBS_FIELDS}
                for s in ((data or {}).get("segments") or []) if isinstance(s, dict) and _num(s.get("t"))]
    medians = (data or {}).get("medians")
    medians = medians if isinstance(medians, dict) else {}
    frames = os.path.join(OBS_DIR, "%s.frames.jsonl" % sid)
    return {
        "camera": os.path.isfile(frames) or bool(data and _num(data.get("camera_frames"))
                                                  and data["camera_frames"] > 0),
        "observe_ready": data is not None,
        "observe_segments": segments,
        "observe_medians": {k: medians.get(k) for k in _OBS_MEDIAN_KEYS},
    }


def _match_segment(t, segments):
    if not _num(t):
        return None
    for seg in segments:
        if abs(seg["t"] - t) < 0.5:
            return seg
    return None


def _check_frame(fr) -> bool:
    """一帧的白名单校验：{"ct": 毫秒, "f": null | {"bs": {26 个有限数}, "m": [16 个有限数]}, "p": null | 25×[x, y, 可见度]}。"""
    if not isinstance(fr, dict) or set(fr) - {"ct", "f", "p"} or not _num(fr.get("ct")):
        return False
    f, p = fr.get("f"), fr.get("p")
    if f is not None:
        if not isinstance(f, dict) or set(f) != {"bs", "m"}:
            return False
        bs, m = f["bs"], f["m"]
        if not isinstance(bs, dict) or set(bs) != _CAM_SET or not all(_num(v) for v in bs.values()):
            return False
        if not isinstance(m, list) or len(m) != 16 or not all(_num(v) for v in m):
            return False
    if p is not None:
        if not isinstance(p, list) or len(p) != 25:
            return False
        if not all(isinstance(q, list) and len(q) == 3 and all(_num(v) for v in q) for q in p):
            return False
    return True


async def _read_body(request: Request, limit: int):
    """读请求体，超过 limit 就停下返回 None：先看 Content-Length，再边读边数，超大请求体不会整个读进内存。"""
    try:
        if int(request.headers.get("content-length") or 0) > limit:
            return None
    except ValueError:
        pass
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > limit:
            return None
    return bytes(buf)


def _obs_total() -> int:
    """观察目录里所有 frames 文件的总字节数。"""
    total = 0
    try:
        with os.scandir(OBS_DIR) as it:
            for entry in it:
                if entry.name.endswith(".frames.jsonl") and entry.is_file():
                    total += entry.stat().st_size
    except OSError:
        pass
    return total


@app.post("/api/observe/{sid}")
async def observe(sid: str, request: Request):
    """患者页摄像头观察的一批关键点数值 → 追加写 <OBS_DIR>/<sid>.frames.jsonl（目录 700、文件 600）。

    整批校验，任何一处不合格整批丢弃（400）；时间换成服务器秒：t = 收到时刻 - (sent_ct - ct) / 1000，
    只用浏览器时钟的差值，两边时钟差多少都不影响。不存图像，也不保存浏览器时间 ct。"""
    if not _observe_enabled():
        raise HTTPException(404, "摄像头观察已关闭")
    if not _SID_RE.fullmatch(sid or ""):
        raise HTTPException(400, "非法会话标识")
    body = await _read_body(request, OBS_MAX_BODY)
    recv = time.time()
    if body is None:
        raise HTTPException(413, "请求体过大")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "不是 JSON")
    if not isinstance(data, dict) or data.get("v") != "cam-0.1" or not _num(data.get("sent_ct")):
        raise HTTPException(400, "格式不对")
    frames = data.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= OBS_MAX_FRAMES:
        raise HTTPException(400, "frames 数量不对")
    if not all(_check_frame(fr) for fr in frames):
        raise HTTPException(400, "帧数据不合格")
    ages = [data["sent_ct"] - fr["ct"] for fr in frames]
    if not all(0 <= a <= OBS_MAX_AGE_MS for a in ages):
        raise HTTPException(400, "帧时间不对")
    lines = "".join(json.dumps({"t": round(recv - a / 1000.0, 3), "f": fr.get("f"), "p": fr.get("p")},
                               separators=(",", ":")) + "\n" for a, fr in zip(ages, frames)).encode("utf-8")
    path = os.path.join(OBS_DIR, "%s.frames.jsonl" % sid)
    with _OBS_LOCK:
        os.makedirs(OBS_DIR, exist_ok=True)
        try:
            os.chmod(OBS_DIR, 0o700)
        except OSError:
            pass
        size = os.path.getsize(path) if os.path.isfile(path) else 0
        if size + len(lines) > OBS_MAX_FILE:
            raise HTTPException(413, "本次问诊的观察数据已达上限")
        if _obs_total() + len(lines) > OBS_MAX_TOTAL:
            raise HTTPException(413, "观察数据总量已达上限")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, lines)
        finally:
            os.close(fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return {"ok": True, "accepted": len(frames)}


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
