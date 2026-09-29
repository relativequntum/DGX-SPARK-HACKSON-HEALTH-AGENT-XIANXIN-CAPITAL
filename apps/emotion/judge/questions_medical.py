# -*- coding: utf-8 -*-
"""医疗信息组判断题（Jev 格式）。只做**定位**：这句回答里有没有医生开诊前该亲眼看的信息、
属于哪类、多急、够不够具体。不写摘要、不下诊断——摘要归阶段一（路线图 M1「医生结构化摘要」）。

每题针对「患者最新一条回答」，结合 state.chat.messages 里最近 N 轮上下文判断。
格式与 Jev Decisions API 一致，可原样发给 Jev 云端或喂给本地大模型（backends/）。

红旗边界（docs/safety-and-privacy.md、决策记录第 5 条）：
- risk_clue 只能抬不能压：有疑问就答 true；engine 把它永远排在清单最前；
- 本模块不做「未命中即安全」的推论，确定性红旗规则另有其层，本模块不替代。

unknown 约定同 questions_emotion.py。博士 / 医生审阅后可直接改本文件；改了 choice 的 key 要同步 CHOICE_LABELS。
"""

from __future__ import annotations

GROUP = "medical"
GROUP_LABEL = "医疗信息"

QUESTIONS: dict = {
    "contains_key_info": {
        "type": "noul",
        "instructions": (
            "Does the patient's latest answer contain information a clinician would want to read "
            "verbatim before the visit, rather than a bare confirmation of what the agent asked? "
            "New facts count; '是的' / '没有' to a yes/no question does not, unless the yes/no itself "
            "is clinically important (e.g. confirming an allergy)."
        ),
        "criteria": {
            "true": (
                "Names a symptom, its timing or course, a drug, a reaction, a past condition, "
                "a trigger, or a life circumstance that bears on the complaint."
            ),
            "false": (
                "A bare confirmation, small talk, a question back to the agent, "
                "or content already stated earlier in the snippet."
            ),
        },
    },
    "info_category": {
        "type": "choice",
        "instructions": (
            "Which category best describes the MOST important information in the patient's latest answer? "
            "If the answer contains any hint of self-harm, harm to others, or an acute severe symptom, "
            "choose risk_clue even if other categories also apply."
        ),
        "criteria": {
            "chief_complaint": (
                "The main problem and its onset, duration, course, or character (what, since when, how it feels)."
            ),
            "symptom_change": (
                "A symptom getting worse or better, a new pattern, a trigger, or a new symptom "
                "outside the original complaint."
            ),
            "medication": (
                "Drugs or remedies taken: names, doses, how long, self-medication, "
                "effects or side effects, stopping or changing a drug."
            ),
            "allergy_adverse": (
                "An allergy, intolerance, or a past adverse reaction to a drug, food, or material."
            ),
            "history": (
                "Past illnesses, surgeries, chronic conditions, pregnancy, or family history."
            ),
            "lifestyle_context": (
                "Sleep, diet, work or study stress, alcohol, smoking, living situation, "
                "or a recent life event that bears on the complaint."
            ),
            "risk_clue": (
                "Any wording that could indicate self-harm, harm to others, or an acute severe symptom "
                "(chest pain, trouble breathing, heavy bleeding, confusion, fainting). "
                "Suspected is enough; a human decides."
            ),
            "none": (
                "No clinically relevant information in this answer."
            ),
            "unknown": (
                "Too garbled or too little text to categorize."
            ),
        },
    },
    "risk_clue": {
        "type": "noul",
        "instructions": (
            "Does the patient's latest answer contain ANY wording that could indicate self-harm, "
            "harm to others, or an acute severe symptom happening now (chest pain, trouble breathing, "
            "heavy bleeding, confusion, fainting, high fever with a stiff neck)? "
            "Answer true on any doubt. This question only raises attention; it never lowers it. "
            "A separate rule layer handles confirmed red flags; do not reason about that layer here."
        ),
        "criteria": {
            "true": (
                "Direct or indirect wording of this kind is present: '不想活了', '活着没意思', "
                "'想伤害', '胸口一直疼', '喘不上气', or a description of losing consciousness."
            ),
            "false": (
                "Nothing in the answer could be read this way."
            ),
        },
    },
    "urgency": {
        "type": "score",
        "instructions": (
            "How urgently should the clinician see the information in the patient's latest answer, "
            "relative to everything else in the pre-visit record? Score the information itself, "
            "not the patient's tone. If the answer contains a risk clue, use bin 8 or 9."
        ),
        "criteria": [
            "Background context with no bearing on today's visit.",
            "Confirms something already known in the snippet; adds little.",
            "Useful history or lifestyle detail; can wait until the visit.",
            "Chief-complaint details (onset, duration, course) that frame the visit.",
            "Current medication or self-medication the clinician must reconcile before prescribing.",
            "A symptom that has worsened or changed pattern recently.",
            "A new symptom outside the original complaint, or a suspected adverse drug reaction.",
            "An allergy or interaction risk relevant to likely prescriptions.",
            "An acute-red-flag-family symptom described as ongoing (chest pain, trouble breathing, "
            "heavy bleeding, confusion, fainting).",
            "Self-harm or harm-to-others wording, or an acute severe symptom described as happening now "
            "or worsening fast.",
        ],
    },
    "specificity": {
        "type": "choice",
        "instructions": (
            "How concrete is the information in the patient's latest answer? "
            "Judge only the answer's own wording."
        ),
        "criteria": {
            "specific": (
                "Gives names, numbers, dates, durations, or frequencies ('每晚两点醒', '吃了三天奥美拉唑')."
            ),
            "vague": (
                "General description without specifics ('吃了点药', '有段时间了', '经常不舒服')."
            ),
            "unknown": (
                "No information to judge, or too garbled."
            ),
        },
    },
    "needs_followup": {
        "type": "noul",
        "instructions": (
            "Does the patient's latest answer leave an obvious gap that a clinician would want to ask about "
            "(a drug without dose or duration, a symptom without timing, a 'sometimes' without frequency, "
            "a reaction without what caused it)? Only judge gaps in the information given; "
            "if the answer contains no clinical information, answer false."
        ),
        "criteria": {
            "true": (
                "The information is present but incomplete in a way a clinician would need to fill: "
                "missing dose, duration, timing, frequency, or cause."
            ),
            "false": (
                "The information given is complete enough for its category, or there is no clinical "
                "information in the answer."
            ),
        },
    },
}


CHOICE_LABELS: dict = {
    "info_category": {
        "chief_complaint": "主诉与病程", "symptom_change": "症状变化或新症状",
        "medication": "用药", "allergy_adverse": "过敏或不良反应", "history": "既往史或家族史",
        "lifestyle_context": "生活与社会背景", "risk_clue": "疑似风险线索",
        "none": "无临床信息", "unknown": "无法判断",
    },
    "specificity": {
        "specific": "有具体细节", "vague": "描述笼统", "unknown": "无法判断",
    },
}

NOUL_LABELS: dict = {
    "contains_key_info": {"true": "含医生需看的信息", "false": "无新信息"},
    "risk_clue": {"true": "疑似风险线索（请人工核实）", "false": "未见风险措辞"},
    "needs_followup": {"true": "信息不完整，需追问", "false": "信息足够或无信息"},
}

SCORE_LABELS: dict = {
    "urgency": "紧急程度",
}


if __name__ == "__main__":
    for name, q in QUESTIONS.items():
        assert q["type"] in ("noul", "choice", "score"), name
        assert q["instructions"].strip(), name
        if q["type"] == "choice":
            assert "unknown" in q["criteria"], f"{name}: choice 必须带 unknown"
            assert set(CHOICE_LABELS[name]) == set(q["criteria"]), f"{name}: CHOICE_LABELS 与 criteria 不一致"
        elif q["type"] == "noul":
            assert set(q["criteria"]) == {"true", "false"}, name
            assert set(NOUL_LABELS[name]) == {"true", "false"}, name
        else:
            assert isinstance(q["criteria"], list) and len(q["criteria"]) == 10, f"{name}: score 要 10 档"
            assert name in SCORE_LABELS, name
    assert "risk_clue" in QUESTIONS and QUESTIONS["risk_clue"]["type"] == "noul"  # engine 靠这题置顶
    assert "risk_clue" in QUESTIONS["info_category"]["criteria"]
    assert set(CHOICE_LABELS) == {n for n, q in QUESTIONS.items() if q["type"] == "choice"}
    assert set(NOUL_LABELS) == {n for n, q in QUESTIONS.items() if q["type"] == "noul"}
    print(f"questions_medical ok ({len(QUESTIONS)} questions)")
