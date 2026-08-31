from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

import httpx

from cet6_listener.config import LlmSettings
from cet6_listener.domain.events import AnswerEvent, QuestionEvent, TranscriptSegment, TranslationEvent
from cet6_listener.llm.output_cleaner import (
    clean_answer,
    clean_translation,
    contains_chinese,
    is_usable_answer,
    is_usable_translation,
    looks_like_question,
)
from cet6_listener.llm.prompt import (
    build_answer_retry_messages,
    build_chinese_repair_messages,
    build_messages,
    build_translation_messages,
    build_translation_repair_messages,
    extract_resolved_evidence,
    select_relevant_passage,
)

logger = logging.getLogger(__name__)


class LlmError(RuntimeError):
    """llama-server 请求或启动失败。"""


class LlamaCppClient:
    def __init__(self, settings: LlmSettings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.timeout_seconds)
        self._process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if await self._ready():
            logger.info("[LLM] 使用已运行的 llama-server：%s", self._settings.base_url)
            return
        if not self._settings.auto_start:
            raise LlmError(f"llama-server 不可用：{self._settings.base_url}")
        binary = Path(self._settings.binary)
        model = Path(self._settings.model_path)
        if not binary.is_file():
            raise LlmError(f"找不到 llama-server：{binary}")
        if not model.is_file():
            raise LlmError(f"找不到 Qwen 模型：{model}")
        self._process = await asyncio.create_subprocess_exec(
            str(binary),
            "-m",
            str(model),
            "--host",
            self._settings.host,
            "--port",
            str(self._settings.port),
            "-c",
            str(self._settings.context_size),
            "-t",
            str(self._settings.threads),
            "-np",
            "1",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(240):
            if self._process.returncode is not None:
                raise LlmError(f"llama-server 启动失败，退出码 {self._process.returncode}。")
            if await self._ready():
                logger.info("[LLM] llama-server 已启动")
                return
            await asyncio.sleep(0.25)
        raise LlmError("等待 llama-server 加载模型超时。")

    async def warmup(self) -> None:
        await self._complete(build_messages("A short test passage.", "What is this?"), max_tokens=2)

    async def answer(self, event: QuestionEvent) -> AnswerEvent:
        started = time.monotonic()
        raw = ""
        first_token: float | None = None
        last_error: Exception | None = None
        passage = select_relevant_passage(event.passage, event.question)
        logger.info(
            "[EVIDENCE] question=%s words=%d -> %d",
            event.question_id,
            len(event.passage.split()),
            len(passage.split()),
        )
        resolved = extract_resolved_evidence(passage)
        if resolved is not None:
            logger.info("[EVIDENCE] 使用确定性条件解析结果：%s", resolved)
            for attempt in range(2):
                try:
                    raw, first_token = await self._complete(
                        build_chinese_repair_messages(resolved, event.question)
                    )
                    break
                except (httpx.HTTPError, LlmError) as exc:
                    last_error = exc
                    if attempt == 0:
                        logger.warning("[LLM] 条件解析翻译失败，将重试：%s", exc)
                        await asyncio.sleep(0.2)
            else:
                raise LlmError(f"条件解析翻译连续失败：{last_error}") from last_error
        else:
            for attempt in range(2):
                try:
                    raw, first_token = await self._complete(build_messages(passage, event.question))
                    break
                except (httpx.HTTPError, LlmError) as exc:
                    last_error = exc
                    if attempt == 0:
                        compact = select_relevant_passage(
                            event.passage,
                            event.question,
                            max_sentences=6,
                            max_words=180,
                        )
                        logger.warning(
                            "[LLM] 请求失败，将用精简上下文重试：words=%d -> %d error=%s",
                            len(event.passage.split()),
                            len(compact.split()),
                            exc,
                        )
                        passage = compact
                        await asyncio.sleep(0.2)
            else:
                raise LlmError(f"LLM 请求连续失败：{last_error}") from last_error
        completed = time.monotonic()
        answer = clean_answer(raw)
        if not answer:
            raise LlmError("LLM 返回空答案。")
        if looks_like_question(answer):
            logger.warning("[LLM] 检测到问题复述，自动重新作答：%r", answer)
            try:
                raw, first_token = await self._complete(
                    build_answer_retry_messages(passage, event.question)
                )
            except (httpx.HTTPError, LlmError) as exc:
                raise LlmError(f"问题复述自动重答失败：{exc}") from exc
            answer = clean_answer(raw)
            completed = time.monotonic()
            if not answer or looks_like_question(answer):
                raise LlmError(f"LLM 重复输出问题而未作答：{raw!r}")
        if not contains_chinese(answer):
            logger.warning("[LLM] 检测到非中文答案，自动翻译重答：%r", answer)
            try:
                repaired_raw, repair_first_token = await self._complete(
                    build_chinese_repair_messages(raw, event.question)
                )
            except (httpx.HTTPError, LlmError) as exc:
                raise LlmError(f"非中文答案自动修复失败：{exc}") from exc
            answer = clean_answer(repaired_raw)
            if not answer or not is_usable_answer(answer):
                raise LlmError(f"LLM 未能返回中文答案：{repaired_raw!r}")
            raw = repaired_raw
            first_token = repair_first_token or first_token
            completed = time.monotonic()
        if not is_usable_answer(answer):
            raise LlmError(f"LLM 返回了无效或提示泄漏答案：{answer!r}")
        logger.info("[LLM] raw=%r", raw)
        logger.info("[ANSWER] %s", answer)
        return AnswerEvent(
            question_id=event.question_id,
            question=event.question,
            answer=answer,
            question_ended_at=event.ended_at,
            request_started_at=started,
            first_token_at=first_token,
            completed_at=completed,
        )

    async def translate(
        self,
        segment: TranscriptSegment,
        segment_id: str,
        *,
        source_language: str = "English",
        target_language: str = "Chinese",
        max_tokens: int = 128,
        max_characters: int = 240,
    ) -> TranslationEvent:
        started = time.monotonic()
        first_token: float | None = None
        last_error: Exception | None = None
        raw = ""
        for attempt in range(2):
            try:
                raw, first_token = await self._complete(
                    build_translation_messages(segment.text, source_language, target_language),
                    max_tokens=max_tokens,
                )
                break
            except (httpx.HTTPError, LlmError) as exc:
                last_error = exc
                if attempt == 0:
                    logger.warning("[TRANSLATE] segment=%s 请求失败，将重试：%s", segment_id, exc)
                    await asyncio.sleep(0.2)
        else:
            raise LlmError(f"翻译请求连续失败：{last_error}") from last_error

        translated = clean_translation(raw, max_characters)
        if not is_usable_translation(translated):
            logger.warning("[TRANSLATE] segment=%s 译文需要中文修复：%r", segment_id, raw)
            try:
                repaired, repair_first_token = await self._complete(
                    build_translation_repair_messages(raw, segment.text, target_language),
                    max_tokens=max_tokens,
                )
            except (httpx.HTTPError, LlmError) as exc:
                raise LlmError(f"译文自动修复失败：{exc}") from exc
            translated = clean_translation(repaired, max_characters)
            if not is_usable_translation(translated):
                raise LlmError(f"LLM 未能返回可用中文译文：{repaired!r}")
            raw = repaired
            first_token = repair_first_token or first_token

        completed = time.monotonic()
        logger.info("[TRANSLATE] source=%r", segment.text)
        logger.info("[TRANSLATION] %s", translated)
        return TranslationEvent(
            segment_id=segment_id,
            source_text=segment.text,
            translated_text=translated,
            segment_ended_at=segment.end_time,
            request_started_at=started,
            first_token_at=first_token,
            completed_at=completed,
        )

    async def _complete(
        self, messages: list[dict[str, str]], *, max_tokens: int | None = None
    ) -> tuple[str, float | None]:
        payload = {
            "messages": messages,
            "max_tokens": max_tokens or self._settings.max_tokens,
            "temperature": self._settings.temperature,
            "stream": True,
            "cache_prompt": True,
        }
        pieces: list[str] = []
        first_token: float | None = None
        async with self._client.stream(
            "POST", f"{self._settings.base_url.rstrip('/')}/v1/chat/completions", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    item = json.loads(data)
                    content = item["choices"][0].get("delta", {}).get("content", "")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                    raise LlmError(f"无法解析 LLM 流式响应：{data[:200]}") from exc
                if content:
                    if first_token is None:
                        first_token = time.monotonic()
                    pieces.append(content)
        return "".join(pieces), first_token

    async def _ready(self) -> bool:
        try:
            response = await self._client.get(f"{self._settings.base_url.rstrip('/')}/health", timeout=0.5)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()
