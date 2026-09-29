# -*- coding: utf-8 -*-
"""情绪 / 沟通组判断题（Jev 格式）。问的是对话里**可观察的回答行为**，不出情绪标签。

每题针对「患者最新一条回答」，结合 state.chat.messages 里最近 N 轮上下文判断。
格式与 Jev Decisions API 一致（type ∈ noul / choice / score；instructions 与 criteria 用英文，
对话文本保持中文），可以原样发给 Jev 云端，也可以喂给本地大模型（backends/）。

unknown 约定：
- choice 题的 criteria 里都带 unknown，让模型能明确说「看不出来」；
- noul / score 题没有选项，由后端在答案里附 confidence，低于阈值时 engine 记为 unknown。

口径来源：apps/emotion/research/决策记录.md 第 11 条（不出情绪标签）、第 21 条（观察对齐到题目）。
博士审阅后可直接改本文件；改了 choice 的 key 要同步 CHOICE_LABELS。
"""

from __future__ import annotations

GROUP = "emotion"
GROUP_LABEL = "情绪 / 沟通"

QUESTIONS: dict = {
    "answer_adequacy": {
        "type": "choice",
        "instructions": (
            "How fully does the patient's latest answer address the question the agent just asked? "
            "Judge the answer against that question only, not against the whole visit. "
            "A short answer to a yes/no question is still full."
        ),
        "criteria": {
            "full": (
                "Directly answers the question with the detail it asked for "
                "(when, how long, how often, what it feels like), even if briefly."
            ),
            "minimal": (
                "Answers, but with the least possible information: one word, '还行', '不知道', "
                "'差不多', or restating the question without adding anything."
            ),
            "evasive": (
                "Shifts to another topic, answers a different question, says they do not want to talk "
                "about it, or turns the question back on the agent ('问这个干什么')."
            ),
            "off_topic": (
                "The answer is unrelated to the question and does not look like a deliberate deflection "
                "(misheard, distracted, or continuing an earlier point)."
            ),
            "unknown": (
                "The snippet does not show which question was asked, or the answer is too garbled "
                "(ASR errors) to judge."
            ),
        },
    },
    "literal_answer": {
        "type": "noul",
        "instructions": (
            "Is the patient's latest answer meant purely literally, with no unsaid meaning? "
            "Judge from the whole snippet. Minimizing serious content ('没什么大事' after describing "
            "weeks of symptoms), hinting, sarcasm, or testing whether the agent is listening all count "
            "as unsaid meaning."
        ),
        "criteria": {
            "true": (
                "A straightforward statement or answer; what is said is what is meant."
            ),
            "false": (
                "There is unsaid meaning: minimizing, a hint the patient will not say outright, "
                "sarcasm, an implied complaint about the process, or a line that says 'fine' "
                "while the content says otherwise."
            ),
        },
    },
    "tension_level": {
        "type": "score",
        "instructions": (
            "How much strain is observable in the WORDING of the patient's latest answer? "
            "Score only what the words show (hedging, repetition, urgency markers, fragments, "
            "self-comments, refusals). Do not infer a mood. Match the current answer, not an earlier one."
        ),
        "criteria": [
            "Plain, matter-of-fact wording. No hedging, no urgency markers, no comments about self.",
            "Slight hedging or a single filler ('嗯', '还好吧'); otherwise plain.",
            "Mild reluctance markers: very short sentences, '不太想说', trailing off once.",
            "Repeated hedging or minimizing ('没什么大事', '可能是我想多了') while describing a real problem.",
            "Noticeable strain: repetition, '真的', '一直', says they are tired of it, but still cooperative.",
            "Explicit statements of struggling or not coping ('撑不住', '受不了') without urgency toward the agent.",
            "Strain plus frustration at the process or the questions ('问这个有什么用'), or sarcasm toward the agent.",
            "Pleading or urgency toward the agent ('求你', '快点'), or explicit fear about what the answer means.",
            "Disorganized wording: fragments, contradictions within one answer, marked exclamation or crying markers.",
            "Statements of giving up, wanting everything to stop, or refusing to continue. "
            "Treat as a risk clue regardless of this score.",
        ],
    },
    "inconsistency": {
        "type": "noul",
        "instructions": (
            "Does the patient's latest answer contradict or materially revise something the patient "
            "said earlier in this snippet? Only count contradictions that are visible in the snippet; "
            "if the earlier statement is not present, answer false."
        ),
        "criteria": {
            "true": (
                "A visible contradiction or major revision: earlier '睡得还行', now '三个月没睡好'; "
                "earlier 'no medication', now names a drug; a changed timeline."
            ),
            "false": (
                "Consistent with earlier statements, adds detail without contradicting, "
                "or the earlier statement is not in the snippet."
            ),
        },
    },
    "wants_from_agent": {
        "type": "choice",
        "instructions": (
            "Beyond answering the question, what does the patient's latest answer ask of the agent "
            "or the clinician? Judge the latest answer first. If it only answers the question, choose none."
        ),
        "criteria": {
            "reassurance": (
                "Wants to be told it is not serious, or asks whether they should worry ('是不是很严重', '没事吧')."
            ),
            "explanation": (
                "Wants to understand why something is happening or what it means ('为什么会这样', '这是什么病')."
            ),
            "urgency": (
                "Wants faster action: an appointment, a decision, medication now ('能不能今天就看', '先给我开点药')."
            ),
            "to_stop": (
                "Wants to end or pause the conversation, or not discuss this topic ('别问了', '先到这吧')."
            ),
            "none": (
                "Only answers the question; no request toward the agent or clinician."
            ),
            "unknown": (
                "Too little text or too garbled to tell."
            ),
        },
    },
    "worth_flagging": {
        "type": "noul",
        "instructions": (
            "Should the clinician read this exchange before the visit because of HOW the patient "
            "answered, not because of its medical content? Consider the answers above: evasion, "
            "unsaid meaning, high strain, contradiction, or a request toward the clinician. "
            "Medical content is judged by another question set; ignore it here."
        ),
        "criteria": {
            "true": (
                "The way the patient answered would change how a clinician opens the conversation: "
                "they avoided the topic, minimized, contradicted themselves, showed strain, or asked for something."
            ),
            "false": (
                "A plain, cooperative answer with nothing about the manner of answering that needs attention."
            ),
        },
    },
}


# choice 类答案的中文说法，医生视图和评测报告共用这一份。
CHOICE_LABELS: dict = {
    "answer_adequacy": {
        "full": "回答充分", "minimal": "回答极简", "evasive": "回避或转移话题",
        "off_topic": "答非所问", "unknown": "无法判断",
    },
    "wants_from_agent": {
        "reassurance": "希望得到安心的说法", "explanation": "希望了解原因",
        "urgency": "希望尽快处理", "to_stop": "希望停止或换话题",
        "none": "只是在回答", "unknown": "无法判断",
    },
}

# noul 题的中文说法：true / false 各一句，医生视图用。
NOUL_LABELS: dict = {
    "literal_answer": {"true": "字面意思", "false": "有潜台词"},
    "inconsistency": {"true": "与前文矛盾", "false": "与前文一致"},
    "worth_flagging": {"true": "回答方式值得医生留意", "false": "回答方式无特别之处"},
}

SCORE_LABELS: dict = {
    "tension_level": "措辞紧张度",
}


if __name__ == "__main__":
    # 不联网的自检：格式不变式。改题目最容易坏的地方——choice 漏 unknown、score 不是 10 档、标签漏 key。
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
    assert set(CHOICE_LABELS) == {n for n, q in QUESTIONS.items() if q["type"] == "choice"}
    assert set(NOUL_LABELS) == {n for n, q in QUESTIONS.items() if q["type"] == "noul"}
    print(f"questions_emotion ok ({len(QUESTIONS)} questions)")
