from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from dataclasses import replace
from pathlib import Path

import psutil
import typer

from cet6_listener.asr import AsrError, create_asr_backend
from cet6_listener.audio.file_source import AudioDecodeError, FileAudioSource
from cet6_listener.audio.vad import EnergyVad
from cet6_listener.config import AppSettings
from cet6_listener.domain.events import QuestionEvent
from cet6_listener.llm.client import LlamaCppClient, LlmError
from cet6_listener.logging import configure_logging
from cet6_listener.pipeline.realtime import RealtimePipeline
from cet6_listener.pipeline.translation import TranslationPipeline
from cet6_listener.tts.grpc_client import GrpcTtsClient, TtsError
from cet6_listener.tts.player import AlsaPcmPlayer, PlaybackError

app = typer.Typer(no_args_is_help=True, help="瑞莎 A7A 六级英语听力助手")
logger = logging.getLogger(__name__)


def _settings(path: Path) -> AppSettings:
    settings = AppSettings.load(path)
    configure_logging(settings.logging.level, Path(settings.logging.output_dir))
    return settings


@app.command("run")
def run_command(
    audio: Path = typer.Option(..., "--audio", "-a", exists=True, dir_okay=False, help="六级音频文件"),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
    dry_run: bool = typer.Option(False, "--dry-run", help="不调用和播放 TTS"),
    fast: bool = typer.Option(False, "--fast", help="不按真实时间等待音频"),
    asr_backend: str | None = typer.Option(None, "--asr", help="whisper-cpp 或 zipformer-npu"),
) -> None:
    """运行文件音频端到端流水线。"""
    settings = _settings(config)
    if asr_backend:
        settings = replace(settings, asr=replace(settings.asr, backend=asr_backend))
        settings.validate()
    source = FileAudioSource(audio, settings.audio, realtime=not fast)
    asr = create_asr_backend(settings.asr)
    llm = LlamaCppClient(settings.llm)
    tts = None if dry_run else GrpcTtsClient(settings.tts)
    player = None if dry_run else AlsaPcmPlayer(settings.tts.player_binary)
    pipeline = RealtimePipeline(settings, source, asr, llm, dry_run=dry_run, tts=tts, player=player)
    try:
        asyncio.run(pipeline.run())
    except* (AudioDecodeError, AsrError, LlmError, TtsError, PlaybackError, OSError) as group:
        for error in group.exceptions:
            logger.error("运行失败：%s", error)
        raise typer.Exit(1) from group


@app.command("translate")
def translate_command(
    audio: Path = typer.Option(..., "--audio", "-a", exists=True, dir_okay=False, help="待翻译的英语音频文件"),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
    dry_run: bool = typer.Option(False, "--dry-run", help="输出译文但不调用和播放 TTS"),
    fast: bool = typer.Option(False, "--fast", help="不按真实时间等待音频"),
    asr_backend: str | None = typer.Option(None, "--asr", help="whisper-cpp 或 zipformer-npu"),
) -> None:
    """实时识别英语语音，翻译为中文并通过 TTS 播放。"""
    settings = _settings(config)
    if asr_backend:
        settings = replace(settings, asr=replace(settings.asr, backend=asr_backend))
        settings.validate()
    source = FileAudioSource(audio, settings.audio, realtime=not fast)
    asr = create_asr_backend(settings.asr)
    llm = LlamaCppClient(settings.llm)
    tts = None if dry_run else GrpcTtsClient(settings.tts)
    player = None if dry_run else AlsaPcmPlayer(settings.tts.player_binary)
    pipeline = TranslationPipeline(
        settings,
        source,
        asr,
        llm,
        dry_run=dry_run,
        tts=tts,
        player=player,
    )
    try:
        asyncio.run(pipeline.run())
    except* (AudioDecodeError, AsrError, LlmError, TtsError, PlaybackError, OSError) as group:
        for error in group.exceptions:
            logger.error("翻译运行失败：%s", error)
        raise typer.Exit(1) from group


@app.command("check")
def check_command(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
    asr_backend: str | None = typer.Option(None, "--asr", help="检查指定 ASR 后端"),
) -> None:
    """检查外部程序、模型和 TTS 服务。"""
    settings = _settings(config)
    if asr_backend:
        settings = replace(settings, asr=replace(settings.asr, backend=asr_backend))
        settings.validate()
    checks = {
        "FFmpeg": _exists(settings.audio.ffmpeg_binary),
        "aplay": _exists(settings.tts.player_binary),
        "llama-server": _exists(settings.llm.binary),
        "Qwen model": Path(settings.llm.model_path).is_file(),
    }
    checks.update(_asr_checks(settings))
    failed = False
    for name, ok in checks.items():
        typer.echo(f"{'OK' if ok else 'MISSING':7} {name}")
        failed |= not ok
    try:
        voices = asyncio.run(_list_voices(settings))
        typer.echo(f"OK      TTS ({len(voices)} voices)")
    except TtsError as exc:
        failed = True
        typer.echo(f"FAILED  TTS: {exc}")
    if failed:
        raise typer.Exit(1)


@app.command("list-voices")
def list_voices_command(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
) -> None:
    """列出当前 TTS 实例可用音色。"""
    settings = _settings(config)
    try:
        voices = asyncio.run(_list_voices(settings))
    except TtsError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc
    for voice in voices:
        typer.echo(f"{voice.voice_id}\t{voice.name}\t{voice.language}")


@app.command("test-tts")
def test_tts_command(
    text: str = typer.Option("因为航班延误", "--text", "-t"),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
) -> None:
    """合成并播放一条中文文本。"""
    settings = _settings(config)
    try:
        asyncio.run(_test_tts(settings, text))
    except (TtsError, OSError) as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc


@app.command("benchmark-llm")
def benchmark_llm_command(
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
) -> None:
    """运行一次本地 Qwen 延迟与内存测试。"""
    settings = _settings(config)
    try:
        asyncio.run(_benchmark_llm(settings))
    except LlmError as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc


@app.command("benchmark-asr")
def benchmark_asr_command(
    audio: Path = typer.Option(..., "--audio", "-a", exists=True, dir_okay=False),
    config: Path = typer.Option(Path("config/default.yaml"), "--config", "-c", envvar="CET6_CONFIG"),
    asr_backend: str | None = typer.Option(None, "--asr", help="whisper-cpp 或 zipformer-npu"),
) -> None:
    """以最快速度转写文件并报告 ASR 实时率。"""
    settings = _settings(config)
    if asr_backend:
        settings = replace(settings, asr=replace(settings.asr, backend=asr_backend))
        settings.validate()
    try:
        asyncio.run(_benchmark_asr(settings, audio))
    except (AudioDecodeError, AsrError, OSError) as exc:
        logger.error("%s", exc)
        raise typer.Exit(1) from exc


async def _list_voices(settings: AppSettings):  # type: ignore[no-untyped-def]
    client = GrpcTtsClient(settings.tts)
    try:
        return await client.list_voices()
    finally:
        await client.close()


async def _test_tts(settings: AppSettings, text: str) -> None:
    client = GrpcTtsClient(settings.tts)
    player = AlsaPcmPlayer(settings.tts.player_binary)
    try:
        await client.prepare()
        event = await player.play("manual", client.synthesize(text))
        typer.echo(f"播放完成：{(event.completed_at - event.started_at) * 1000:.1f} ms")
    finally:
        await player.close()
        await client.close()


async def _benchmark_llm(settings: AppSettings) -> None:
    client = LlamaCppClient(settings.llm)
    before = psutil.Process().memory_info().rss
    started = time.monotonic()
    try:
        await client.start()
        loaded = time.monotonic()
        event = await client.answer(
            QuestionEvent(
                "benchmark",
                "The flight was cancelled because of severe weather conditions.",
                "Why couldn't the man leave yesterday?",
                time.monotonic(),
            )
        )
        typer.echo(f"model_start_seconds={loaded - started:.3f}")
        typer.echo(f"first_token_seconds={(event.first_token_at or event.completed_at) - event.request_started_at:.3f}")
        typer.echo(f"total_seconds={event.completed_at - event.request_started_at:.3f}")
        typer.echo(f"answer={event.answer}")
        typer.echo(f"orchestrator_rss_delta_mb={(psutil.Process().memory_info().rss - before) / 1024 / 1024:.2f}")
    finally:
        await client.close()


async def _benchmark_asr(settings: AppSettings, path: Path) -> None:
    source = FileAudioSource(path, settings.audio, realtime=False)
    backend = create_asr_backend(settings.asr)
    vad = EnergyVad(settings.audio, settings.vad)
    started = time.monotonic()
    audio_seconds = 0.0
    count = 0
    try:
        await backend.start()
        async for frame in source.frames():
            audio_seconds = max(audio_seconds, frame.timestamp + frame.duration)
            speech = vad.consume(frame)
            if speech is not None:
                result = await backend.transcribe(speech)
                count += 1
                typer.echo(f"[{result.start_time:.2f}-{result.end_time:.2f}] {result.text}")
    finally:
        await source.close()
        await backend.close()
    wall = time.monotonic() - started
    typer.echo(f"audio_seconds={audio_seconds:.3f}")
    typer.echo(f"wall_seconds={wall:.3f}")
    typer.echo(f"realtime_factor={wall / audio_seconds if audio_seconds else 0:.3f}")
    typer.echo(f"segments={count}")


def _exists(value: str) -> bool:
    path = Path(value)
    return path.is_file() if path.parent != Path(".") else shutil.which(value) is not None


def _asr_checks(settings: AppSettings) -> dict[str, bool]:
    backend = settings.asr.backend.strip().casefold().replace("-", "_")
    if backend == "whisper_cpp":
        return {
            "ASR backend (whisper_cpp)": True,
            "whisper-server": _exists(settings.asr.binary),
            "Whisper model": Path(settings.asr.model_path).is_file(),
        }
    model_dir = Path(settings.asr.npu_model_dir)
    return {
        "ASR backend (zipformer_npu)": True,
        "A733 /dev/vipcore": os.access(settings.asr.npu_device, os.R_OK | os.W_OK),
        "Zipformer NPU binary": _exists(settings.asr.npu_binary),
        "Zipformer encoder": (model_dir / settings.asr.npu_encoder).is_file(),
        "Zipformer decoder": (model_dir / settings.asr.npu_decoder).is_file(),
        "Zipformer joiner": (model_dir / settings.asr.npu_joiner).is_file(),
        "Zipformer tokens": (model_dir / settings.asr.npu_tokens).is_file(),
        "VIPLite library directory": Path(settings.asr.npu_library_dir).is_dir(),
    }


if __name__ == "__main__":
    app()
