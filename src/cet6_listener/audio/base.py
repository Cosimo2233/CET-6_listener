from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from cet6_listener.domain.events import AudioFrame


class AudioSource(Protocol):
    async def frames(self) -> AsyncIterator[AudioFrame]: ...

    async def close(self) -> None: ...
