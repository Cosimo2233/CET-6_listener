from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import struct
from collections import deque
from pathlib import Path
from typing import Iterator

from cet6_listener.asr.base import AsrError
from cet6_listener.config import AsrSettings
from cet6_listener.domain.events import SpeechSegment, TranscriptSegment

logger = logging.getLogger(__name__)

_READY_MARKER = "ASR_READY"
_TEXT_PREFIX = "TEXT="


class ZipformerNpuBackend:
    """瑞莎 A7A 官方 Zipformer NBG/VIPLite 常驻进程后端。"""

    def __init__(self, settings: AsrSettings) -> None:
        self._settings = settings
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._results: asyncio.Queue[str] = asyncio.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        binary, encoder, decoder, joiner, tokens = self._required_paths()
        missing = [str(path) for path in (binary, encoder, decoder, joiner, tokens) if not path.is_file()]
        if missing:
            raise AsrError("Zipformer NPU 文件缺失：" + "、".join(missing))
        device = Path(self._settings.npu_device)
        if not device.exists():
            raise AsrError(f"A733 NPU 设备不存在：{device}")
        if not os.access(device, os.R_OK | os.W_OK):
            raise AsrError(f"当前用户没有 A733 NPU 读写权限：{device}")

        env = os.environ.copy()
        library_dir = Path(self._settings.npu_library_dir).resolve()
        if library_dir.is_dir():
            current = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{library_dir}:{current}" if current else str(library_dir)

        self._ready.clear()
        self._stderr_tail.clear()
        self._drain_results()
        self._process = await asyncio.create_subprocess_exec(
            str(binary),
            "-nb0",
            str(encoder),
            "-nb1",
            str(decoder),
            "-nb2",
            str(joiner),
            "--stdin",
            cwd=str(binary.parent),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._stdout_task = asyncio.create_task(self._read_stdout(), name="zipformer-npu-stdout")
        self._stderr_task = asyncio.create_task(self._read_stderr(), name="zipformer-npu-stderr")
        try:
            await asyncio.wait_for(self._wait_ready(), timeout=self._settings.npu_startup_timeout_seconds)
        except (TimeoutError, AsrError):
            details = "".join(self._stderr_tail).strip()
            await self.close()
            suffix = f"\n{details}" if details else ""
            raise AsrError(f"等待 Zipformer NPU 启动超时或进程退出{suffix}") from None
        logger.info("[ASR] Zipformer 已在 A733 NPU 常驻，模型目录：%s", self._settings.npu_model_dir)

    async def transcribe(self, segment: SpeechSegment) -> TranscriptSegment:
        async with self._lock:
            process = self._process
            if process is None or process.returncode is not None or process.stdin is None:
                raise AsrError("Zipformer NPU 进程未运行。")
            if segment.sample_rate != 16000:
                raise AsrError(f"Zipformer NPU 仅支持 16000 Hz，收到 {segment.sample_rate} Hz。")
            if len(segment.pcm_s16le) % 2:
                raise AsrError("Zipformer NPU 收到的 PCM S16LE 字节数不是偶数。")

            self._drain_results()
            try:
                for frame in _pcm_frames(segment.pcm_s16le, self._settings.npu_frame_samples):
                    process.stdin.write(struct.pack("<I", len(frame)) + frame)
                    await process.stdin.drain()
                process.stdin.write(struct.pack("<I", 0))
                await process.stdin.drain()
                text = await asyncio.wait_for(self._results.get(), timeout=self._settings.timeout_seconds)
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise AsrError("Zipformer NPU stdin 已关闭。") from exc
            except TimeoutError as exc:
                raise AsrError("等待 Zipformer NPU TEXT 结果超时。") from exc
            return TranscriptSegment(text=text.strip(), start_time=segment.start_time, end_time=segment.end_time)

    async def _wait_ready(self) -> None:
        while not self._ready.is_set():
            if self._process is None or self._process.returncode is not None:
                raise AsrError("Zipformer NPU 进程在就绪前退出。")
            await asyncio.sleep(0.05)

    async def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        while line := await process.stdout.readline():
            value = line.decode("utf-8", errors="replace").strip()
            if _READY_MARKER in value:
                self._ready.set()
            if value.startswith(_TEXT_PREFIX):
                await self._results.put(value[len(_TEXT_PREFIX) :])

    async def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            value = line.decode("utf-8", errors="replace")
            self._stderr_tail.append(value)
            logger.debug("[ASR:NPU] %s", value.rstrip())

    def _required_paths(self) -> tuple[Path, Path, Path, Path, Path]:
        model_dir = Path(self._settings.npu_model_dir).resolve()
        return (
            Path(self._settings.npu_binary).resolve(),
            model_dir / self._settings.npu_encoder,
            model_dir / self._settings.npu_decoder,
            model_dir / self._settings.npu_joiner,
            model_dir / self._settings.npu_tokens,
        )

    def _drain_results(self) -> None:
        while not self._results.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._results.get_nowait()

    async def close(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    await process.stdin.wait_closed()
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._stdout_task, self._stderr_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._stdout_task = None
        self._stderr_task = None
        self._ready.clear()


def _pcm_frames(pcm_s16le: bytes, frame_samples: int) -> Iterator[bytes]:
    if frame_samples <= 0:
        raise ValueError("npu_frame_samples 必须大于 0。")
    frame_bytes = frame_samples * 2
    for offset in range(0, len(pcm_s16le), frame_bytes):
        yield pcm_s16le[offset : offset + frame_bytes]
