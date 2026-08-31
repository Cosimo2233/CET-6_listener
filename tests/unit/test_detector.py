from cet6_listener.detector.question_detector import QuestionDetector
from cet6_listener.domain.events import TranscriptSegment
from cet6_listener.transcript.manager import TranscriptManager


def segment(text: str, start: float = 0, end: float = 1) -> TranscriptSegment:
    return TranscriptSegment(text, start, end)


def test_detects_numbered_question_and_keeps_passage() -> None:
    manager = TranscriptManager()
    detector = QuestionDetector(manager)
    assert detector.consume(segment("The woman has applied for another job.")) is None

    event = detector.consume(segment("Question 1. What is the woman planning to do?", 2, 3))

    assert event is not None
    assert event.question_id == "1"
    assert event.question == "What is the woman planning to do?"
    assert "applied for another job" in event.passage


def test_question_group_preserves_preceding_passage() -> None:
    manager = TranscriptManager()
    manager.append_passage("the relevant conversation passage")
    detector = QuestionDetector(manager)

    detector.consume(segment("Questions 5 to 8 are based on the following conversation."))

    assert "relevant conversation" in manager.passage


def test_content_marker_resets_previous_group() -> None:
    manager = TranscriptManager()
    manager.append_passage("old passage")
    detector = QuestionDetector(manager)

    detector.consume(segment("Conversation 2."))

    assert manager.passage == ""


def test_recording_marker_resets_previous_group() -> None:
    manager = TranscriptManager()
    manager.append_passage("old recording")
    detector = QuestionDetector(manager)

    detector.consume(segment("Recording 2."))

    assert manager.passage == ""


def test_hyphenated_group_marker_arms_question_detection() -> None:
    detector = QuestionDetector(TranscriptManager())
    detector.consume(segment("Questions 22-25 are based on the recording you have just heard."))

    event = detector.consume(segment("What does the speaker say travelers commonly complain about?"))

    assert event is not None


def test_group_marker_and_first_question_in_same_segment() -> None:
    manager = TranscriptManager()
    manager.append_passage("relevant passage")
    detector = QuestionDetector(manager)

    event = detector.consume(
        segment(
            "Questions 9 to 11 are based on the conversation you have just heard. "
            "Question 9. What does the woman suggest doing?"
        )
    )

    assert event is not None
    assert event.question_id == "9"
    assert event.question == "What does the woman suggest doing?"
    assert event.passage == "relevant passage"


def test_direct_typical_question_is_detected() -> None:
    detector = QuestionDetector(TranscriptManager())
    detector.consume(segment("Questions 1 to 4 are based on the conversation you have just heard."))

    event = detector.consume(segment("What can we learn from the conversation?"))

    assert event is not None


def test_numbered_question_accepts_according_stem() -> None:
    detector = QuestionDetector(TranscriptManager())

    event = detector.consume(
        segment("Question 3. According to the man, how does one get a career in foreign relations?")
    )

    assert event is not None
    assert event.question_id == "3"


def test_dialogue_question_is_not_treated_as_exam_question() -> None:
    detector = QuestionDetector(TranscriptManager())

    event = detector.consume(segment("What can you tell us?"))

    assert event is None
