from __future__ import annotations

import re
from collections import deque

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+")


def remove_word_overlap(previous: str, current: str, max_words: int = 16) -> str:
    previous_words = _WORD_RE.findall(previous)
    current_matches = list(_WORD_RE.finditer(current))
    current_words = [item.group(0) for item in current_matches]
    limit = min(max_words, len(previous_words), len(current_words))
    previous_folded = [word.casefold() for word in previous_words]
    current_folded = [word.casefold() for word in current_words]
    overlap = 0
    for count in range(limit, 0, -1):
        if previous_folded[-count:] == current_folded[:count]:
            overlap = count
            break
    if not overlap:
        return current.strip()
    if overlap >= len(current_matches):
        return ""
    return current[current_matches[overlap].start() :].strip(" ,.;:-")


class TranscriptManager:
    def __init__(self, word_limit: int = 700) -> None:
        self._word_limit = word_limit
        self._segments: deque[str] = deque()
        self._word_counts: deque[int] = deque()
        self._total_words = 0
        self._last_raw = ""

    @property
    def passage(self) -> str:
        return " ".join(self._segments)

    @property
    def word_count(self) -> int:
        return self._total_words

    def append_passage(self, text: str) -> str:
        normalized = " ".join(text.split())
        if not normalized:
            return ""
        deduplicated = remove_word_overlap(self._last_raw, normalized)
        self._last_raw = normalized
        if not deduplicated:
            return ""
        count = len(_WORD_RE.findall(deduplicated))
        if not count:
            return ""
        self._segments.append(deduplicated)
        self._word_counts.append(count)
        self._total_words += count
        self._trim()
        return deduplicated

    def snapshot(self) -> str:
        return self.passage

    def reset(self) -> None:
        self._segments.clear()
        self._word_counts.clear()
        self._total_words = 0
        self._last_raw = ""

    def _trim(self) -> None:
        while len(self._segments) > 1 and self._total_words > self._word_limit:
            self._segments.popleft()
            self._total_words -= self._word_counts.popleft()
        if self._total_words <= self._word_limit or not self._segments:
            return
        words = self._segments[0].split()
        keep = words[-self._word_limit :]
        self._segments[0] = " ".join(keep)
        self._word_counts[0] = len(keep)
        self._total_words = len(keep)
