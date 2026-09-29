#!/usr/bin/env python3
"""问诊转写落盘：把每一轮对话按 sessionid 追加写入 JSONL，供医生端控制台读取。

为什么放在这里而不是 LiveTalking 的服务层：`llm.py` 是唯一必经之处——
患者的提问（`llm_response` 的入参）和模型的回答（流式 `notify` 的正文）都从这里经过；
而 LiveTalking 本身把会话状态放在进程内存里，空闲 120s 就被回收，问诊内容随会话消失。

落盘位置：`$DOCTOR_RECORD_DIR/<sessionid>.jsonl`（默认 `~/livetalking-logs/consultations`）。
每行一个事件，文件顺序即时间顺序：

    {"t": 1690000000.1, "kind": "user",      "text": "..."}
    {"t": ...,          "kind": "assistant", "text": "...", "provider": "openclaw"}
    {"t": ...,          "kind": "summary",   "doctor": "...", "patient": "...", "provider": "openclaw"}

失败策略：任何异常都吞掉——记录是为了给医生看，绝不能反过来拖垮数字人作答。
"""
import json
import os
import re
import threading

_LOCK = threading.Lock()
DEFAULT_DIR = "~/livetalking-logs/consultations"

# 与前端 web/triage.js 的 splitSummary() 保持一致：
# agent 输出的是一整篇 Markdown，用标题区分「医生参考版」和「患者核对版」。
# 注意必须带 MULTILINE：整篇小结是多行文本，`^` 默认只匹配串首，
# 否则「## 医生参考版」出现在正文中间行时会被误判成普通回复。
_DOCTOR_HEADING = re.compile(r"^\s*#{1,6}\s*医生(?:参考|版)", re.MULTILINE)
_PATIENT_HEADING = re.compile(r"^\s*#{1,6}\s*患者核对版", re.MULTILINE)
_OTHER_HEADING = re.compile(r"^\s*#{1,6}\s+\S|^\s*\*\*保存位置", re.MULTILINE)


def enabled() -> bool:
    """总开关：DOCTOR_RECORD=0 可整体关闭落盘（便于排障或隐私演练）。"""
    return os.getenv("DOCTOR_RECORD", "1") != "0"


def record_dir() -> str:
    return os.path.expanduser(os.getenv("DOCTOR_RECORD_DIR", DEFAULT_DIR))


def split_summary(text):
    """把连续的总结 Markdown 拆成 (医生参考版, 患者核对版)。"""
    cur = "pre"
    doctor = []
    patient = []
    for line in str(text or "").split("\n"):
        if _PATIENT_HEADING.match(line):
            cur = "patient"
            continue
        if _DOCTOR_HEADING.match(line):
            cur = "doctor"
            continue
        if _OTHER_HEADING.match(line):
            cur = "other"
        if cur == "patient":
            patient.append(line)
        elif cur == "doctor":
            doctor.append(line)
    return "\n".join(doctor).strip(), "\n".join(patient).strip()


def has_summary_heading(text) -> bool:
    return bool(_DOCTOR_HEADING.search(str(text or ""))
                or _PATIENT_HEADING.search(str(text or "")))


def _safe_sid(sessionid) -> str:
    """会话 ID 只允许安全字符（前端/服务端可能带上任意串，不能直接拼进文件路径）。

    合法：[A-Za-z0-9_-]{8,64}；不合法的一律映射成哈希短码，保证可写且唯一。
    """
    import hashlib

    sessionid = str(sessionid or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", sessionid):
        return sessionid
    return "sid-" + hashlib.sha256(sessionid.encode("utf-8")).hexdigest()[:16]


def _append(sessionid, event):
    if not sessionid or not enabled():
        return
    import time

    event = dict(event)
    event.setdefault("t", time.time())
    path = os.path.join(record_dir(), "%s.jsonl" % _safe_sid(sessionid))
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # 问诊内容是敏感数据：目录与文件都只给属主读写
        try:
            os.chmod(os.path.dirname(path), 0o700)
        except OSError:
            pass
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            os.chmod(path, 0o600)
        except Exception as e:  # noqa: BLE001
            print("[consult-recorder] 写入失败(忽略): %s" % e, flush=True)


def record_user(sessionid, text, source="voice"):
    # 「结束问诊」指令（"问诊结束，请生成预问诊记录。"）不是患者的陈述，
    # 由调用方决定是否写入；这里只负责落盘。
    text = (text or "").strip()
    if text:
        _append(sessionid, {"kind": "user", "text": text, "source": source})


def record_assistant(sessionid, text, provider=""):
    text = (text or "").strip()
    if text:
        _append(sessionid, {"kind": "assistant", "text": text, "provider": provider})


def record_summary(sessionid, text, provider=""):
    doctor, patient = split_summary(text)
    _append(sessionid, {
        "kind": "summary",
        "doctor": doctor,
        "patient": patient,
        "provider": provider,
        "has_heading": has_summary_heading(text),
    })


def record_reply(sessionid, text, provider="", silent=False):
    """一轮回复落盘（silent 仅用于日志定位，判定依据是正文里的标题）。

    只要正文里出现了「医生参考版 / 患者核对版」标题就按小结存、并拆成两份；
    这样即使前端的 silent 标记没传过来，医生端依然能拿到结构化小结。
    """
    text = (text or "").strip()
    if not text:
        return
    if has_summary_heading(text):
        record_summary(sessionid, text, provider)
    else:
        record_assistant(sessionid, text, provider)
