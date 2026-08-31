from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import grpc

from cet6_listener.config import TtsSettings
from cet6_listener.domain.events import PcmChunk
from cet6_listener.protos.tts import preset_voice_pb2, preset_voice_pb2_grpc, tts_pb2, tts_pb2_grpc

logger = logging.getLogger(__name__)


class TtsError(RuntimeError):
    """gRPC TTS 调用失败。"""


@dataclass(frozen=True, slots=True)
class PresetVoice:
    voice_id: str
    name: str
    language: str


class GrpcTtsClient:
    def __init__(self, settings: TtsSettings) -> None:
        self._settings = settings
        self._channel = grpc.aio.insecure_channel(settings.target)
        self._voice_stub = preset_voice_pb2_grpc.PresetVoiceServiceStub(self._channel)
        self._tts_stub = tts_pb2_grpc.TtsServiceStub(self._channel)
        self._serving_mode = ""
        self._voice_id = ""
        self._voice_names: dict[str, str] = {}
        self._active_call: Any | None = None

    async def list_voices(self) -> list[PresetVoice]:
        try:
            response = await self._voice_stub.ListPresetVoices(
                preset_voice_pb2.ListPresetVoicesRequest(), timeout=self._settings.timeout_seconds
            )
        except grpc.aio.AioRpcError as exc:
            raise TtsError(f"查询音色失败：{exc.details() or exc.code().name}") from exc
        self._serving_mode = response.serving_mode.strip().casefold()
        self._voice_names = {
            item.voice_id: item.name for item in response.voices if item.voice_id and item.name
        }
        duplex = self._serving_mode == "duplex"
        voices = [
            PresetVoice(item.voice_id, item.name, item.language)
            for item in response.voices
            if item.available_on_instance and (item.supports_duplex if duplex else item.supports_synthesize)
        ]
        return sorted(voices, key=lambda item: (item.language, item.name, item.voice_id))

    async def prepare(self) -> str:
        voices = await self.list_voices()
        if self._settings.voice_id:
            match = next((voice for voice in voices if voice.voice_id == self._settings.voice_id), None)
            if match is None:
                raise TtsError(f"配置的音色不可用：{self._settings.voice_id}")
        else:
            match = next((voice for voice in voices if _language_matches(voice.language, self._settings.language)), None)
            if match is None:
                raise TtsError(f"服务没有可用的 {self._settings.language} 音色，请配置 TTS_VOICE_ID。")
        self._voice_id = match.voice_id
        logger.info("[TTS] voice=%s name=%s language=%s mode=%s", match.voice_id, match.name, match.language, self._serving_mode)
        return match.voice_id

    async def synthesize(self, text: str) -> AsyncIterator[PcmChunk]:
        if not self._voice_id:
            await self.prepare()
        if self._serving_mode == "duplex":
            preset = self._voice_names.get(self._voice_id, self._voice_id)
            call = self._tts_stub.DuplexSynthesize(
                self._duplex_requests(text, preset), timeout=self._settings.timeout_seconds
            )
        else:
            call = self._tts_stub.Synthesize(
                tts_pb2.SynthesizeRequest(
                    voice=tts_pb2.VoiceSource(preset_voice_id=self._voice_id),
                    text=text,
                    language=self._settings.language,
                    decoder_chunk_size=self._settings.decoder_chunk_size,
                ),
                timeout=self._settings.timeout_seconds,
            )
        self._active_call = call
        expected_index: int | None = None
        sample_rate: int | None = None
        try:
            async for response in call:
                index = int(response.chunk_index)
                if expected_index is None:
                    expected_index = index
                if index != expected_index:
                    raise TtsError(f"TTS 音频块序号异常：期望 {expected_index}，收到 {index}。")
                expected_index += 1
                if response.sample_rate <= 0:
                    raise TtsError("TTS 返回了无效采样率。")
                if sample_rate is None:
                    sample_rate = response.sample_rate
                elif response.sample_rate != sample_rate:
                    raise TtsError("TTS 流中途改变了采样率。")
                if response.pcm_s16le:
                    yield PcmChunk(bytes(response.pcm_s16le), response.sample_rate, index)
        except asyncio.CancelledError:
            call.cancel()
            raise
        except grpc.aio.AioRpcError as exc:
            if exc.code() is not grpc.StatusCode.CANCELLED:
                raise TtsError(f"语音合成失败：{exc.details() or exc.code().name}") from exc
        finally:
            if self._active_call is call:
                self._active_call = None

    async def _duplex_requests(self, text: str, preset: str) -> AsyncIterator[Any]:
        yield tts_pb2.DuplexSynthesizeRequest(
            config=tts_pb2.DuplexStreamConfig(
                voice=tts_pb2.VoiceSource(preset_voice_id=preset),
                language=self._settings.language,
                decoder_chunk_size=self._settings.decoder_chunk_size,
            )
        )
        yield tts_pb2.DuplexSynthesizeRequest(text_chunk=text)

    async def close(self) -> None:
        if self._active_call is not None:
            self._active_call.cancel()
            self._active_call = None
        await self._channel.close()


def _language_matches(actual: str, requested: str) -> bool:
    actual_folded, requested_folded = actual.casefold(), requested.casefold()
    if requested_folded in actual_folded or actual_folded in requested_folded:
        return True
    chinese_aliases = {"chinese", "zh", "zh-cn", "中文", "普通话", "mandarin"}
    return actual_folded in chinese_aliases and requested_folded in chinese_aliases
