from cet6_listener.transcript.manager import TranscriptManager, remove_word_overlap


def test_remove_word_overlap() -> None:
    assert remove_word_overlap("The woman will change her job", "her job next week") == "next week"
    assert remove_word_overlap("same text", "same text") == ""


def test_context_is_bounded() -> None:
    manager = TranscriptManager(word_limit=5)
    manager.append_passage("one two three")
    manager.append_passage("four five six")

    assert manager.word_count <= 5
    assert manager.passage == "four five six"
