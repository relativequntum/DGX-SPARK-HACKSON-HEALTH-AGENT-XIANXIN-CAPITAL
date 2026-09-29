# -*- coding: utf-8 -*-
import re

from apps.emotion.judge.render_html import render

RESULT = {
    "schema_version": "judge-0.1", "session_id": "demo-7", "generated_at": "2026-09-24T23:00:00+08:00",
    "review_notice": "待医务人员确认：本页只标出值得先看的回答。",
    "errors": 0,
    "turns": [
        {"index": 0, "role": "agent", "text": "最近睡眠怎么样？", "question_id": "sleep"},
        {"index": 1, "role": "patient", "text": "还行吧 <script>alert(1)</script>", "judgments": {}},
        {"index": 2, "role": "agent", "text": "有没有在吃什么药？", "question_id": "medication"},
        {"index": 3, "role": "patient", "text": "吃了点助眠的。", "judgments": {}},
        {"index": 4, "role": "agent", "text": "最近心情怎么样？", "question_id": "mood"},
        {"index": 5, "role": "patient", "text": "有时候觉得活着没什么意思。", "judgments": {}},
    ],
    "hits": [
        {"turn_index": 5, "text": "有时候觉得活着没什么意思。", "question_id": "mood", "question": "最近心情怎么样？",
         "group": "medical", "group_label": "医疗信息", "importance": 0.9, "risk": True, "source": "local:qwen3-vl:8b",
         "labels": {"info_category": "疑似风险线索", "urgency": "紧急程度 9/9"}, "evidence": "活着没什么意思", "answers": {}},
        {"turn_index": 3, "text": "吃了点助眠的。", "question_id": "medication", "question": "有没有在吃什么药？",
         "group": "medical", "group_label": "医疗信息", "importance": 0.63, "risk": False, "source": "jev-cloud:typesafe/jev-1.13",
         "labels": {"info_category": "用药"}, "evidence": "助眠的", "answers": {}},
    ],
}


def test_page_has_title_notice_and_no_external_resources():
    html = render(RESULT)
    assert "<title>" in html and "demo-7" in html
    assert "待医务人员确认" in html
    assert "http://" not in html and "https://" not in html  # 离线演示，不拉任何外部资源


def test_every_turn_is_listed_with_anchor_and_text_is_escaped():
    html = render(RESULT)
    for i in range(6):
        assert f'id="turn-{i}"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "<script>alert(1)" not in html
    assert "最近心情怎么样？" in html


def test_hit_list_links_to_turns_in_ranked_order_with_risk_marked():
    html = render(RESULT)
    links = re.findall(r'href="#turn-(\d+)"', html)
    assert links == ["5", "3"]
    first = html.index('href="#turn-5"')
    assert "风险" in html[first:first + 800]
    assert "90%" in html and "63%" in html
    assert "本地" in html and "Jev 云端" in html
    assert "活着没什么意思" in html and "紧急程度 9/9" in html


def test_hit_turns_are_highlighted_in_transcript():
    html = render(RESULT)
    turn5 = html[html.index('id="turn-5"'):]
    assert 'class="turn patient hit risk' in turn5[:200]
    turn1 = html[html.index('id="turn-1"'):]
    assert "hit" not in turn1[:120]
