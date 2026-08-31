from __future__ import annotations

import time
from array import array
from collections.abc import AsyncIterator

import pytest

from cet6_listener.config import AppSettings
from cet6_listener.domain.events import (
    AnswerEvent,
    AudioFrame,
    PcmChunk,
    PlaybackEvent,
    SpeechSegment,
    TranscriptSegment,
    TranslationEvent,
)
from cet6_listener.pipeline.realtime import RealtimePipeline
from cet6_listener.pipeline.translation import TranslationPipeline
from cet6_listener.llm.client import LlmError


class FakeSource:
    async def frames(self) -> AsyncIterator[AudioFrame]:
        values = [1000] * 5 + [0] * 30 + [1000] * 5 + [0] * 30
        for index, value in enumerate(values):
            yield AudioFrame(array("h", [value] * 320).tobytes(), index * 0.02, 0.02)
        yield AudioFrame(b"", len(values) * 0.02, 0, True)

    async def close(self) -> None:
        return None


class FakeAsr:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def start(self) -> None:
        return None

    async def transcribe(self, segment: SpeechSegment) -> TranscriptSegment:
        texts = [
            "The woman has applied for a position at another company.",
            "Question 1. What is the woman planning to do?",
        ]
        text = texts[self.calls]
        self.calls += 1
        return TranscriptSegment(text, segment.start_time, segment.end_time)

    async def close(self) -> None:
        self.closed = True


class FakeLlm:
    def __init__(self) -> None:
        self.closed = False

    async def start(self) -> None:
        return None

    async def answer(self, event):  # type: ignore[no-untyped-def]
        now = time.monotonic()
        return AnswerEvent(event.question_id, event.question, "换一份工作", event.ended_at, now, now, now)

    async def translate(self, segment, segment_id, **_kwargs):  # type: ignore[no-untyped-def]
        now = time.monotonic()
        return TranslationEvent(
            segment_id,
            segment.text,
            f"译文{segment_id}",
            segment.end_time,
            now,
            now,
            now,
        )

    async def close(self) -> None:
        self.closed = True


class FailingLlm(FakeLlm):
    async def start(self) -> None:
        raise LlmError("startup failed")


class FakeTts:
    def __init__(self) -> None:
        self.prepared = False
        self.closed = False

    async def prepare(self) -> str:
        self.prepared = True
        return "fake-voice"

    async def synthesize(self, _text: str):  # type: ignore[no-untyped-def]
        yield PcmChunk(b"\x00\x00" * 100, 16000, 0)

    async def close(self) -> None:
        self.closed = True


class FakePlayer:
    def __init__(self) -> None:
        self.bytes_played = 0
        self.closed = False

    async def play(self, question_id: str, chunks):  # type: ignore[no-untyped-def]
        started = time.monotonic()
        async for chunk in chunks:
            self.bytes_played += len(chunk.data)
        return PlaybackEvent(question_id, started, time.monotonic())

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_dry_run_pipeline_completes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "config.yaml"
    config.write_text(
        "vad:\n  rms_threshold: 400\n  prefix_ms: 20\n  silence_ms: 600\n  max_speech_seconds: 20\n",
        encoding="utf-8",
    )
    settings = AppSettings.load(config, tmp_path / "missing.env")
    source = FakeSource()
    asr = FakeAsr()
    llm = FakeLlm()
    pipeline = RealtimePipeline(settings, source, asr, llm, dry_run=True)  # type: ignore[arg-type]

    metrics = await pipeline.run()

    assert metrics.transcript_segments == 2
    assert metrics.questions == 1
    assert metrics.answers == 1
    assert metrics.peak_rss_mb > 0
    assert asr.closed
    assert llm.closed


@pytest.mark.asyncio
async def test_full_fake_pipeline_streams_tts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "config.yaml"
    config.write_text(
        "vad:\n  rms_threshold: 400\n  prefix_ms: 20\n  silence_ms: 600\n  max_speech_seconds: 20\n",
        encoding="utf-8",
    )
    settings = AppSettings.load(config, tmp_path / "missing.env")
    tts = FakeTts()
    player = FakePlayer()
    pipeline = RealtimePipeline(
        settings,
        FakeSource(),
        FakeAsr(),
        FakeLlm(),  # type: ignore[arg-type]
        tts=tts,  # type: ignore[arg-type]
        player=player,  # type: ignore[arg-type]
    )

    metrics = await pipeline.run()

    assert metrics.answers == 1
    assert tts.prepared and tts.closed
    assert player.bytes_played == 200
    assert player.closed


@pytest.mark.asyncio
async def test_startup_failure_still_closes_started_backends(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "config.yaml"
    config.write_text("{}\n", encoding="utf-8")
    settings = AppSettings.load(config, tmp_path / "missing.env")
    asr = FakeAsr()
    llm = FailingLlm()
    pipeline = RealtimePipeline(settings, FakeSource(), asr, llm, dry_run=True)  # type: ignore[arg-type]

    with pytest.raises(LlmError, match="startup failed"):
        await pipeline.run()

    assert asr.closed
    assert llm.closed


@pytest.mark.asyncio
async def test_translation_pipeline_translates_every_segment_and_streams_tts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = tmp_path / "config.yaml"
    config.write_text(
        "vad:\n  rms_threshold: 400\n  prefix_ms: 20\n  silence_ms: 600\n  max_speech_seconds: 20\n",
        encoding="utf-8",
    )
    settings = AppSettings.load(config, tmp_path / "missing.env")
    source = FakeSource()
    asr = FakeAsr()
    llm = FakeLlm()
    tts = FakeTts()
    player = FakePlayer()
    pipeline = TranslationPipeline(
        settings,
        source,
        asr,
        llm,  # type: ignore[arg-type]
        tts=tts,  # type: ignore[arg-type]
        player=player,  # type: ignore[arg-type]
    )

    metrics = await pipeline.run()

    assert metrics.transcript_segments == 2
    assert metrics.translations == 2
    assert player.bytes_played == 400
    assert tts.prepared and tts.closed
    assert asr.closed and llm.closed and player.closed
