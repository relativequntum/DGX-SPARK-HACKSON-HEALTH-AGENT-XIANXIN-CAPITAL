# -*- coding: utf-8 -*-
"""跑 samples/ 下全部虚构样本，对照 eval/gold.json 打分，写 outputs/judge/eval/report.md。

    python -m apps.emotion.judge.eval.run_eval                 # 本机 Ollama
    python -m apps.emotion.judge.eval.run_eval --backend openai --base-url http://127.0.0.1:8080/v1

金标准是人标的（待博士审），分数只用来看改题目 / 换模型有没有变好，不是临床指标。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from ..__main__ import add_backend_args, backend_from_args, load_session, write_outputs
from ..engine import analyze_session
from .metrics import score_session, summarize

HERE = pathlib.Path(__file__).resolve().parent


def main(argv=None, backend=None) -> int:
    p = argparse.ArgumentParser(prog="python -m apps.emotion.judge.eval.run_eval")
    add_backend_args(p)
    p.add_argument("--samples", default=str(HERE.parent / "samples"))
    p.add_argument("--gold", default=str(HERE / "gold.json"))
    p.add_argument("--out-dir", default="outputs/judge/eval")
    p.add_argument("--keep", type=int, default=10)
    p.add_argument("--threshold", type=float, default=0.5)
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    backend = backend or backend_from_args(args)
    gold = json.loads(pathlib.Path(args.gold).read_text(encoding="utf-8"))["sessions"]
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows, per_session = [], {}
    for path in sorted(pathlib.Path(args.samples).glob("*.json")):
        session = load_session(path)
        sid = str(session["session_id"])
        if sid not in gold:
            print(f"[eval] 跳过 {sid}：gold.json 里没有", file=sys.stderr)
            continue
        t0 = time.time()
        result = analyze_session(session, backend, keep=args.keep, threshold=args.threshold)
        elapsed = time.time() - t0
        write_outputs(result, out_dir)
        s = score_session(result["hits"], gold[sid])
        per_session[sid] = s
        rows.append((sid, s, elapsed, result["errors"], getattr(backend, "source", "")))
        print(f"[eval] {sid}: tp={s['tp']} fp={s['fp']} fn={s['fn']} risk={s['risk_caught']}/{s['risk_expected']} "
              f"{elapsed:.1f}s errors={result['errors']}")

    total = summarize(per_session)
    report = _report(rows, total, getattr(backend, "source", ""))
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"[eval] 报告写到 {out_dir / 'report.md'}")
    return 0


def _report(rows, total, source) -> str:
    lines = [f"# judge 评测（来源 {source}，{time.strftime('%Y-%m-%d %H:%M')}）", "",
             "| 样本 | 应命中 | 命中 | 误报 | 漏报 | 风险抓到 | 耗时 | 后端出错 |", "|---|---|---|---|---|---|---|---|"]
    for sid, s, elapsed, errors, _ in rows:
        lines.append(f"| {sid} | {s['tp'] + s['fn']} | {s['tp']} | {s['fp']} | {s['fn']} | "
                     f"{s['risk_caught']}/{s['risk_expected']} | {elapsed:.0f}s | {errors} |")
    lines += ["", f"**合计**：precision {total['precision']:.2f} · recall {total['recall']:.2f} · "
                  f"风险召回 {total['risk_recall']:.2f}（{total['risk_caught']}/{total['risk_expected']}）",
              "", "漏报 / 误报明细："]
    for sid, s, _, _, _ in rows:
        if s["missed"] or s["extra"]:
            lines.append(f"- {sid}：漏 {s['missed'] or '无'}；多 {s['extra'] or '无'}")
    lines += ["", "金标准由人标注、待博士审；分数只用于比较题目与模型的改动，不是临床指标。"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
