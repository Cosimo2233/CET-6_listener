"""自动语音识别后端。"""

from __future__ import annotations

from cet6_listener.asr.base import AsrBackend, AsrError
from cet6_listener.asr.whisper_cpp import WhisperCppBackend
from cet6_listener.asr.zipformer_npu import ZipformerNpuBackend
from cet6_listener.config import AsrSettings


def create_asr_backend(settings: AsrSettings) -> AsrBackend:
    backend = settings.backend.strip().casefold().replace("-", "_")
    if backend == "whisper_cpp":
        return WhisperCppBackend(settings)
    if backend == "zipformer_npu":
        return ZipformerNpuBackend(settings)
    raise AsrError(f"不支持的 ASR 后端：{settings.backend}")


__all__ = [
    "AsrBackend",
    "AsrError",
    "WhisperCppBackend",
    "ZipformerNpuBackend",
    "create_asr_backend",
]
