# -*- coding: utf-8 -*-
import pytest

from apps.emotion.judge.state import build_state

TURNS = [
    {"role": "agent", "text": "最近睡眠怎么样？", "question_id": "sleep"},
    {"role": "patient", "text": "还行吧。"},
    {"role": "agent", "text": "有没有在吃什么药？", "question_id": "medication"},
    {"role": "patient", "text": "吃了点助眠的，名字忘了。"},
    {"role": "agent", "text": "胃不舒服多久了？", "question_id": "stomach"},
    {"role": "patient", "text": "三个月了，其实睡也没睡好。"},
]


def test_state_holds_focus_turn_and_context_up_to_it():
    state = build_state(TURNS, focus=3, keep=3)
    msgs = state["chat"]["messages"]
    assert [m["from"] for m in msgs] == ["patient", "agent", "patient"]
    assert msgs[-1]["text"] == "吃了点助眠的，名字忘了。"
    assert state["chat"]["latest_from"] == "patient"


def test_state_names_the_question_being_answered():
    state = build_state(TURNS, focus=5, keep=10)
    assert state["chat"]["focus"] == {"question_id": "stomach", "question": "胃不舒服多久了？"}


def test_state_reserves_empty_channels_field():
    state = build_state(TURNS, focus=1, keep=10)
    assert state["channels"] == {}


def test_state_rejects_focus_on_agent_turn():
    with pytest.raises(ValueError):
        build_state(TURNS, focus=0, keep=10)


def test_state_rejects_unknown_role():
    bad = [{"role": "doctor", "text": "x"}, {"role": "patient", "text": "y"}]
    with pytest.raises(ValueError):
        build_state(bad, focus=1, keep=10)
