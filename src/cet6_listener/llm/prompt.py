from __future__ import annotations

import re

SYSTEM_PROMPT = """你是一个英语六级听力理解助手。请只依据给出的英语证据回答当前问题。
严格遵守：
1. 先判断问题询问的主体和答案类型，再寻找能直接填入问题答案位置的原文；
2. 主体、时间、数量、比较关系、肯定否定和趋势方向必须与原文一致；
3. 转折或总结后的直接结论优先于相邻的例子、过程和宽泛背景；
4. 先直接回答核心答案；证据明确时，可补充一个不重复且不矛盾的限定；
5. 只输出一个自然的中文短句，不解释推理、不复述问题、不输出选项字母；
6. 不使用“根据原文”“答案可能是”等前缀，不凭常识补充材料外信息；
7. 控制在12至36个中文字以内，最多不超过48字。"""

TRANSLATION_SYSTEM_PROMPT = """你是实时口译员。把收到的英语语音转写忠实翻译成自然、简洁的中文。
严格遵守：
1. 保留原文的事实、人物、数字、否定、语气和问句形式；
2. 不回答原文中的问题，不解释、不概括、不补充背景；
3. 人名、地名、机构名和术语没有可靠中文译名时可以保留英文；
4. 修正明显的口语断句，但不要遗漏有意义的信息；
5. 只输出中文译文，不添加“翻译如下”等前缀。"""

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|[\r\n]+")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+")
_STOP_WORDS = {
    "a", "about", "according", "an", "and", "are", "be", "been", "being", "can", "could",
    "did", "do", "does", "from", "had", "has", "have", "how", "in", "is", "it", "its",
    "man", "may", "of", "on", "one", "say", "says", "said", "speaker", "that", "the", "their",
    "them", "they", "this", "to", "was", "were", "what", "when", "where", "which", "who",
    "why", "will", "woman", "would",
}

_RELATION_CUES = {
    "reason": {"because", "cause", "due", "reason", "since"},
    "result": {"cause", "consequence", "create", "effect", "lead", "result"},
    "advice": {"advise", "must", "need", "recommend", "should", "suggest"},
    "evaluation": {"attitude", "believe", "consider", "feel", "regard", "think", "view"},
    "importance": {"essential", "important", "key", "matter", "priority", "significant"},
    "change": {"decline", "decrease", "fewer", "grow", "increase", "less", "more", "reduce", "rise"},
    "finding": {"discover", "evidence", "find", "finding", "indicate", "research", "show", "study", "suggest"},
    "action": {"act", "do", "happen", "make", "take"},
    "purpose": {"attention", "educational", "enable", "help", "learning", "support"},
}

_CONTRAST_CUES = (
    " actually ",
    " but ",
    " however ",
    " in fact ",
    " instead ",
    " rather ",
    " the important ",
    " what matters ",
)
_RESOLVED_EVIDENCE = re.compile(r"<condition_resolution>(.*?)</condition_resolution>", re.DOTALL)


def build_messages(passage: str, question: str) -> list[dict[str, str]]:
    guidance = question_guidance(question)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"<transcript>\n{passage}\n</transcript>\n\n"
                f"<question>\n{question}\n</question>\n\n"
                f"<guidance>\n{guidance}\n</guidance>\n\n只输出中文答案。"
            ),
        },
    ]


def build_translation_messages(
    text: str, source_language: str = "English", target_language: str = "Chinese"
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"把下面的 {source_language} 转写翻译成 {target_language}。\n"
                f"<source>\n{text}\n</source>\n只输出译文。"
            ),
        },
    ]


def build_translation_repair_messages(
    raw: str, source_text: str, target_language: str = "Chinese"
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"把候选译文忠实改写为自然的 {target_language}。只输出译文；"
                "不得回答原文中的问题，不得改变人物、数字、否定和事实。"
            ),
        },
        {
            "role": "user",
            "content": f"<source>\n{source_text}\n</source>\n<candidate>\n{raw}\n</candidate>",
        },
    ]


def build_answer_retry_messages(passage: str, question: str) -> list[dict[str, str]]:
    messages = build_messages(passage, question)
    messages[0]["content"] += (
        "\n上一次输出复述了问题。此次必须从证据中提取事实作答；答案必须是陈述句，不能是疑问句。"
    )
    messages[1]["content"] += "\n不要翻译或改写问题，只填写问题所缺少的答案内容。"
    return messages


def extract_resolved_evidence(passage: str) -> str | None:
    """返回已经由确定性规则改写成完整答案的英文证据。"""
    match = _RESOLVED_EVIDENCE.search(passage)
    return " ".join(match.group(1).split()) if match else None


def question_guidance(question: str) -> str:
    folded = " ".join(question.casefold().split())
    guidance: list[str] = []

    if " the woman" in folded or "woman's" in folded or "woman’s" in folded:
        guidance.append("询问对象是女士，只回答女士的观点、状态或行为，不要混入男士的说法")
    elif " the man" in folded or "man's" in folded or "man’s" in folded:
        guidance.append("询问对象是男士，只回答男士的观点、状态或行为，不要混入女士的说法")
    elif "the speaker's team" in folded or "the speaker’s team" in folded:
        guidance.append("询问对象是讲话者团队的研究，回答研究直接显示的结果")
    elif "the speaker" in folded:
        guidance.append("询问对象是讲话者，回答其明确表达的观点或结论")

    if "mainly discuss" in folded or "mainly about" in folded:
        if "by the end" in folded or "at the end" in folded:
            guidance.append("答案类型是结尾核心主题，不要用开头背景替代")
        else:
            guidance.append("答案类型是整段核心主题，不要只复述一个例子")
    elif folded.startswith("why "):
        guidance.append("答案类型是直接原因，优先because、since、due to等因果内容")
    elif "result from" in folded or "lead to" in folded or "can result" in folded:
        guidance.append("答案类型是最终结果；若证据有result、lead to或create，直接回答其结果宾语，保持正负方向，不要用前面的中间影响替代")
    elif "what may happen" in folded or "what happened" in folded:
        guidance.append("答案类型是发生的具体事件，保留may、even when等限制条件")
    elif "must be" in folded:
        guidance.append("答案类型是人物受到的评价或所处状态，直接回答形容词含义，不回答其想法内容")
    elif "think of" in folded or "view about" in folded or "attitude" in folded:
        guidance.append("答案类型是态度或评价，明确正面、负面、合理或不合理")
    elif "advise" in folded or "should " in folded or "must " in folded:
        if "should be included" in folded or "should be added" in folded:
            guidance.append("答案类型是实现目标所需的功能或条件；把if A do not B, not C改写成只有能B的A，必须保留B的完整对象；转折前示例不能直接当答案")
        else:
            guidance.append("答案类型是建议或应采取的行动，使用原文动作，不回答行动的背景")
    elif "increasing number" in folded or "growing number" in folded:
        guidance.append("答案类型是增长人群所做的动作；先用前一句把this、that、second、former或latter替换为所指人群，回答该人群在做什么；as或because后的下降趋势通常只是原因")
    elif "importance" in folded or "important" in folded or "what matters" in folded:
        guidance.append("答案类型是重要的事物或做法；提取matter或important对应的主语或表语，不能把问题翻译成中文")
    elif "signif" in folded or "indicate" in folded:
        guidance.append("答案类型是所体现的现象或趋势，不要把该趋势造成的后果当答案")
    elif folded.startswith("how "):
        if folded.startswith("how did ") or folded.startswith("how was "):
            guidance.append("答案类型是实际过程或做法，按原文回答发生过的动作")
        else:
            guidance.append("答案类型是一般方法、程度或关系；人物个例不能替代一般原则")
    elif "study" in folded or "research" in folded or "finding" in folded:
        guidance.append("答案类型是研究的直接发现；区分实验组，保留比较、比例和增减方向")
    elif "what do we learn" in folded:
        guidance.append("答案类型是关键事实，只保留最能区分选项的身份、状态、变化或结论")
    elif "what is said about" in folded or "what does the speaker say about" in folded:
        guidance.append("回答有区分度的评价、比较或结论，不能只给宽泛定义")
    elif re.search(r"what (?:does|did|will|would) .+ do\b", folded):
        guidance.append("答案类型是具体行为或计划，直接回答动作及必要对象")
    else:
        guidance.append("先给出与问题语法位置直接对应的核心信息")

    guidance.append("最后核对主体、否定词、比较对象和增减方向，不能用相邻句替代直接证据")
    return "；".join(guidance) + "。"


def select_relevant_passage(
    passage: str, question: str, *, max_sentences: int = 8, max_words: int = 260
) -> str:
    """选择问题相关句及邻句，降低长材料中的相邻信息干扰。"""
    sentences = [item.strip() for item in _SENTENCE_SPLIT.split(passage) if item.strip()]
    if not sentences:
        return passage
    terms = _content_terms(question)
    relation_terms = _relation_terms(question)
    scored: list[tuple[int, int]] = []
    for index, sentence in enumerate(sentences):
        words = _content_terms(sentence, keep_common=True)
        score = len(terms & words) * 6
        score += len(relation_terms & words) * 12
        padded = f" {' '.join(sentence.casefold().split())} "
        if any(cue in padded for cue in _CONTRAST_CUES):
            score += 1
        scored.append((score, index))
    ranked = [index for _, index in sorted(scored, key=lambda item: (-item[0], item[1]))]
    if scored and max(score for score, _ in scored) <= 0:
        return passage
    selected: set[int] = set()
    for index in ranked:
        for candidate in (index, index - 1, index + 1):
            if 0 <= candidate < len(sentences):
                selected.add(candidate)
            if len(selected) >= max_sentences:
                break
        if len(selected) >= max_sentences:
            break
    direct_index = ranked[0]
    direct = sentences[direct_index]
    supporting = [sentences[index] for index in sorted(selected) if index != direct_index]
    direct_words = direct.split()
    support_words = " ".join(supporting).split()
    remaining = max(max_words - len(direct_words), 0)
    support_words = support_words[:remaining]
    if not support_words:
        return direct
    folded_question = " ".join(question.casefold().split())
    folded_direct = " ".join(direct.casefold().split())
    if (
        ("should be included" in folded_question or "should be added" in folded_question)
        and folded_direct.startswith(("however", "but", "if "))
    ):
        condition = re.search(
            r"\bif\s+(?P<subject>[^,]+?)\s+"
            r"(?:(?:do|does|will|can|may)\s+not|(?:don't|doesn't|won't|can't))\s+"
            r"(?P<requirement>[^,]+)",
            direct,
            re.IGNORECASE,
        )
        if condition:
            return (
                "<condition_resolution>To support the stated goal, "
                f"{condition.group('subject')} must {condition.group('requirement')}."
                "</condition_resolution>"
            )
        return direct
    reference_hint = ""
    if "second group" in folded_direct:
        resolution = _resolve_second_group(sentences, direct_index)
        reference_hint = f"<reference_resolution>{resolution}</reference_resolution> "
    elif "the former" in folded_direct or "the latter" in folded_direct:
        reference_hint = (
            "<reference_resolution>先按前文列举顺序解析former或latter，再回答该对象</reference_resolution> "
        )
    return (
        f"<supporting_context>{' '.join(support_words)}</supporting_context> "
        f"{reference_hint}"
        f"<likely_direct_evidence>{direct}</likely_direct_evidence>"
    )


def _resolve_second_group(sentences: list[str], direct_index: int) -> str:
    """解析常见的 for some ... for others ... / second group 指代。"""
    previous = " ".join(sentences[max(0, direct_index - 2) : direct_index])
    folded = " ".join(previous.split())
    same_sentence = re.search(
        r"for some\s+(?P<population>[A-Za-z]+),?\s+(?P<activity>.+?)\s+is\s+.+?"
        r"(?:but|while)\s+for others,?\s+(?:it(?:'s| is)?\s+)?(?P<state>[^.]+)",
        folded,
        re.IGNORECASE,
    )
    if same_sentence:
        return (
            "The second group means "
            f"{same_sentence.group('population')} for whom "
            f"{same_sentence.group('activity')} is {same_sentence.group('state')}. "
            "The as/because clause gives the reason, not the group's action."
        )
    split_sentences = re.search(
        r"for some\s+(?P<population>[A-Za-z]+),?\s+(?P<activity>.+?)\s+is\s+[^.]+\.\s*"
        r"for others,?\s+(?:it(?:'s| is)?\s+)?(?P<state>[^.]+)",
        folded,
        re.IGNORECASE,
    )
    if split_sentences:
        return (
            "The second group means "
            f"{split_sentences.group('population')} for whom "
            f"{split_sentences.group('activity')} is {split_sentences.group('state')}. "
            "The as/because clause gives the reason, not the group's action."
        )
    return (
        "The second group refers to the people described by 'for others' in the preceding context, "
        "not the different people in the as/because clause."
    )


def _content_terms(text: str, *, keep_common: bool = False) -> set[str]:
    terms: set[str] = set()
    for raw in _WORD.findall(text):
        word = raw.casefold()
        if len(word) <= 2:
            continue
        if not keep_common and word in _STOP_WORDS:
            continue
        terms.add(_stem(word))
    return terms


def _stem(word: str) -> str:
    """轻量归一化，覆盖听力题中常见的单复数和时态变化。"""
    if len(word) > 5 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 6 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 5 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 5 and word.endswith("es"):
        return word[:-2]
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _relation_terms(question: str) -> set[str]:
    folded = " ".join(question.casefold().split())
    groups: list[str] = []
    if folded.startswith("why ") or "reason" in folded:
        groups.append("reason")
    if "result" in folded or "lead to" in folded or "happen" in folded:
        groups.append("result")
    if "advise" in folded or "should" in folded or "must" in folded:
        groups.append("advice")
    if "think" in folded or "view" in folded or "attitude" in folded:
        groups.append("evaluation")
    if "important" in folded or "importance" in folded or "key" in folded or "matter" in folded:
        groups.append("importance")
    if (
        "more" in folded
        or "less" in folded
        or "increas" in folded
        or "decreas" in folded
        or "level" in folded
        or "trend" in folded
    ):
        groups.append("change")
    if "study" in folded or "research" in folded or "finding" in folded:
        groups.append("finding")
    if re.search(r"\b(?:do|did|happen|make|take)\b", folded):
        groups.append("action")
    if "learning" in folded or "bolster" in folded or "in order to" in folded:
        groups.append("purpose")
    return {_stem(term) for group in groups for term in _RELATION_CUES[group]}


def build_chinese_repair_messages(answer: str, question: str = "") -> list[dict[str, str]]:
    """忠实翻译不合格答案，不在修复阶段重新推理。"""
    return [
        {
            "role": "system",
            "content": (
                "你是忠实翻译器，不是答题者。只输出15至35个中文字的中文译文，不解释，不输出英文字母。"
                "英文名称、缩写和术语应尽量意译成自然中文，不要机械保留字母。"
                "保留原答案的每个名词、动作和修饰关系，不得概括成更宽泛的词。"
                "不得用“负面事物”“消极影响”等笼统词替代具体名词。"
                "原文中的每个实义名词和of修饰短语都必须在译文中体现，不得复述问题来替代翻译。"
                "例如a persistent decline in trust应译为“信任持续下降”，不能译为“负面变化”。"
                "不得改变、删减、补充或重新判断原答案的含义。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"问题语境：{question}\n" if question else ""
            ) + f"忠实翻译下面的答案短语，只输出中文译文：\n{answer}",
        },
    ]
