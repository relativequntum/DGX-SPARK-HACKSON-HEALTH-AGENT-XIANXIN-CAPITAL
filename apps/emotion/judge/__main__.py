# -*- coding: utf-8 -*-
"""命令行入口。

    python -m apps.emotion.judge run samples/xxx.json                 # 本机 Ollama（默认 qwen3-vl:8b）
    python -m apps.emotion.judge run s.json --backend openai --base-url http://127.0.0.1:8080/v1 --model qwen3.6-35b-a3b
    python -m apps.emotion.judge run s.json --cloud                   # 显式开关 + JEV_API_KEY 才走 Jev，失败退本地

输出 <out-dir>/<session_id>.judge.json 与 .judge.html（默认 outputs/judge/，已被 .gitignore 挡住）。
会话文件：{"session_id": "...", "turns": [{"role": "agent"|"patient", "text": "...", "question_id": "..."}]}，
也接受裸的 turns 列表（session_id 取文件名），以及数字人 consult_recorder 的问诊记录 .jsonl（见 sources.py）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .backends.base import FallbackBackend
from .backends.jev_cloud import JEV_ENV, JevCloudBackend, cloud_enabled
from .backends.local_openai import LocalOpenAIBackend
from .backends.ollama_native import OllamaNativeBackend
from .engine import DEFAULT_GROUPS, analyze_session
from .render_html import render
from .sources import load_session  # noqa: F401  (评测脚本也从这里取)


def add_backend_args(p: argparse.ArgumentParser) -> None:
    """run 子命令与评测脚本共用的后端参数。"""
    p.add_argument("--backend", choices=("ollama", "openai"), default="ollama",
                   help="本地传输：ollama = 本机 /api/chat（默认）；openai = OpenAI 兼容 /v1（Spark llama-server）")
    p.add_argument("--model", help="本地模型名（默认 ollama: qwen3-vl:8b；openai: qwen3.6-35b-a3b）")
    p.add_argument("--host", help="Ollama 地址，默认 http://127.0.0.1:11434")
    p.add_argument("--base-url", help="OpenAI 兼容端点，默认 http://127.0.0.1:8080/v1")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--cloud", action="store_true", help=f"显式开启 Jev 云端判断（还需要环境变量 {JEV_ENV}）")
    p.add_argument("--cloud-model", default=None, help="Jev 模型名，默认 typesafe/jev-1.13")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m apps.emotion.judge", description="预问诊对话重点判断（阶段三 judge）")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="对一段会话跑一次判断，输出 JSON + HTML")
    run.add_argument("session", help="会话 JSON 文件")
    add_backend_args(run)
    run.add_argument("--groups", default=",".join(DEFAULT_GROUPS), help="题组，逗号分隔：emotion,medical")
    run.add_argument("--keep", type=int, default=10, help="每条回答带最近多少轮上下文")
    run.add_argument("--threshold", type=float, default=0.5, help="重要度达到多少算命中（风险线索不受此限）")
    run.add_argument("--out-dir", default="outputs/judge")
    return p


def make_backend(argv):
    return backend_from_args(build_parser().parse_args(argv))


def backend_from_args(args):
    if args.backend == "openai":
        local = LocalOpenAIBackend(base_url=args.base_url, model=args.model, timeout=args.timeout)
    else:
        local = OllamaNativeBackend(host=args.host, model=args.model, timeout=args.timeout)
    if not args.cloud:
        return local
    if not cloud_enabled(True):
        print(f"[judge] --cloud 已指定但环境变量 {JEV_ENV} 为空，本次只用本地判断。", file=sys.stderr)
        return local
    cloud = JevCloudBackend(**({"model": args.cloud_model} if args.cloud_model else {}))
    return FallbackBackend(cloud, local)


def write_outputs(result: dict, out_dir: pathlib.Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = str(result.get("session_id"))
    json_path = out_dir / f"{stem}.judge.json"
    html_path = out_dir / f"{stem}.judge.html"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    html_path.write_text(render(result), encoding="utf-8")
    return json_path, html_path


def main(argv=None, backend=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    args = build_parser().parse_args(argv)
    session = load_session(pathlib.Path(args.session))
    backend = backend or make_backend(argv)
    groups = tuple(g.strip() for g in args.groups.split(",") if g.strip())
    result = analyze_session(session, backend, groups=groups, keep=args.keep, threshold=args.threshold)

    json_path, html_path = write_outputs(result, pathlib.Path(args.out_dir))
    stem = str(session["session_id"])
    print(f"[judge] {stem}: {len(result['hits'])} 条命中，{result['errors']} 次后端出错")
    for n, h in enumerate(result["hits"], 1):
        flag = "风险 " if h["risk"] else ""
        print(f"  #{n} {flag}{h['group_label']} {round(h['importance'] * 100)}% turn{h['turn_index']} {h['text'][:40]}")
    print(f"[judge] 写出 {json_path}")
    print(f"[judge] 写出 {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
