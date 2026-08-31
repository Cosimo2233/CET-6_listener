from __future__ import annotations

import math
from array import array
from collections import deque

from cet6_listener.config import AudioSettings, VadSettings
from cet6_listener.domain.events import AudioFrame, SpeechSegment


def pcm_rms(pcm_s16le: bytes) -> int:
    if len(pcm_s16le) < 2:
        return 0
    samples = array("h")
    samples.frombytes(pcm_s16le[: len(pcm_s16le) // 2 * 2])
    return math.isqrt(sum(value * value for value in samples) // len(samples))


class EnergyVad:
    """适用于 MVP 的有界能量 VAD；后端可替换为更复杂模型。"""

    def __init__(self, audio: AudioSettings, settings: VadSettings) -> None:
        self._sample_rate = audio.sample_rate
        self._threshold = settings.rms_threshold
        self._silence_frames = max(1, settings.silence_ms // audio.frame_ms)
        self._max_frames = max(1, settings.max_speech_seconds * 1000 // audio.frame_ms)
        self._prefix: deque[AudioFrame] = deque(maxlen=max(1, settings.prefix_ms // audio.frame_ms))
        self._speech: list[AudioFrame] = []
        self._silent_count = 0

    @property
    def active(self) -> bool:
        return bool(self._speech)

    def consume(self, frame: AudioFrame) -> SpeechSegment | None:
        if frame.eof:
            return self.flush(frame.timestamp)
        voiced = pcm_rms(frame.data) >= self._threshold
        if not self._speech:
            self._prefix.append(frame)
            if not voiced:
                return None
            self._speech = list(self._prefix)
            self._prefix.clear()
            self._silent_count = 0
            return None

        self._speech.append(frame)
        self._silent_count = 0 if voiced else self._silent_count + 1
        if self._silent_count >= self._silence_frames or len(self._speech) >= self._max_frames:
            return self._emit()
        return None

    def flush(self, end_time: float | None = None) -> SpeechSegment | None:
        if not self._speech:
            self._prefix.clear()
            return None
        return self._emit(end_time)

    def _emit(self, end_time: float | None = None) -> SpeechSegment:
        frames, self._speech = self._speech, []
        self._silent_count = 0
        self._prefix.clear()
        return SpeechSegment(
            pcm_s16le=b"".join(item.data for item in frames),
            start_time=frames[0].timestamp,
            end_time=end_time if end_time is not None else frames[-1].timestamp + frames[-1].duration,
            sample_rate=self._sample_rate,
        )
