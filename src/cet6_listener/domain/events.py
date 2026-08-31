from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class AudioFrame:
    data: bytes
    timestamp: float
    duration: float
    eof: bool = False


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    pcm_s16le: bytes
    start_time: float
    end_time: float
    sample_rate: int


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    text: str
    start_time: float
    end_time: float
    is_final: bool = True


@dataclass(frozen=True, slots=True)
class QuestionEvent:
    question_id: str
    passage: str
    question: str
    ended_at: float


@dataclass(frozen=True, slots=True)
class AnswerEvent:
    question_id: str
    question: str
    answer: str
    question_ended_at: float
    request_started_at: float
    first_token_at: float | None
    completed_at: float


@dataclass(frozen=True, slots=True)
class TranslationEvent:
    segment_id: str
    source_text: str
    translated_text: str
    segment_ended_at: float
    request_started_at: float
    first_token_at: float | None
    completed_at: float


@dataclass(frozen=True, slots=True)
class PcmChunk:
    data: bytes
    sample_rate: int
    chunk_index: int


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    question_id: str
    started_at: float
    completed_at: float


class ListeningPhase(StrEnum):
    IDLE = "IDLE"
    PASSAGE = "PASSAGE"
    QUESTION = "QUESTION"


class AnswerPhase(StrEnum):
    IDLE = "IDLE"
    GENERATING = "GENERATING"
    SPEAKING = "SPEAKING"
