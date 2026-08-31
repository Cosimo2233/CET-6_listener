from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, TypeVar, get_type_hints

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class AudioSettings:
    ffmpeg_binary: str = "ffmpeg"
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 20
    realtime: bool = True


@dataclass(frozen=True, slots=True)
class VadSettings:
    rms_threshold: int = 450
    prefix_ms: int = 200
    silence_ms: int = 600
    max_speech_seconds: int = 20


@dataclass(frozen=True, slots=True)
class AsrSettings:
    backend: str = "whisper_cpp"
    binary: str = "runtime/bin/whisper-server"
    model_path: str = "model-bin/ggml-base.en.bin"
    base_url: str = "http://127.0.0.1:8178"
    host: str = "127.0.0.1"
    port: int = 8178
    threads: int = 4
    language: str = "en"
    timeout_seconds: float = 60
    auto_start: bool = True
    npu_binary: str = "runtime/zipformer-a733/zipformer_demo_a733"
    npu_model_dir: str = "model-bin/zipformer-a733"
    npu_library_dir: str = "runtime/zipformer-a733/lib"
    npu_device: str = "/dev/vipcore"
    npu_encoder: str = "encoder_int16_a733.nb"
    npu_decoder: str = "decoder_int16_a733.nb"
    npu_joiner: str = "joiner_int16_a733.nb"
    npu_tokens: str = "tokens.txt"
    npu_frame_samples: int = 1600
    npu_startup_timeout_seconds: float = 60


@dataclass(frozen=True, slots=True)
class LlmSettings:
    binary: str = "runtime/bin/llama-server"
    model_path: str = "model-bin/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    base_url: str = "http://127.0.0.1:8080"
    host: str = "127.0.0.1"
    port: int = 8080
    context_size: int = 4096
    threads: int = 6
    max_tokens: int = 36
    temperature: float = 0.2
    timeout_seconds: float = 30
    auto_start: bool = True


@dataclass(frozen=True, slots=True)
class TtsSettings:
    target: str = "39.106.1.132:30032"
    voice_id: str = ""
    language: str = "Chinese"
    timeout_seconds: float = 30
    decoder_chunk_size: int = 0
    prefix: str = ""
    player_binary: str = "aplay"


@dataclass(frozen=True, slots=True)
class PipelineSettings:
    context_word_limit: int = 700
    question_silence_ms: int = 600
    max_question_seconds: int = 20
    audio_queue_size: int = 3000
    question_queue_size: int = 4
    answer_queue_size: int = 4


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    source_language: str = "English"
    target_language: str = "Chinese"
    max_tokens: int = 128
    max_characters: int = 240
    queue_size: int = 8


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str = "INFO"
    output_dir: str = "outputs"


@dataclass(frozen=True, slots=True)
class AppSettings:
    audio: AudioSettings
    vad: VadSettings
    asr: AsrSettings
    llm: LlmSettings
    tts: TtsSettings
    pipeline: PipelineSettings
    translation: TranslationSettings
    logging: LoggingSettings

    @classmethod
    def load(cls, config_path: Path | None = None, env_file: Path | None = None) -> "AppSettings":
        load_dotenv(env_file or Path(".env"), override=False)
        selected = config_path or Path(os.getenv("CET6_CONFIG", "config/default.yaml"))
        if not selected.exists():
            raise FileNotFoundError(f"配置文件不存在：{selected}")
        raw = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("配置文件顶层必须是映射。")
        _apply_environment(raw)
        settings = cls(
            audio=_construct(AudioSettings, raw.get("audio", {})),
            vad=_construct(VadSettings, raw.get("vad", {})),
            asr=_construct(AsrSettings, raw.get("asr", {})),
            llm=_construct(LlmSettings, raw.get("llm", {})),
            tts=_construct(TtsSettings, raw.get("tts", {})),
            pipeline=_construct(PipelineSettings, raw.get("pipeline", {})),
            translation=_construct(TranslationSettings, raw.get("translation", {})),
            logging=_construct(LoggingSettings, raw.get("logging", {})),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.audio.sample_rate <= 0 or self.audio.channels != 1:
            raise ValueError("MVP 音频必须是正采样率的单声道 PCM。")
        if self.audio.frame_ms <= 0 or 1000 % self.audio.frame_ms:
            raise ValueError("audio.frame_ms 必须能整除 1000。")
        if self.pipeline.context_word_limit <= 0:
            raise ValueError("pipeline.context_word_limit 必须大于 0。")
        if self.translation.max_tokens <= 0 or self.translation.max_characters <= 0:
            raise ValueError("translation 的 max_tokens 和 max_characters 必须大于 0。")
        if self.translation.queue_size <= 0:
            raise ValueError("translation.queue_size 必须大于 0。")
        if self.asr.backend.strip().casefold().replace("-", "_") not in {"whisper_cpp", "zipformer_npu"}:
            raise ValueError("asr.backend 必须是 whisper_cpp 或 zipformer_npu。")
        if self.asr.npu_frame_samples <= 0:
            raise ValueError("asr.npu_frame_samples 必须大于 0。")
        if not self.tts.target:
            raise ValueError("tts.target 不能为空。")


T = TypeVar("T")


def _construct(model: type[T], values: Any) -> T:
    if not isinstance(values, dict):
        raise ValueError(f"{model.__name__} 配置必须是映射。")
    allowed = {item.name for item in fields(model)}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"{model.__name__} 包含未知字段：{', '.join(sorted(unknown))}")
    hints = get_type_hints(model)
    converted = {key: _coerce(value, hints[key]) for key, value in values.items()}
    return model(**converted)


def _coerce(value: Any, expected: type[Any]) -> Any:
    if expected is bool and isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return expected(value) if isinstance(value, str) and expected in {int, float} else value


def _apply_environment(raw: dict[str, Any]) -> None:
    mapping = {
        "TTS_TARGET": ("tts", "target"),
        "TTS_VOICE_ID": ("tts", "voice_id"),
        "TTS_LANGUAGE": ("tts", "language"),
        "TTS_TIMEOUT_SECONDS": ("tts", "timeout_seconds"),
        "TTS_DECODER_CHUNK_SIZE": ("tts", "decoder_chunk_size"),
        "LLM_BASE_URL": ("llm", "base_url"),
        "LLM_MODEL_PATH": ("llm", "model_path"),
        "ASR_BASE_URL": ("asr", "base_url"),
        "ASR_MODEL_PATH": ("asr", "model_path"),
        "ASR_BACKEND": ("asr", "backend"),
        "ASR_NPU_BINARY": ("asr", "npu_binary"),
        "ASR_NPU_MODEL_DIR": ("asr", "npu_model_dir"),
        "ASR_NPU_LIBRARY_DIR": ("asr", "npu_library_dir"),
        "TRANSLATION_SOURCE_LANGUAGE": ("translation", "source_language"),
        "TRANSLATION_TARGET_LANGUAGE": ("translation", "target_language"),
        "TRANSLATION_MAX_TOKENS": ("translation", "max_tokens"),
        "TRANSLATION_MAX_CHARACTERS": ("translation", "max_characters"),
        "TRANSLATION_QUEUE_SIZE": ("translation", "queue_size"),
    }
    for name, (section, key) in mapping.items():
        if name in os.environ:
            raw.setdefault(section, {})[key] = os.environ[name]
