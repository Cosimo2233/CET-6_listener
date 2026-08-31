from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import psutil

from cet6_listener.asr.base import AsrBackend
from cet6_listener.audio.base import AudioSource
from cet6_listener.audio.vad import EnergyVad
from cet6_listener.config import AppSettings
from cet6_listener.domain.events import AudioFrame, TranscriptSegment, TranslationEvent
from cet6_listener.llm.client import LlamaCppClient, LlmError
from cet6_listener.tts.grpc_client import GrpcTtsClient, TtsError
from cet6_listener.tts.player import AlsaPcmPlayer, PlaybackError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranslationMetrics:
    audio_seconds: float
    wall_seconds: float
    transcript_segments: int
    translations: int
    peak_rss_mb: float

    @property
    def realtime_factor(self) -> float:
        return self.wall_seconds / self.audio_seconds if self.audio_seconds else 0.0


class TranslationPipeline:
    """按 VAD 语音段执行英文识别、中文翻译和顺序 TTS 播放。"""

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
        self._audio_queue: asyncio.Queue[AudioFrame] = asyncio.Queue(
            settings.pipeline.audio_queue_size
        )
        self._transcript_queue: asyncio.Queue[TranscriptSegment | None] = asyncio.Queue(
            settings.translation.queue_size
        )
        self._translation_queue: asyncio.Queue[TranslationEvent | None] = asyncio.Queue(
            settings.translation.queue_size
        )
        self._audio_seconds = 0.0
        self._transcript_count = 0
        self._translation_count = 0
        self._peak_rss = 0

    async def run(self) -> TranslationMetrics:
        started = time.monotonic()
        monitor_stop = asyncio.Event()
        monitor = asyncio.create_task(self._monitor_memory(monitor_stop), name="memory-monitor")
        try:
            await self._asr.start()
            await self._llm.start()
            if not self._dry_run:
                if self._tts is None or self._player is None:
                    raise RuntimeError("非 dry-run 翻译模式必须配置 TTS 和播放器。")
                await self._tts.prepare()
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(self._produce_audio(), name="audio-producer")
                tasks.create_task(self._recognize(), name="asr-worker")
                tasks.create_task(self._translate(), name="translation-worker")
                tasks.create_task(self._speak(), name="tts-worker")
        finally:
            monitor_stop.set()
            await monitor
            await self._source.close()
            await self._asr.close()
            await self._llm.close()
            if self._tts is not None:
                await self._tts.close()
            if self._player is not None:
                await self._player.close()

        metrics = TranslationMetrics(
            audio_seconds=self._audio_seconds,
            wall_seconds=time.monotonic() - started,
            transcript_segments=self._transcript_count,
            translations=self._translation_count,
            peak_rss_mb=self._peak_rss / 1024 / 1024,
        )
        logger.info(
            "[TRANSLATION_METRICS] audio=%.2fs wall=%.2fs rtf=%.3f peak_rss_mb=%.1f transcripts=%d translations=%d",
            metrics.audio_seconds,
            metrics.wall_seconds,
            metrics.realtime_factor,
            metrics.peak_rss_mb,
            metrics.transcript_segments,
            metrics.translations,
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
                if transcript.text.strip():
                    self._transcript_count += 1
                    logger.info(
                        "[ASR] %.2f-%.2f %s",
                        transcript.start_time,
                        transcript.end_time,
                        transcript.text,
                    )
                    await self._transcript_queue.put(transcript)
            if frame.eof:
                await self._transcript_queue.put(None)
                return

    async def _translate(self) -> None:
        sequence = 0
        while True:
            segment = await self._transcript_queue.get()
            if segment is None:
                await self._translation_queue.put(None)
                return
            sequence += 1
            segment_id = f"segment-{sequence:04d}"
            try:
                event = await self._llm.translate(
                    segment,
                    segment_id,
                    source_language=self._settings.translation.source_language,
                    target_language=self._settings.translation.target_language,
                    max_tokens=self._settings.translation.max_tokens,
                    max_characters=self._settings.translation.max_characters,
                )
            except LlmError as exc:
                logger.error("[TRANSLATE] segment=%s failed: %s", segment_id, exc)
                continue
            self._translation_count += 1
            await self._translation_queue.put(event)

    async def _speak(self) -> None:
        while True:
            event = await self._translation_queue.get()
            if event is None:
                return
            first_token_ms = (
                (event.first_token_at - event.request_started_at) * 1000
                if event.first_token_at is not None
                else -1
            )
            logger.info(
                "[TRANSLATION_LATENCY] id=%s first_token_ms=%.1f total_ms=%.1f",
                event.segment_id,
                first_token_ms,
                (event.completed_at - event.request_started_at) * 1000,
            )
            logger.info("SOURCE: %s", event.source_text)
            logger.info("TRANSLATION: %s", event.translated_text)
            if self._dry_run:
                continue
            assert self._tts is not None and self._player is not None
            try:
                chunks = self._tts.synthesize(
                    f"{self._settings.tts.prefix}{event.translated_text}"
                )
                playback = await self._player.play(event.segment_id, chunks)
                logger.info(
                    "[TRANSLATION_LATENCY] id=%s request_to_tts_start_ms=%.1f playback_ms=%.1f",
                    event.segment_id,
                    (playback.started_at - event.request_started_at) * 1000,
                    (playback.completed_at - playback.started_at) * 1000,
                )
            except (TtsError, PlaybackError, OSError) as exc:
                logger.error("[TTS] segment=%s failed: %s", event.segment_id, exc)
