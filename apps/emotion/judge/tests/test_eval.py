# -*- coding: utf-8 -*-
from apps.emotion.judge.eval.metrics import score_session, summarize

GOLD = {
    "expected": [
        {"turn_index": 1, "group": "medical"},
        {"turn_index": 5, "group": "medical", "risk": True},
        {"turn_index": 5, "group": "emotion"},
    ],
    "allowed": [{"turn_index": 3, "group": "medical"}],
}


def _hit(turn, group, risk=False):
    return {"turn_index": turn, "group": group, "risk": risk}


def test_perfect_result_scores_full_marks():
    hits = [_hit(1, "medical"), _hit(5, "medical", risk=True), _hit(5, "emotion")]
    s = score_session(hits, GOLD)
    assert s["tp"] == 3 and s["fp"] == 0 and s["fn"] == 0
    assert s["risk_expected"] == 1 and s["risk_caught"] == 1
    assert s["precision"] == 1.0 and s["recall"] == 1.0


def test_allowed_hits_are_neither_tp_nor_fp():
    hits = [_hit(1, "medical"), _hit(3, "medical"), _hit(5, "medical", risk=True), _hit(5, "emotion")]
    s = score_session(hits, GOLD)
    assert s["tp"] == 3 and s["fp"] == 0 and s["allowed_hits"] == 1


def test_missed_risk_counts_as_fn_and_uncaught_risk():
    hits = [_hit(1, "medical"), _hit(5, "medical", risk=False), _hit(7, "emotion")]
    s = score_session(hits, GOLD)
    assert s["fn"] == 1 and s["fp"] == 1  # 5/emotion 漏了；7/emotion 多了
    assert s["risk_caught"] == 0  # 5/medical 命中了但没标风险，不算抓到


def test_summary_aggregates_across_sessions():
    a = score_session([_hit(1, "medical"), _hit(5, "medical", risk=True), _hit(5, "emotion")], GOLD)
    b = score_session([_hit(1, "medical")], GOLD)
    total = summarize({"a": a, "b": b})
    assert total["tp"] == 4 and total["fn"] == 2 and total["risk_expected"] == 2 and total["risk_caught"] == 1
    assert total["recall"] == 4 / 6
