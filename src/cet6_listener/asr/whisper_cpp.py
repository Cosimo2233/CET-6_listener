from __future__ import annotations

import asyncio
import io
import json
import logging
import wave
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from cet6_listener.asr.base import AsrError
from cet6_listener.config import AsrSettings
from cet6_listener.domain.events import SpeechSegment, TranscriptSegment

logger = logging.getLogger(__name__)


class WhisperCppBackend:
    def __init__(self, settings: AsrSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if await self._server_ready():
            logger.info("[ASR] 使用已运行的 whisper-server：%s", self._settings.base_url)
            return
        if not self._settings.auto_start:
            raise AsrError(f"whisper-server 不可用：{self._settings.base_url}")
        binary = Path(self._settings.binary)
        model = Path(self._settings.model_path)
        if not binary.is_file():
            raise AsrError(f"找不到 whisper-server：{binary}")
        if not model.is_file():
            raise AsrError(f"找不到 Whisper 模型：{model}")
        self._process = await asyncio.create_subprocess_exec(
            str(binary),
            "-m",
            str(model),
            "--host",
            self._settings.host,
            "--port",
            str(self._settings.port),
            "-t",
            str(self._settings.threads),
            "-l",
            self._settings.language,
            "--no-gpu",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        for _ in range(80):
            if self._process.returncode is not None:
                raise AsrError(f"whisper-server 启动失败：{await self._process_error()}")
            if await self._server_ready():
                logger.info("[ASR] whisper-server 已启动")
                return
            await asyncio.sleep(0.25)
        raise AsrError("等待 whisper-server 启动超时。")

    async def transcribe(self, segment: SpeechSegment) -> TranscriptSegment:
        wav_data = _wav_bytes(segment.pcm_s16le, segment.sample_rate)
        try:
            response = await self._client.post(
                f"{self._settings.base_url.rstrip('/')}/inference",
                data={"response_format": "json", "language": self._settings.language},
                files={"file": ("segment.wav", wav_data, "audio/wav")},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AsrError(f"ASR 请求失败：{exc}") from exc
        text = _extract_text(response)
        return TranscriptSegment(text=text.strip(), start_time=segment.start_time, end_time=segment.end_time)

    async def _server_ready(self) -> bool:
        parsed = urlparse(self._settings.base_url)
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=0.4
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    async def _process_error(self) -> str:
        if self._process is None or self._process.stderr is None:
            return "未知错误"
        return (await self._process.stderr.read()).decode("utf-8", errors="replace").strip()

    async def close(self) -> None:
        await self._client.aclose()
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()


def _wav_bytes(pcm_s16le: bytes, sample_rate: int) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_s16le)
    return output.getvalue()


def _extract_text(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except json.JSONDecodeError:
        return response.text
    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            return payload["text"]
        transcription = payload.get("transcription")
        if isinstance(transcription, list):
            return " ".join(str(item.get("text", "")) for item in transcription if isinstance(item, dict))
    raise AsrError("whisper-server 返回中没有可识别文本。")
