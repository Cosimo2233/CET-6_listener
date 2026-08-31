from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from cet6_listener.domain.events import PcmChunk


class TtsBackend(Protocol):
    async def prepare(self) -> str: ...

    def synthesize(self, text: str) -> AsyncIterator[PcmChunk]: ...

    async def close(self) -> None: ...
