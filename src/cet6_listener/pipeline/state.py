from __future__ import annotations

import logging
from dataclasses import dataclass

from cet6_listener.domain.events import AnswerPhase, ListeningPhase

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineState:
    listening: ListeningPhase = ListeningPhase.IDLE
    answer: AnswerPhase = AnswerPhase.IDLE

    def set_listening(self, phase: ListeningPhase) -> None:
        if phase != self.listening:
            logger.info("[STATE] listening %s -> %s", self.listening, phase)
            self.listening = phase

    def set_answer(self, phase: AnswerPhase) -> None:
        if phase != self.answer:
            logger.info("[STATE] answer %s -> %s", self.answer, phase)
            self.answer = phase
