import os
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from cet6_listener.asr import create_asr_backend
from cet6_listener.asr.zipformer_npu import ZipformerNpuBackend, _pcm_frames
from cet6_listener.config import AsrSettings
from cet6_listener.domain.events import SpeechSegment
from cet6_listener.asr.whisper_cpp import _extract_text, _wav_bytes


def test_wav_bytes_has_header() -> None:
    result = _wav_bytes(b"\x00\x00" * 320, 16000)
    assert result.startswith(b"RIFF")
    assert b"WAVE" in result[:16]


def test_extract_text_accepts_supported_shapes() -> None:
    assert _extract_text(httpx.Response(200, json={"text": "hello"})) == "hello"
    response = httpx.Response(200, json={"transcription": [{"text": "hello"}, {"text": "world"}]})
    assert _extract_text(response) == "hello world"


def test_pcm_frames_preserves_all_samples() -> None:
    pcm = bytes(range(20))
    frames = list(_pcm_frames(pcm, frame_samples=4))
    assert [len(frame) for frame in frames] == [8, 8, 4]
    assert b"".join(frames) == pcm


@pytest.mark.asyncio
async def test_zipformer_npu_protocol_with_fake_process(tmp_path: Path) -> None:
    binary = tmp_path / "fake-zipformer"
    binary.write_text(
        """#!/usr/bin/env python3
import struct
import sys

print('ASR_READY', flush=True)
while True:
    raw = sys.stdin.buffer.read(4)
    if not raw:
        break
    size = struct.unpack('<I', raw)[0]
    if size == 0:
        print('TEXT=hello from npu', flush=True)
        continue
    remaining = size
    while remaining:
        data = sys.stdin.buffer.read(remaining)
        if not data:
            raise SystemExit(2)
        remaining -= len(data)
""",
        encoding="utf-8",
    )
    os.chmod(binary, 0o755)
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for name in ("encoder_int16_a733.nb", "decoder_int16_a733.nb", "joiner_int16_a733.nb"):
        (model_dir / name).touch()
    (model_dir / "tokens.txt").write_text("0 <blk>\n", encoding="utf-8")
    device = tmp_path / "vipcore"
    device.touch()
    settings = replace(
        AsrSettings(),
        backend="zipformer_npu",
        npu_binary=str(binary),
        npu_model_dir=str(model_dir),
        npu_library_dir=str(tmp_path / "lib"),
        npu_device=str(device),
        npu_frame_samples=4,
        npu_startup_timeout_seconds=2,
        timeout_seconds=2,
    )
    backend = ZipformerNpuBackend(settings)
    try:
        await backend.start()
        result = await backend.transcribe(SpeechSegment(b"\x00\x00" * 10, 1.5, 2.5, 16000))
    finally:
        await backend.close()
    assert result.text == "hello from npu"
    assert result.start_time == 1.5
    assert result.end_time == 2.5
    assert isinstance(create_asr_backend(settings), ZipformerNpuBackend)
