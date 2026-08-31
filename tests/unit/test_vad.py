from array import array

import pytest

from cet6_listener.audio.vad import EnergyVad, pcm_rms
from cet6_listener.config import AudioSettings, VadSettings
from cet6_listener.domain.events import AudioFrame


def frame(value: int, index: int, *, eof: bool = False) -> AudioFrame:
    samples = array("h", [value] * 320).tobytes() if not eof else b""
    return AudioFrame(samples, index * 0.02, 0 if eof else 0.02, eof)


def test_pcm_rms() -> None:
    assert pcm_rms(frame(1000, 0).data) == 1000
    assert pcm_rms(b"") == 0


def test_vad_emits_after_silence_with_prefix() -> None:
    vad = EnergyVad(
        AudioSettings(frame_ms=20),
        VadSettings(rms_threshold=400, prefix_ms=40, silence_ms=40, max_speech_seconds=2),
    )
    emitted = []
    for index, value in enumerate([0, 0, 1000, 1000, 0, 0]):
        segment = vad.consume(frame(value, index))
        if segment:
            emitted.append(segment)

    assert len(emitted) == 1
    assert emitted[0].start_time == 0.02
    assert emitted[0].end_time == pytest.approx(0.12)
    assert len(emitted[0].pcm_s16le) == 5 * 640


def test_vad_flushes_at_eof() -> None:
    vad = EnergyVad(AudioSettings(), VadSettings())
    vad.consume(frame(1000, 0))

    segment = vad.consume(frame(0, 1, eof=True))

    assert segment is not None
    assert segment.pcm_s16le
