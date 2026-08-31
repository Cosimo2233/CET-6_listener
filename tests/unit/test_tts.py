from types import SimpleNamespace

import pytest

from cet6_listener.config import TtsSettings
from cet6_listener.tts.grpc_client import GrpcTtsClient, TtsError, _language_matches


class FakeStream:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.cancelled = False

    def __aiter__(self):  # type: ignore[no-untyped-def]
        return self._iterate()

    async def _iterate(self):  # type: ignore[no-untyped-def]
        for response in self.responses:
            yield response

    def cancel(self) -> None:
        self.cancelled = True


class FakeTtsStub:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream

    def Synthesize(self, _request, timeout: float):  # type: ignore[no-untyped-def]
        assert timeout == 1
        return self.stream


def client_with(stream: FakeStream) -> GrpcTtsClient:
    client = GrpcTtsClient.__new__(GrpcTtsClient)
    client._settings = TtsSettings(target="localhost:1", voice_id="voice", timeout_seconds=1)
    client._voice_id = "voice"
    client._voice_names = {}
    client._serving_mode = "synthesize"
    client._active_call = None
    client._tts_stub = FakeTtsStub(stream)
    return client


@pytest.mark.asyncio
async def test_synthesize_yields_ordered_pcm() -> None:
    stream = FakeStream(
        [
            SimpleNamespace(chunk_index=3, sample_rate=24000, pcm_s16le=b"a"),
            SimpleNamespace(chunk_index=4, sample_rate=24000, pcm_s16le=b"b"),
        ]
    )

    chunks = [chunk async for chunk in client_with(stream).synthesize("测试")]

    assert b"".join(chunk.data for chunk in chunks) == b"ab"


@pytest.mark.asyncio
async def test_synthesize_rejects_index_gap() -> None:
    stream = FakeStream(
        [
            SimpleNamespace(chunk_index=0, sample_rate=24000, pcm_s16le=b"a"),
            SimpleNamespace(chunk_index=2, sample_rate=24000, pcm_s16le=b"b"),
        ]
    )

    with pytest.raises(TtsError, match="序号异常"):
        _ = [chunk async for chunk in client_with(stream).synthesize("测试")]


def test_chinese_language_aliases() -> None:
    assert _language_matches("zh-CN", "Chinese")
    assert _language_matches("中文", "Chinese")
