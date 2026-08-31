from __future__ import annotations

from typing import Protocol

from cet6_listener.domain.events import SpeechSegment, TranscriptSegment


class AsrError(RuntimeError):
    """ASR 后端启动或推理失败。"""


class AsrBackend(Protocol):
    async def start(self) -> None: ...

    async def transcribe(self, segment: SpeechSegment) -> TranscriptSegment: ...

    async def close(self) -> None: ...
