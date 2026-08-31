import time

import httpx
import pytest

from cet6_listener.config import LlmSettings
from cet6_listener.domain.events import QuestionEvent, TranscriptSegment
from cet6_listener.llm.client import LlamaCppClient
from cet6_listener.llm.output_cleaner import (
    clean_answer,
    clean_translation,
    contains_chinese,
    has_excessive_repetition,
    is_usable_answer,
    is_usable_translation,
    looks_like_question,
)
from cet6_listener.llm.prompt import (
    build_answer_retry_messages,
    build_chinese_repair_messages,
    build_messages,
    build_translation_messages,
    extract_resolved_evidence,
    question_guidance,
    select_relevant_passage,
)


def test_clean_answer_removes_noise_and_first_sentence() -> None:
    assert clean_answer('**答案是：** “因为航班延误”。这是解释。') == "因为航班延误"


def test_clean_answer_is_bounded() -> None:
    assert len(clean_answer("很" * 60)) == 48


def test_clean_answer_prefers_complete_clause_boundary() -> None:
    first_clause = "核" * 30
    answer = clean_answer(first_clause + "，" + "补" * 30)
    assert answer == first_clause


def test_clean_translation_keeps_multiple_sentences_and_questions() -> None:
    translated = clean_translation("翻译如下：今天天气很好。你想出去吗？")
    assert translated == "今天天气很好。你想出去吗？"
    assert is_usable_translation(translated)


def test_clean_translation_preserves_spaces_inside_english_names() -> None:
    assert clean_translation("他住在 New York City。") == "他住在New York City。"


def test_english_answer_keeps_spaces_and_is_not_chinese() -> None:
    answer = clean_answer("A private home offering lodging and breakfast.")
    assert answer.startswith("A private home offering ")
    assert not contains_chinese(answer)


def test_one_chinese_character_does_not_make_english_answer_chinese() -> None:
    assert not contains_chinese("The answer 是 a private home")
    assert contains_chinese("提供住宿和早餐的私人住宅")


def test_prompt_echo_is_not_usable_answer() -> None:
    assert not is_usable_answer("与问题最直接相关的候选证据按相关度排序")
    assert is_usable_answer("价格合理，午餐时段顾客很多")


def test_question_echo_is_rejected() -> None:
    assert looks_like_question("What is of real importance when people make poor decisions?")
    assert looks_like_question("人们做出错误决定时，什么才是真正重要的")
    assert not looks_like_question("妥善利用从错误决定中吸取的经验")
    assert not looks_like_question("what they do with the lessons learned")
    assert not is_usable_answer("人们做出错误决定时，什么才是真正重要的")


def test_prompt_contains_passage_and_question() -> None:
    messages = build_messages("a passage", "a question")
    assert messages[0]["role"] == "system"
    assert "a passage" in messages[1]["content"]
    assert "a question" in messages[1]["content"]
    assert "核心信息" in messages[1]["content"]
    assert "<transcript>" in messages[1]["content"]


def test_translation_prompt_forbids_answering_source_questions() -> None:
    messages = build_translation_messages("Why are you late?")
    assert "不回答原文中的问题" in messages[0]["content"]
    assert "Why are you late?" in messages[1]["content"]
    assert "只输出译文" in messages[1]["content"]


def test_question_type_guidance_prefers_final_result() -> None:
    guidance = question_guidance("What can result from this common behavior?")
    assert "最终结果" in guidance
    assert "正负方向" in guidance


def test_how_guidance_prefers_general_rule_over_example() -> None:
    guidance = question_guidance("How does one get a career in foreign relations?")
    assert "一般方法" in guidance
    assert "个例" in guidance


def test_how_did_guidance_requests_actual_process() -> None:
    guidance = question_guidance("How did the researchers carry out the study?")
    assert "实际过程" in guidance


def test_guidance_locks_asked_speaker_and_answer_type() -> None:
    guidance = question_guidance(
        "What does the man say the woman must be in thinking they will finish next week?"
    )
    assert "男士" in guidance
    assert "评价或所处状态" in guidance
    assert "不回答其想法内容" in guidance


def test_guidance_preserves_research_groups_and_direction() -> None:
    guidance = question_guidance(
        "What does the study show about frequent users compared with infrequent users?"
    )
    assert "区分实验组" in guidance
    assert "增减方向" in guidance


def test_select_relevant_passage_keeps_matching_sentence_and_neighbor() -> None:
    passage = (
        "The weather was pleasant. People talked about their work. "
        "The baggage tag can be torn off on the conveyor belt. "
        "The owner should put a phone number on the bag. Dinner was served."
    )
    compact = select_relevant_passage(
        passage,
        "What may happen to the baggage tag on the conveyor belt?",
        max_sentences=3,
    )
    assert "torn off" in compact
    assert "phone number" in compact
    assert "weather" not in compact


def test_select_relevant_passage_prefers_direct_result_over_nearby_background() -> None:
    passage = " ".join(
        [
            "People often use phones during face-to-face conversations.",
            "Some participants described the interaction as less enjoyable.",
            "The researchers collected ratings after each meeting.",
            "This common phone behavior can create vicious cycles of detachment.",
            "The report was published in a social psychology journal.",
            "Other researchers plan to repeat the experiment.",
            "The sample included both friends and strangers.",
            "No further demographic details were reported.",
            "The authors thanked their assistants.",
        ]
    )
    compact = select_relevant_passage(
        passage,
        "What can result from this common behavior of using phones?",
        max_sentences=3,
        max_words=80,
    )
    assert "vicious cycles of detachment" in compact


def test_select_relevant_passage_uses_relation_cues_for_importance() -> None:
    passage = " ".join(
        [
            "People make poor decisions throughout life.",
            "Regret can prevent them from moving forward.",
            "Everyone has made a choice they later questioned.",
            "What matters is what people do with the lessons they have learned.",
            "The speaker then asks listeners to consider their progress.",
            "No person can make perfect choices all the time.",
            "The talk ends with a short summary.",
            "The audience applauds the speaker.",
            "A new program begins after a pause.",
        ]
    )
    compact = select_relevant_passage(
        passage,
        "What is of real importance when people make poor decisions?",
        max_sentences=3,
        max_words=80,
    )
    assert "What matters" in compact


def test_evidence_window_explains_second_group_reference() -> None:
    passage = (
        "For some customers dining out is a treat, but for others it is a daily occurrence. "
        "That second group is becoming the majority because fewer customers enjoy cooking. "
        "A later survey confirmed the same trend."
    )
    evidence = select_relevant_passage(
        passage,
        "What do an increasing number of customers do?",
        max_sentences=3,
    )
    assert "second group means customers" in evidence
    assert "dining out" in evidence


def test_direct_contrast_condition_omits_distracting_examples() -> None:
    passage = (
        "Electronic books contain music, animation and sound effects. "
        "These examples may increase participation. "
        "However, if features do not draw attention to educational content, they do not support learning."
    )
    evidence = select_relevant_passage(
        passage,
        "What features should be included to support learning?",
        max_sentences=3,
    )
    assert "draw attention to educational content" in evidence
    assert "must draw attention" in evidence
    assert "music" not in evidence
    assert extract_resolved_evidence(evidence) == (
        "To support the stated goal, features must draw attention to educational content."
    )


def test_extract_resolved_evidence_returns_none_for_normal_context() -> None:
    assert extract_resolved_evidence("Ordinary listening evidence.") is None


def test_repetitive_generation_is_rejected() -> None:
    repeated = "要成为外交官需要具备技能" * 3
    assert has_excessive_repetition(repeated)
    assert not is_usable_answer(repeated)
    assert not has_excessive_repetition("职业外交官，需要沟通能力和持续学习")


def test_repair_prompt_requires_chinese_only() -> None:
    messages = build_chinese_repair_messages("a private home", "What is a B&B?")
    assert "只输出" in messages[0]["content"]
    assert "a private home" in messages[1]["content"]
    assert "不得改变" in messages[0]["content"]
    assert "What is a B&B?" in messages[1]["content"]


def test_answer_retry_prompt_forbids_question_repetition() -> None:
    messages = build_answer_retry_messages("evidence", "What happened?")
    assert "不能是疑问句" in messages[0]["content"]
    assert "不要翻译或改写问题" in messages[1]["content"]


@pytest.mark.asyncio
async def test_timeout_retry_uses_compact_relevant_context() -> None:
    client = LlamaCppClient(LlmSettings(auto_start=False))
    requests: list[str] = []

    async def fake_complete(messages, *, max_tokens=None):  # type: ignore[no-untyped-def]
        requests.append(messages[1]["content"])
        if len(requests) == 1:
            raise httpx.ReadTimeout("slow")
        return "行李标签可能脱落，自动系统也无法完全避免", time.monotonic()

    client._complete = fake_complete  # type: ignore[method-assign]
    passage = " ".join(
        [f"Unrelated sentence number {index}." for index in range(20)]
        + ["The baggage tag may be torn off on the conveyor belt."]
    )
    try:
        answer = await client.answer(
            QuestionEvent(
                "retry",
                passage,
                "What may happen to the baggage tag?",
                time.monotonic(),
            )
        )
    finally:
        await client.close()

    assert answer.answer.startswith("行李标签")
    assert len(requests) == 2
    assert len(requests[1]) < len(requests[0])
    assert "baggage tag" in requests[1]


@pytest.mark.asyncio
async def test_translate_returns_multisentence_chinese_and_uses_translation_limit() -> None:
    client = LlamaCppClient(LlmSettings(auto_start=False))
    token_limits: list[int | None] = []

    async def fake_complete(messages, *, max_tokens=None):  # type: ignore[no-untyped-def]
        token_limits.append(max_tokens)
        assert "<source>" in messages[1]["content"]
        return "天气很好。你想出去吗？", time.monotonic()

    client._complete = fake_complete  # type: ignore[method-assign]
    try:
        event = await client.translate(
            TranscriptSegment("The weather is nice. Do you want to go out?", 0.0, 2.0),
            "segment-0001",
            max_tokens=96,
        )
    finally:
        await client.close()

    assert event.translated_text == "天气很好。你想出去吗？"
    assert event.source_text.startswith("The weather")
    assert token_limits == [96]
