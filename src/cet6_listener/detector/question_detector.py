from __future__ import annotations

import re
import time
import uuid

from cet6_listener.domain.events import QuestionEvent, TranscriptSegment
from cet6_listener.transcript.manager import TranscriptManager

_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
_QUESTION_MARKER = re.compile(
    r"\bquestion\s+(?P<number>\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\b[\s.,:;-]*",
    re.IGNORECASE,
)
_GROUP_MARKER = re.compile(
    r"\bquestions?\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
    r"(?:to|through|and|[-–—])\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"are\s+based\s+on\b",
    re.IGNORECASE,
)
_CONTENT_MARKER = re.compile(
    r"^(?:conversation|passage|recording)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_DIRECT_QUESTION = re.compile(
    r"^(?:what|why|how|where|when|who|whom|whose|which|does|do|did|is|are|was|were|can|could|would|will)\b",
    re.IGNORECASE,
)
_TYPICAL_STEM = re.compile(
    r"\b(?:what\s+can\s+we\s+learn|what\s+does\s+(?:the\s+)?(?:man|woman|speaker)|"
    r"what\s+can\s+be\s+inferred|where\s+does\s+the\s+conversation|"
    r"what\s+is\s+the\s+speaker\s+mainly|why\s+does\s+the\s+speaker)\b",
    re.IGNORECASE,
)


class QuestionDetector:
    def __init__(self, transcript: TranscriptManager, max_question_seconds: float = 20) -> None:
        self._transcript = transcript
        self._max_seconds = max_question_seconds
        self._question_parts: list[str] = []
        self._question_started_at: float | None = None
        self._number = ""
        self._question_mode = False

    @property
    def collecting(self) -> bool:
        return self._question_started_at is not None

    def consume(self, segment: TranscriptSegment) -> QuestionEvent | None:
        text = " ".join(segment.text.split())
        if not text:
            return None

        suppress_prefix = False
        content = _CONTENT_MARKER.search(text)
        if content:
            self._transcript.reset()
            self._cancel_question()
            self._question_mode = False
            suppress_prefix = True
            if _QUESTION_MARKER.search(text, content.end()) is None:
                return None

        group = _GROUP_MARKER.search(text)
        if group:
            self._cancel_question()
            self._question_mode = True
            suppress_prefix = True
            if _QUESTION_MARKER.search(text, group.end()) is None:
                return None

        marker = _QUESTION_MARKER.search(text)
        if marker:
            prefix = text[: marker.start()].strip()
            if prefix and not suppress_prefix:
                self._transcript.append_passage(prefix)
            self._start(segment.start_time, marker.group("number"))
            remainder = text[marker.end() :].strip()
            if remainder:
                self._question_parts.append(remainder)
            return self._finish_if_complete(segment.end_time)

        if self.collecting:
            self._question_parts.append(text)
            if segment.end_time - (self._question_started_at or segment.start_time) > self._max_seconds:
                self._cancel_question()
                return None
            return self._finish_if_complete(segment.end_time)

        if self._question_mode and _DIRECT_QUESTION.search(text) and (
            _TYPICAL_STEM.search(text) or text.endswith("?")
        ):
            self._start(segment.start_time, "")
            self._question_parts.append(text)
            return self._finish_if_complete(segment.end_time)

        self._transcript.append_passage(text)
        return None

    def flush(self, ended_at: float) -> QuestionEvent | None:
        return self._finish_if_complete(ended_at, force=True)

    def _start(self, started_at: float, number: str) -> None:
        self._question_parts.clear()
        self._question_started_at = started_at
        folded = number.casefold()
        self._number = _NUMBER_WORDS.get(folded, number)

    def _finish_if_complete(self, ended_at: float, *, force: bool = False) -> QuestionEvent | None:
        question = " ".join(self._question_parts).strip()
        complete = len(question.split()) >= 4 and (
            bool(self._number) or self._looks_complete(question)
        )
        if not question or (not force and not complete):
            return None
        identifier = self._number or uuid.uuid4().hex[:8]
        event = QuestionEvent(
            question_id=identifier,
            passage=self._transcript.snapshot(),
            question=question,
            ended_at=time.monotonic(),
        )
        self._cancel_question()
        return event

    @staticmethod
    def _looks_complete(question: str) -> bool:
        return bool(_DIRECT_QUESTION.search(question) or _TYPICAL_STEM.search(question)) and len(question.split()) >= 4

    def _cancel_question(self) -> None:
        self._question_parts.clear()
        self._question_started_at = None
        self._number = ""
