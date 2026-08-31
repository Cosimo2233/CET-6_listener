from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TypeVar

import psutil

from cet6_listener.asr.base import AsrBackend
from cet6_listener.audio.base import AudioSource
from cet6_listener.audio.vad import EnergyVad
from cet6_listener.config import AppSettings
from cet6_listener.detector.question_detector import QuestionDetector
from cet6_listener.domain.events import (
    AnswerEvent,
    AnswerPhase,
    AudioFrame,
    ListeningPhase,
    QuestionEvent,
    TranscriptSegment,
)
from cet6_listener.llm.client import LlamaCppClient, LlmError
from cet6_listener.pipeline.state import PipelineState
from cet6_listener.transcript.manager import TranscriptManager
from cet6_listener.tts.grpc_client import GrpcTtsClient, TtsError
from cet6_listener.tts.player import AlsaPcmPlayer, PlaybackError

logger = logging.getLogger(__name__)
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PipelineMetrics:
    audio_seconds: float
    wall_seconds: float
    transcript_segments: int
    questions: int
    answers: int
    peak_rss_mb: float

    @property
    def realtime_factor(self) -> float:
        return self.wall_seconds / self.audio_seconds if self.audio_seconds else 0.0


class RealtimePipeline:
    def __init__(
        self,
        settings: AppSettings,
        source: AudioSource,
        asr: AsrBackend,
        llm: LlamaCppClient,
        *,
        dry_run: bool = False,
        tts: GrpcTtsClient | None = None,
        player: AlsaPcmPlayer | None = None,
    ) -> None:
        self._settings = settings
        self._source = source
        self._asr = asr
        self._llm = llm
        self._dry_run = dry_run
        self._tts = tts
        self._player = player
        self._state = PipelineState()
        self._audio_queue: asyncio.Queue[AudioFrame] = asyncio.Queue(settings.pipeline.audio_queue_size)
        self._transcript_queue: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue()
        self._question_queue: asyncio.Queue[QuestionEvent | None] = asyncio.Queue(settings.pipeline.question_queue_size)
        self._answer_queue: asyncio.Queue[AnswerEvent | None] = asyncio.Queue(settings.pipeline.answer_queue_size)
        self._audio_seconds = 0.0
        self._transcript_count = 0
        self._question_count = 0
        self._answer_count = 0
        self._peak_rss = 0

    async def run(self) -> PipelineMetrics:
        started = time.monotonic()
        monitor_stop = asyncio.Event()
        monitor = asyncio.create_task(self._monitor_memory(monitor_stop), name="memory-monitor")
        try:
            await self._asr.start()
            await self._llm.start()
            if not self._dry_run:
                if self._tts is None or self._player is None:
                    raise RuntimeError("非 dry-run 模式必须配置 TTS 和播放器。")
                await self._tts.prepare()
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._produce_audio(), name="audio-producer")
                tasks.create_task(self._recognize(), name="asr-worker")
                tasks.create_task(self._detect_questions(), name="question-detector")
                tasks.create_task(self._generate_answers(), name="llm-worker")
                tasks.create_task(self._speak_answers(), name="tts-worker")
        finally:
            monitor_stop.set()
            await monitor
            self._state.set_listening(ListeningPhase.IDLE)
            self._state.set_answer(AnswerPhase.IDLE)
            await self._source.close()
            await self._asr.close()
            await self._llm.close()
            if self._tts is not None:
                await self._tts.close()
            if self._player is not None:
                await self._player.close()
        metrics = PipelineMetrics(
            audio_seconds=self._audio_seconds,
            wall_seconds=time.monotonic() - started,
            transcript_segments=self._transcript_count,
            questions=self._question_count,
            answers=self._answer_count,
            peak_rss_mb=self._peak_rss / 1024 / 1024,
        )
        logger.info(
            "[METRICS] audio=%.2fs wall=%.2fs rtf=%.3f peak_rss_mb=%.1f transcripts=%d questions=%d answers=%d",
            metrics.audio_seconds,
            metrics.wall_seconds,
            metrics.realtime_factor,
            metrics.peak_rss_mb,
            metrics.transcript_segments,
            metrics.questions,
            metrics.answers,
        )
        return metrics

    async def _monitor_memory(self, stop: asyncio.Event) -> None:
        process = psutil.Process()
        while True:
            try:
                rss = process.memory_info().rss
                rss += sum(child.memory_info().rss for child in process.children(recursive=True))
                self._peak_rss = max(self._peak_rss, rss)
            except (psutil.Error, OSError):
                pass
            if stop.is_set():
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                continue

    async def _produce_audio(self) -> None:
        async for frame in self._source.frames():
            self._audio_seconds = max(self._audio_seconds, frame.timestamp + frame.duration)
            await self._audio_queue.put(frame)

    async def _recognize(self) -> None:
        vad = EnergyVad(self._settings.audio, self._settings.vad)
        while True:
            frame = await self._audio_queue.get()
            speech = vad.consume(frame)
            if speech is not None:
                transcript = await self._asr.transcribe(speech)
                if transcript.text:
                    self._transcript_count += 1
                    logger.info("[ASR] %.2f-%.2f %s", transcript.start_time, transcript.end_time, transcript.text)
                    await self._transcript_queue.put(transcript)
            if frame.eof:
                await self._transcript_queue.put(None)
                return

    async def _detect_questions(self) -> None:
        manager = TranscriptManager(self._settings.pipeline.context_word_limit)
        detector = QuestionDetector(manager, self._settings.pipeline.max_question_seconds)
        self._state.set_listening(ListeningPhase.PASSAGE)
        last_end = 0.0
        while True:
            segment = await self._transcript_queue.get()
            if segment is None:
                event = detector.flush(last_end)
                if event is not None:
                    await self._emit_question(event)
                await self._question_queue.put(None)
                return
            last_end = segment.end_time
            event = detector.consume(segment)
            self._state.set_listening(
                ListeningPhase.QUESTION if detector.collecting else ListeningPhase.PASSAGE
            )
            if event is not None:
                await self._emit_question(event)

    async def _emit_question(self, event: QuestionEvent) -> None:
        self._question_count += 1
        logger.info("[QUESTION] id=%s %s", event.question_id, event.question)
        logger.info("[CONTEXT] words=%d", len(event.passage.split()))
        await _put_latest(self._question_queue, event)

    async def _generate_answers(self) -> None:
        while True:
            event = await self._question_queue.get()
            if event is None:
                await self._answer_queue.put(None)
                return
            self._state.set_answer(AnswerPhase.GENERATING)
            try:
                answer = await self._llm.answer(event)
            except LlmError as exc:
                logger.error("[LLM] question=%s failed: %s", event.question_id, exc)
                self._state.set_answer(AnswerPhase.IDLE)
                continue
            self._answer_count += 1
            await _put_latest(self._answer_queue, answer)

    async def _speak_answers(self) -> None:
        while True:
            event = await self._answer_queue.get()
            if event is None:
                self._state.set_answer(AnswerPhase.IDLE)
                return
            first_token_ms = (
                (event.first_token_at - event.question_ended_at) * 1000
                if event.first_token_at is not None
                else -1
            )
            logger.info(
                "[LATENCY] id=%s llm_first_token_ms=%.1f llm_total_ms=%.1f",
                event.question_id,
                first_token_ms,
                (event.completed_at - event.request_started_at) * 1000,
            )
            if self._dry_run:
                logger.info("QUESTION: %s", event.question)
                logger.info("ANSWER: %s", event.answer)
                self._state.set_answer(AnswerPhase.IDLE)
                continue
            assert self._tts is not None and self._player is not None
            self._state.set_answer(AnswerPhase.SPEAKING)
            try:
                chunks = self._tts.synthesize(f"{self._settings.tts.prefix}{event.answer}")
                playback = await self._player.play(event.question_id, chunks)
                logger.info(
                    "[LATENCY] id=%s question_to_tts_start_ms=%.1f playback_ms=%.1f",
                    event.question_id,
                    (playback.started_at - event.question_ended_at) * 1000,
                    (playback.completed_at - playback.started_at) * 1000,
                )
            except (TtsError, PlaybackError, OSError) as exc:
                logger.error("[TTS] question=%s failed: %s", event.question_id, exc)
            self._state.set_answer(AnswerPhase.IDLE)


async def _put_latest(queue: asyncio.Queue[T | None], item: T) -> None:
    if queue.full():
        dropped = queue.get_nowait()
        logger.warning("[QUEUE] 队列已满，丢弃最旧项目：%s", getattr(dropped, "question_id", dropped))
    queue.put_nowait(item)
