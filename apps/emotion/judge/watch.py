# -*- coding: utf-8 -*-
"""自动判断：盯着数字人的问诊记录目录，问诊结束后、大模型空闲时跑 judge，
结果写成医生控制台「重点」页签读的文件（`<out-dir>/<会话>.judge.json` 与 `.judge.html`）。

    python -m apps.emotion.judge.watch            # 常驻；Spark 上由 systemd 用户服务 emotion-judge-watch 拉起
    python -m apps.emotion.judge.watch --once     # 扫一遍就退出

什么时候判断：记录里出现 summary（患者点了结束问诊），或超过 --idle 秒没有新内容；
已有结果且记录没再变就不重复判断；判断期间记录又长了，下一轮再判一次。
怎么不打扰数字人：Spark 上的 llama-server 只有 1 个并发槽。每发一次判断请求前，先看 llama-server
在不在处理请求、数字人有没有在线会话，忙就等，最多等 --max-wait 秒。
隐私：只用本地模型，没有云端选项；日志只写会话编号前 8 位、命中数和耗时，不写对话内容。
全部判断都失败（比如 llama-server 没起来）时不写结果，--retry 秒后或记录变了再试；
部分失败时先写出判到的部分给医生看，--retry 秒后整段重判，判全了才算完。
单条会话出意外（坏文件、磁盘、后端抛了别的异常）只让这一条退避，其余会话照常，进程不退出；日志只写异常类名。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.request

from .__main__ import write_outputs
from .backends.local_openai import LocalOpenAIBackend, resolve_api_key
from .backends.ollama_native import OllamaNativeBackend
from .engine import analyze_session
from .sources import from_consult_record

IDLE_S = 180.0
RETRY_S = 600.0
DEFAULT_LT_ADMIN = "http://127.0.0.1:8010/api/admin/sessions"


def _scan(path: pathlib.Path) -> tuple:
    """(是否已结束, 患者是否说过话)。坏行跳过。"""
    ended = patient = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("kind") == "summary":
            ended = True
        elif event.get("kind") == "user" and str(event.get("text") or "").strip():
            patient = True
    return ended, patient


def _finished(result: pathlib.Path) -> bool:
    """结果文件判全了才算完：errors > 0（部分失败）或读不了、解析不了（比如写了一半）都算没完。
    failures 只在内存里，服务重启后靠这里把重启前的部分失败结果找回来重判。"""
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and not data.get("errors")


def pending_sessions(consult_dir, out_dir, now=None, idle_s: float = IDLE_S, failures=None,
                     retry_s: float = RETRY_S) -> list:
    """需要（重新）判断的 (会话编号, 记录路径)，按文件名排序。
    记在 failures 里的会话（出错或部分失败）即使已有结果，也在 retry_s 后重判；
    不在 failures 里、但结果文件没判全的（重启前的部分失败、写坏的文件），马上重判，之后同样按 failures 退避。"""
    now = time.time() if now is None else now
    consult_dir, out_dir = pathlib.Path(consult_dir), pathlib.Path(out_dir)
    if not consult_dir.is_dir():
        return []
    todo = []
    for path in sorted(consult_dir.glob("*.jsonl")):
        sid = path.stem
        failed = (failures or {}).get(sid)
        try:
            mtime = path.stat().st_mtime
            result = out_dir / f"{sid}.judge.json"
            if not failed and result.is_file() and result.stat().st_mtime >= mtime and _finished(result):
                continue
            if failed and failed[0] == mtime and now - failed[1] < retry_s:
                continue
            ended, patient = _scan(path)
        except OSError:  # 扫描时记录被删、读不了：跳过这一条，别挡住后面的会话
            continue
        if patient and (ended or now - mtime >= idle_s):
            todo.append((sid, path))
    return todo


def run_once(consult_dir, out_dir, backend, now=None, idle_s: float = IDLE_S, keep: int = 10,
             threshold: float = 0.5, failures=None, retry_s: float = RETRY_S) -> list:
    now = time.time() if now is None else now
    failures = {} if failures is None else failures
    out_dir = pathlib.Path(out_dir)
    done = []
    for sid, path in pending_sessions(consult_dir, out_dir, now, idle_s, failures, retry_s):
        started, mtime = time.time(), None
        try:
            mtime = path.stat().st_mtime
            result = analyze_session(from_consult_record(path), backend, keep=keep, threshold=threshold)
            judged = sum(len(t.get("judgments") or {}) for t in result["turns"])
            spent = round(time.time() - started, 1)
            if judged and result["errors"] >= judged:
                failures[sid] = (mtime, now)
                done.append({"session_id": sid, "status": "failed", "errors": result["errors"], "seconds": spent})
                continue
            json_path, html_path = write_outputs(result, out_dir)
            if path.stat().st_mtime != mtime:  # 判断期间记录又长了：把结果时间拨回去，下一轮再判
                for p in (json_path, html_path):
                    os.utime(p, (mtime, mtime))
        except Exception as exc:  # noqa: BLE001 - 一条会话出意外只让它自己退避，不带崩常驻进程
            failures[sid] = (mtime, now)
            done.append({"session_id": sid, "status": "error", "error": type(exc).__name__,
                         "seconds": round(time.time() - started, 1)})  # 只记类名：异常文本可能带对话内容
            continue
        if result["errors"]:  # 部分失败：判到的已写出给医生看，同时记入 failures，retry_s 后整段重判
            failures[sid] = (mtime, now)
        else:
            failures.pop(sid, None)
        done.append({"session_id": sid, "status": "partial" if result["errors"] else "ok",
                     "hits": len(result["hits"]), "risk": sum(1 for h in result["hits"] if h["risk"]),
                     "errors": result["errors"], "seconds": spent})
    return done


class PoliteBackend:
    """每次请求前先等 llama-server 与数字人都空下来（最多 max_wait_s 秒），再交给 inner。"""

    def __init__(self, inner, is_busy, sleep=time.sleep, poll_s: float = 5.0, max_wait_s: float = 600.0) -> None:
        self.inner, self.is_busy, self.sleep = inner, is_busy, sleep
        self.poll_s, self.max_wait_s = poll_s, max_wait_s
        self.source = getattr(inner, "source", "")

    def ask(self, state: dict, questions: dict) -> dict:
        waited = 0.0
        while waited < self.max_wait_s and self.is_busy():
            self.sleep(self.poll_s)
            waited += self.poll_s
        return self.inner.ask(state, questions)


def parse_llama_busy(metrics_text: str) -> bool:
    for line in metrics_text.splitlines():
        if line.startswith(("llamacpp:requests_processing", "llamacpp:requests_deferred")):
            try:
                if float(line.split()[-1]) > 0:
                    return True
            except ValueError:
                continue
    return False


def parse_live_sessions(payload) -> int:
    """LiveTalking /api/admin/sessions 的在线会话数；格式不对算 0。"""
    if not isinstance(payload, dict):
        return 0
    rows = (payload.get("data") or {}).get("sessions") if isinstance(payload.get("data"), dict) else None
    return sum(1 for r in rows or [] if isinstance(r, dict) and r.get("sessionid"))


def make_is_busy(llm_base_url, lt_admin_url, timeout: float = 2.5):
    """llama-server 正在处理请求、或数字人有在线会话，就算忙。读不到的那一路当作不忙。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 都是同机回环，绕开代理
    metrics_url = None
    if llm_base_url:
        base = llm_base_url.rstrip("/")
        metrics_url = (base[:-3] if base.endswith("/v1") else base) + "/metrics"

    def is_busy() -> bool:
        if metrics_url:
            key = resolve_api_key()
            headers = {"Authorization": f"Bearer {key}"} if key and key != "local" else {}
            try:
                with opener.open(urllib.request.Request(metrics_url, headers=headers), timeout=timeout) as resp:
                    if parse_llama_busy(resp.read().decode("utf-8", "replace")):
                        return True
            except Exception:  # noqa: BLE001 - 拿不到就只看另一路
                pass
        if lt_admin_url:
            try:
                with opener.open(lt_admin_url, timeout=timeout) as resp:
                    if parse_live_sessions(json.loads(resp.read().decode("utf-8"))) > 0:
                        return True
            except Exception:  # noqa: BLE001
                pass
        return False

    return is_busy


def describe(item: dict) -> str:
    sid = item["session_id"][:8]
    if item["status"] == "error":
        return f"{sid} 判断出错：{item['error']}，稍后重试（{item['seconds']}s）"
    if item["status"] == "failed":
        return f"{sid} 判断失败：{item['errors']} 次后端出错，稍后重试（{item['seconds']}s）"
    retry = "，已写出判到的部分，稍后重判" if item["status"] == "partial" else ""
    return (f"{sid} 判断完成：{item['hits']} 条命中，其中风险线索 {item['risk']} 条，"
            f"{item['errors']} 次出错{retry}（{item['seconds']}s）")


def log(message: str) -> None:
    print(f"[watch] {time.strftime('%m-%d %H:%M:%S')} {message}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    env_out = os.environ.get("EMOTION_OUT")
    p = argparse.ArgumentParser(prog="python -m apps.emotion.judge.watch",
                                description="问诊结束后自动跑 judge，给医生控制台的「重点」页签用（只用本地模型）")
    p.add_argument("--consult-dir", default=os.environ.get("CONSULT_DIR") or "~/livetalking-logs/consultations")
    p.add_argument("--out-dir", default=os.path.join(env_out, "judge", "consult") if env_out else "outputs/judge/consult")
    p.add_argument("--backend", choices=("openai", "ollama"), default="openai",
                   help="openai = Spark 上阶段二的 llama-server（默认）；ollama = 开发机")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--host")
    p.add_argument("--timeout", type=float, default=120)
    p.add_argument("--interval", type=float, default=30.0, help="扫目录的间隔（秒）")
    p.add_argument("--idle", type=float, default=IDLE_S, help="没有 summary 时，记录多久没动静就算结束（秒）")
    p.add_argument("--max-wait", type=float, default=600.0, help="大模型或数字人忙时最多等多久（秒）")
    p.add_argument("--retry", type=float, default=RETRY_S, help="出错、全部或部分失败后多久再试（秒）")
    p.add_argument("--lt-admin-url", default=os.environ.get("LT_ADMIN_URL") or DEFAULT_LT_ADMIN)
    p.add_argument("--once", action="store_true", help="扫一遍就退出")
    return p


def main(argv=None, backend=None, sleep=time.sleep) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    consult_dir = pathlib.Path(args.consult_dir).expanduser()
    out_dir = pathlib.Path(args.out_dir).expanduser()
    if backend is None:
        if args.backend == "openai":
            local = LocalOpenAIBackend(base_url=args.base_url, model=args.model, timeout=args.timeout)
            is_busy = make_is_busy(local.base_url, args.lt_admin_url)
        else:
            local = OllamaNativeBackend(host=args.host, model=args.model, timeout=args.timeout)
            is_busy = make_is_busy(None, args.lt_admin_url)
        backend = PoliteBackend(local, is_busy, max_wait_s=args.max_wait)
    log(f"盯 {consult_dir} → {out_dir}；来源 {getattr(backend, 'source', '')}；"
        f"结束或静默 {args.idle:.0f}s 后判断")
    failures: dict = {}
    while True:
        ok = True
        try:
            for item in run_once(consult_dir, out_dir, backend, idle_s=args.idle, failures=failures,
                                 retry_s=args.retry):
                log(describe(item))
        except Exception as exc:  # noqa: BLE001 - 常驻服务：这一轮出意外只记类名，下一轮照常扫
            ok = False
            log(f"本轮扫描出错：{type(exc).__name__}，{args.interval:.0f}s 后再扫")
        if args.once:
            return 0 if ok else 1
        sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
