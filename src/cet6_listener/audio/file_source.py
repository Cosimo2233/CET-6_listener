from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

from cet6_listener.config import AudioSettings
from cet6_listener.domain.events import AudioFrame

logger = logging.getLogger(__name__)


class AudioDecodeError(RuntimeError):
    """FFmpeg 无法解码输入音频。"""


class FileAudioSource:
    def __init__(self, path: Path, settings: AudioSettings, *, realtime: bool | None = None) -> None:
        self._path = path
        self._settings = settings
        self._realtime = settings.realtime if realtime is None else realtime
        self._process: asyncio.subprocess.Process | None = None

    async def frames(self) -> AsyncIterator[AudioFrame]:
        if not self._path.is_file():
            raise FileNotFoundError(f"音频文件不存在：{self._path}")
        bytes_per_frame = (
            self._settings.sample_rate
            * self._settings.channels
            * 2
            * self._settings.frame_ms
            // 1000
        )
        duration = self._settings.frame_ms / 1000.0
        self._process = await asyncio.create_subprocess_exec(
            self._settings.ffmpeg_binary,
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(self._path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            str(self._settings.channels),
            "-ar",
            str(self._settings.sample_rate),
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert self._process.stdout is not None
        started = time.monotonic()
        frame_index = 0
        try:
            while True:
                data = await self._process.stdout.read(bytes_per_frame)
                if not data:
                    break
                timestamp = frame_index * duration
                if self._realtime:
                    delay = started + timestamp - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                yield AudioFrame(data=data, timestamp=timestamp, duration=len(data) / 2 / self._settings.sample_rate)
                frame_index += 1
            return_code = await self._process.wait()
            stderr = await self._read_stderr()
            if return_code:
                raise AudioDecodeError(f"FFmpeg 解码失败（{return_code}）：{stderr.strip()}")
            yield AudioFrame(data=b"", timestamp=frame_index * duration, duration=0, eof=True)
        finally:
            await self.close()

    async def _read_stderr(self) -> str:
        if self._process is None or self._process.stderr is None:
            return ""
        return (await self._process.stderr.read()).decode("utf-8", errors="replace")

    async def close(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
