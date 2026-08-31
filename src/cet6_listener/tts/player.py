from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from cet6_listener.domain.events import PcmChunk, PlaybackEvent

logger = logging.getLogger(__name__)


class PlaybackError(RuntimeError):
    """ALSA 播放失败。"""


class AlsaPcmPlayer:
    def __init__(self, binary: str = "aplay") -> None:
        self._binary = binary
        self._process: asyncio.subprocess.Process | None = None

    async def play(self, question_id: str, chunks: AsyncIterator[PcmChunk]) -> PlaybackEvent:
        process: asyncio.subprocess.Process | None = None
        started_at: float | None = None
        try:
            async for chunk in chunks:
                if process is None:
                    process = await asyncio.create_subprocess_exec(
                        self._binary,
                        "-q",
                        "-t",
                        "raw",
                        "-f",
                        "S16_LE",
                        "-c",
                        "1",
                        "-r",
                        str(chunk.sample_rate),
                        stdin=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    self._process = process
                    started_at = time.monotonic()
                assert process.stdin is not None
                process.stdin.write(chunk.data)
                await process.stdin.drain()
            if process is None or started_at is None:
                raise PlaybackError("TTS 没有返回可播放的 PCM 数据。")
            assert process.stdin is not None
            process.stdin.close()
            await process.stdin.wait_closed()
            return_code = await process.wait()
            if return_code:
                stderr = b"" if process.stderr is None else await process.stderr.read()
                raise PlaybackError(f"aplay 播放失败（{return_code}）：{stderr.decode(errors='replace').strip()}")
            return PlaybackEvent(question_id, started_at, time.monotonic())
        finally:
            if self._process is process:
                self._process = None

    async def close(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
