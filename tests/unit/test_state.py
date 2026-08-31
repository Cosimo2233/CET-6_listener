from cet6_listener.domain.events import AnswerPhase, ListeningPhase
from cet6_listener.pipeline.state import PipelineState


def test_two_state_axes_are_independent() -> None:
    state = PipelineState()
    state.set_listening(ListeningPhase.PASSAGE)
    state.set_answer(AnswerPhase.SPEAKING)

    assert state.listening is ListeningPhase.PASSAGE
    assert state.answer is AnswerPhase.SPEAKING
