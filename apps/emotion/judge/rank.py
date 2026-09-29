# -*- coding: utf-8 -*-
"""命中排序。风险线索永远在最前（只抬不压，设计决策第 10 条），其余按重要度降序、同分按对话顺序。"""
from __future__ import annotations


def rank_hits(hits: list) -> list:
    return sorted(hits, key=lambda h: (not h.get("risk", False), -float(h.get("importance", 0.0)),
                                       int(h.get("turn_index", 0))))
