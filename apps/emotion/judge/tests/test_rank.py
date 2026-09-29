# -*- coding: utf-8 -*-
from apps.emotion.judge.rank import rank_hits


def _hit(turn, importance, risk=False):
    return {"turn_index": turn, "importance": importance, "risk": risk}


def test_risk_hits_come_before_higher_importance_non_risk_hits():
    hits = [_hit(1, 0.9), _hit(2, 0.3, risk=True), _hit(3, 0.6)]
    assert [h["turn_index"] for h in rank_hits(hits)] == [2, 1, 3]


def test_non_risk_hits_sort_by_importance_desc_then_turn_order():
    hits = [_hit(5, 0.6), _hit(2, 0.6), _hit(3, 0.8)]
    assert [h["turn_index"] for h in rank_hits(hits)] == [3, 2, 5]


def test_rank_does_not_mutate_input():
    hits = [_hit(1, 0.1), _hit(2, 0.9)]
    rank_hits(hits)
    assert [h["turn_index"] for h in hits] == [1, 2]
