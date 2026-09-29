# -*- coding: utf-8 -*-
"""评测口径：命中 = (turn_index, group)。

expected：应命中的对；标 risk 的还要求被标为风险线索（只抬不压，漏标风险单独统计）。
allowed：命中也不算错、漏了也不算错的模糊项。其余多出来的命中算误报。
"""
from __future__ import annotations


def _key(item: dict) -> tuple:
    return int(item["turn_index"]), str(item["group"])


def score_session(hits: list, gold: dict) -> dict:
    expected = {_key(x): bool(x.get("risk")) for x in gold.get("expected", [])}
    allowed = {_key(x) for x in gold.get("allowed", [])}
    got: dict = {}
    for h in hits:
        got[_key(h)] = got.get(_key(h), False) or bool(h.get("risk"))
    got_keys, exp_keys = set(got), set(expected)
    tp = len(got_keys & exp_keys)
    fp = len(got_keys - exp_keys - allowed)
    fn = len(exp_keys - got_keys)
    risk_expected = sum(1 for r in expected.values() if r)
    risk_caught = sum(1 for k, r in expected.items() if r and got.get(k))
    return _with_rates({"tp": tp, "fp": fp, "fn": fn, "allowed_hits": len(got_keys & allowed),
                        "risk_expected": risk_expected, "risk_caught": risk_caught,
                        "missed": sorted(exp_keys - got_keys), "extra": sorted(got_keys - exp_keys - allowed)})


def summarize(per_session: dict) -> dict:
    total = {k: 0 for k in ("tp", "fp", "fn", "allowed_hits", "risk_expected", "risk_caught")}
    for s in per_session.values():
        for k in total:
            total[k] += int(s.get(k, 0))
    return _with_rates(total)


def _with_rates(s: dict) -> dict:
    tp, fp, fn = s["tp"], s["fp"], s["fn"]
    s["precision"] = tp / (tp + fp) if tp + fp else 1.0
    s["recall"] = tp / (tp + fn) if tp + fn else 1.0
    s["risk_recall"] = s["risk_caught"] / s["risk_expected"] if s["risk_expected"] else 1.0
    return s
