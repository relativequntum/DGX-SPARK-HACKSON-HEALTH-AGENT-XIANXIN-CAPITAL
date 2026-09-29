# -*- coding: utf-8 -*-
"""医生视图：一页静态 HTML（设计决策第 11 条）。

左侧问答全文，命中的患者回答按组着色（风险红、医疗蓝、情绪琥珀）；右侧按重要度排序的清单，
每条写类别、置信度、来源（本地 / Jev 云端）、原话依据，点击跳到原句；顶部固定「待医务人员确认」。
不引用任何外部资源（离线演示），不上前端框架。
"""
from __future__ import annotations

import html as _html

_CSS = """
:root{--ink:#1f2933;--muted:#6b7280;--line:#e5e7eb;--bg:#f8fafc;--risk:#b91c1c;--risk-bg:#fef2f2;
--med:#1d4ed8;--med-bg:#eff6ff;--emo:#b45309;--emo-bg:#fffbeb;--agent-bg:#f1f5f9}
*{box-sizing:border-box}body{margin:0;font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif;color:var(--ink);background:var(--bg)}
header{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid var(--line);padding:12px 20px}
header h1{margin:0 0 4px;font-size:18px}.notice{display:block;padding:8px 12px;border-left:4px solid var(--risk);background:var(--risk-bg);color:var(--risk);font-weight:600}
.meta{color:var(--muted);font-size:13px;margin-top:6px}
main{display:grid;grid-template-columns:minmax(0,3fr) minmax(320px,2fr);gap:20px;padding:20px;max-width:1400px;margin:0 auto}
@media(max-width:900px){main{grid-template-columns:1fr}}
section h2{font-size:15px;margin:0 0 10px;color:var(--muted)}
.turn{padding:10px 14px;border-radius:10px;margin:8px 0;border:1px solid var(--line);background:#fff}
.turn.agent{background:var(--agent-bg);border-color:transparent}.turn .who{font-size:12px;color:var(--muted);margin-bottom:2px}
.turn.hit{border-width:2px}.turn.hit-medical{border-color:var(--med);background:var(--med-bg)}
.turn.hit-emotion{border-color:var(--emo);background:var(--emo-bg)}.turn.hit.risk{border-color:var(--risk);background:var(--risk-bg)}
.badges{margin-top:6px}.badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:999px;margin:2px 4px 0 0;border:1px solid currentColor}
.badge.risk{color:var(--risk)}.badge.medical{color:var(--med)}.badge.emotion{color:var(--emo)}
.hits{position:sticky;top:96px;align-self:start;max-height:calc(100vh - 110px);overflow:auto}
.card{display:block;text-decoration:none;color:inherit;background:#fff;border:1px solid var(--line);border-left:5px solid var(--line);border-radius:10px;padding:10px 12px;margin:0 0 10px}
.card.medical{border-left-color:var(--med)}.card.emotion{border-left-color:var(--emo)}.card.risk{border-left-color:var(--risk);background:var(--risk-bg)}
.card .top{display:flex;justify-content:space-between;align-items:center;font-size:13px;color:var(--muted)}
.card .q{font-size:13px;color:var(--muted);margin:4px 0 0}.card .t{margin:4px 0;font-weight:600}
.card .ev{font-size:13px;color:var(--ink);margin:2px 0}.card .ev b{font-weight:600;color:var(--muted)}
.card ul{margin:6px 0 0;padding-left:18px;font-size:13px;color:#374151}
.pct{font-weight:700;color:var(--ink)}footer{padding:12px 20px 30px;color:var(--muted);font-size:13px;text-align:center}
.empty{color:var(--muted);padding:10px}
"""


def render(result: dict) -> str:
    e = _html.escape
    hits = result.get("hits") or []
    turns = result.get("turns") or []
    hit_index = _hits_by_turn(hits)

    transcript = []
    for t in turns:
        i = t["index"]
        if t["role"] == "agent":
            qid = f"　<span class='who'>（{e(str(t.get('question_id')))}）</span>" if t.get("question_id") else ""
            transcript.append(f'<div id="turn-{i}" class="turn agent"><div class="who">问诊 Agent{qid}</div>'
                              f'<div>{e(t["text"])}</div></div>')
            continue
        mine = hit_index.get(i, [])
        classes = "turn patient"
        if mine:
            classes += " hit"
            if any(h["risk"] for h in mine):
                classes += " risk"
            for g in sorted({h["group"] for h in mine}):
                classes += f" hit-{g}"
        badges = ""
        if mine:
            parts = []
            if any(h["risk"] for h in mine):
                parts.append('<span class="badge risk">疑似风险线索 · 请人工核实</span>')
            for h in mine:
                parts.append(f'<span class="badge {e(h["group"])}">{e(h["group_label"])} {_pct(h["importance"])}</span>')
            badges = f'<div class="badges">{"".join(parts)}</div>'
        transcript.append(f'<div id="turn-{i}" class="{classes}"><div class="who">患者</div>'
                          f'<div>{e(t["text"])}</div>{badges}</div>')

    cards = []
    for n, h in enumerate(hits, 1):
        cls = "card " + e(h["group"]) + (" risk" if h["risk"] else "")
        risk = '<span class="badge risk">疑似风险线索</span> ' if h["risk"] else ""
        labels = "".join(f"<li>{e(v)}</li>" for v in (h.get("labels") or {}).values())
        evidence = f'<div class="ev"><b>依据：</b>「{e(h["evidence"])}」</div>' if h.get("evidence") else ""
        question = f'<div class="q">回答「{e(h["question"])}」时</div>' if h.get("question") else ""
        cards.append(
            f'<a class="{cls}" href="#turn-{h["turn_index"]}">'
            f'<div class="top"><span>#{n} {risk}{e(h["group_label"])}</span>'
            f'<span><span class="pct">{_pct(h["importance"])}</span> · {e(_source_label(h.get("source", "")))}</span></div>'
            f'{question}<div class="t">{e(h["text"])}</div>{evidence}<ul>{labels}</ul></a>')
    if not cards:
        cards.append('<div class="empty">没有达到阈值的命中。</div>')

    sources = sorted({_source_label(h.get("source", "")) for h in hits})
    meta = (f"会话 {e(str(result.get('session_id')))} · 生成于 {e(str(result.get('generated_at', '')))} · "
            f"schema {e(str(result.get('schema_version', '')))} · 判断来源：{e('、'.join(sources) or '—')}"
            + (f" · 后端出错 {result['errors']} 次" if result.get("errors") else ""))

    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>预问诊对话重点 · {e(str(result.get('session_id')))}</title><style>{_CSS}</style></head><body>"
        f"<header><h1>预问诊对话重点</h1><span class=\"notice\">{e(result.get('review_notice') or '待医务人员确认')}</span>"
        f"<div class=\"meta\">{meta}</div></header>"
        f"<main><section><h2>对话全文（{len(turns)} 轮）</h2>{''.join(transcript)}</section>"
        f"<section class=\"hits\"><h2>值得先看的回答（{len(hits)} 条，风险线索永远在最前）</h2>{''.join(cards)}</section></main>"
        "<footer>百分比是模型自报的置信度，不是情绪评分。确定性红旗规则另有其层，本页不替代。"
        "所有判断待医务人员确认。</footer></body></html>"
    )


def _hits_by_turn(hits: list) -> dict:
    by = {}
    for h in hits:
        by.setdefault(h["turn_index"], []).append(h)
    return by


def _pct(x) -> str:
    return f"{round(float(x) * 100)}%"


def _source_label(source: str) -> str:
    if source.startswith("local:"):
        return "本地"
    if source.startswith("jev-cloud:"):
        return "Jev 云端"
    return source or "—"
