# -*- coding: utf-8 -*-
from apps.emotion.judge.answers import importance, is_risk, normalize


def test_noul_near_half_is_unknown():
    a = normalize({"type": "noul", "noul": 0.55})
    assert a["unknown"] is True and a["value"] is True


def test_noul_far_from_half_is_known():
    a = normalize({"type": "noul", "noul": 0.9})
    assert a["unknown"] is False and a["value"] is True and a["confidence"] == 0.9


def test_choice_unknown_option_is_unknown():
    a = normalize({"type": "choice", "choice": "unknown", "confidence": 0.9})
    assert a["unknown"] is True and a["value"] == "unknown"


def test_choice_low_confidence_is_unknown():
    a = normalize({"type": "choice", "choice": "full", "confidence": 0.4})
    assert a["unknown"] is True and a["value"] == "full"


def test_choice_confident_is_known():
    a = normalize({"type": "choice", "choice": "full", "confidence": 0.8, "probabilities": {"full": 0.8}})
    assert a["unknown"] is False and a["value"] == "full" and a["probabilities"] == {"full": 0.8}


def test_score_low_confidence_is_unknown():
    a = normalize({"type": "score", "score": 4, "confidence": 0.3})
    assert a["unknown"] is True and a["value"] == 4


def test_emotion_importance_is_worth_flagging_probability():
    answers = {"worth_flagging": normalize({"type": "noul", "noul": 0.8})}
    assert importance("emotion", answers) == 0.8


def test_medical_importance_scales_key_info_by_urgency():
    key = normalize({"type": "noul", "noul": 1.0})
    assert importance("medical", {"contains_key_info": key,
                                  "urgency": normalize({"type": "score", "score": 9, "confidence": 0.9})}) == 1.0
    assert importance("medical", {"contains_key_info": key,
                                  "urgency": normalize({"type": "score", "score": 0, "confidence": 0.9})}) == 0.4
    assert importance("medical", {"contains_key_info": normalize({"type": "noul", "noul": 0.0}),
                                  "urgency": normalize({"type": "score", "score": 9, "confidence": 0.9})}) == 0.0


def test_missing_answers_give_zero_importance():
    assert importance("emotion", {}) == 0.0
    assert importance("medical", {}) == 0.0


def test_risk_from_risk_clue_probability():
    assert is_risk({"risk_clue": normalize({"type": "noul", "noul": 0.6})}) is True
    assert is_risk({"risk_clue": normalize({"type": "noul", "noul": 0.2})}) is False


def test_risk_from_category_or_top_urgency():
    assert is_risk({"info_category": normalize({"type": "choice", "choice": "risk_clue", "confidence": 0.5})}) is True
    assert is_risk({"urgency": normalize({"type": "score", "score": 8, "confidence": 0.2})}) is True
    assert is_risk({"urgency": normalize({"type": "score", "score": 7, "confidence": 0.9})}) is False
