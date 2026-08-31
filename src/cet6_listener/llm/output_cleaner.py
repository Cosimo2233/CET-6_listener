from __future__ import annotations

import re

_PREFIX = re.compile(
    r"^(?:答案(?:是|为)?|我认为|我觉得|可能是|答案可能是|根据原文)[：:，,\s]*",
    re.IGNORECASE,
)
_MARKDOWN = re.compile(r"[*_`#>|]+")
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-z]")
_PROMPT_ECHO = re.compile(r"(?:候选证据|相关度排序|完整听力内容|当前问题|本题要求)")
_ENGLISH_QUESTION = re.compile(
    r"^(?:(?:what|which|who)\s+(?:is|are|was|were|do|does|did|can|could|should|would|will|has|have)\b|"
    r"(?:why|how|when|where)\s+(?:is|are|was|were|do|does|did|can|could|should|would|will|has|have)\b|"
    r"(?:do|does|did|is|are|was|were|can|could|should|would|will|has|have)\b)",
    re.IGNORECASE,
)
_CHINESE_QUESTION_ECHO = re.compile(r"(?:什么才是|是什么|为什么|有何|做什么|如何\??$)")
_TRANSLATION_PREFIX = re.compile(
    r"^(?:翻译(?:结果|如下)?|中文(?:翻译|译文)?|译文)[：:\s]*",
    re.IGNORECASE,
)


def contains_chinese(text: str) -> bool:
    """答案以中文为主，避免夹一个汉字的英文句子绕过校验。"""
    chinese_count = len(_CJK.findall(text))
    latin_count = len(_LATIN.findall(text))
    return chinese_count >= 2 and chinese_count >= latin_count


def is_usable_answer(text: str) -> bool:
    """中文内容且没有复述内部提示语。"""
    return (
        contains_chinese(text)
        and _PROMPT_ECHO.search(text) is None
        and not looks_like_question(text)
        and not has_excessive_repetition(text)
    )


def looks_like_question(text: str) -> bool:
    """识别模型复述/翻译题目而没有作答的退化输出。"""
    stripped = text.strip(" \t\r\n。！？!?：:")
    return bool(_ENGLISH_QUESTION.match(stripped) or _CHINESE_QUESTION_ECHO.search(stripped))


def has_excessive_repetition(text: str) -> bool:
    """拦截小模型循环生成同一短语的退化输出。"""
    compact = re.sub(r"[\s，,。！？!?：:；;]", "", text)
    if len(compact) < 24:
        return False
    return any(compact.count(compact[index : index + 8]) >= 3 for index in range(len(compact) - 7))


def clean_answer(raw: str, max_characters: int = 48) -> str:
    text = _MARKDOWN.sub("", raw).strip()
    text = text.strip("\"'“”‘’[]【】()（）")
    for _ in range(2):
        text = _PREFIX.sub("", text).strip()
    text = re.split(r"[\n\r。！？!?；;]", text, maxsplit=1)[0]
    text = text.strip("\"'“”‘’[]【】()（）")
    if contains_chinese(text):
        text = re.sub(r"\s+", "", text)
    else:
        text = re.sub(r"\s+", " ", text)
    if len(text) <= max_characters:
        return text
    boundaries = [
        index
        for index, character in enumerate(text[: max_characters + 1])
        if character in "，,：:" and index >= max_characters // 2
    ]
    if boundaries:
        return text[: boundaries[-1]]
    return text[:max_characters]


def clean_translation(raw: str, max_characters: int = 240) -> str:
    """清理多句译文，但保留原文的问句和句间标点。"""
    text = _MARKDOWN.sub("", raw).strip()
    text = text.strip("\"'“”‘’[]【】")
    text = _TRANSLATION_PREFIX.sub("", text).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(
        r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])\s+|\s+(?=[\u3400-\u4dbf\u4e00-\u9fff])",
        "",
        text,
    )
    text = re.sub(r"\s+([，。！？；：、,.!?;:])", r"\1", text)
    if len(text) <= max_characters:
        return text
    boundaries = [
        index
        for index, character in enumerate(text[: max_characters + 1])
        if character in "。！？!?；;，,"
        and index >= max_characters * 2 // 3
    ]
    return text[: boundaries[-1] + 1 if boundaries else max_characters]


def is_usable_translation(text: str) -> bool:
    """译文可以是疑问句，但必须以中文为主且不能循环或泄漏提示。"""
    return (
        contains_chinese(text)
        and _PROMPT_ECHO.search(text) is None
        and not has_excessive_repetition(text)
    )
