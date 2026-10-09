from chatplayground_skill.completion import is_response_stable


def test_empty_history_is_not_stable():
    assert is_response_stable([]) is False


def test_single_entry_is_not_stable():
    assert is_response_stable(["hello"]) is False


def test_two_identical_entries_are_stable():
    assert is_response_stable(["hello", "hello"]) is True


def test_two_different_entries_are_not_stable():
    assert is_response_stable(["hello", "hello world"]) is False


def test_blank_entries_are_not_stable():
    assert is_response_stable(["", ""]) is False


def test_custom_window_requires_more_matches():
    assert is_response_stable(["a", "a", "b"], window=3) is False
    assert is_response_stable(["a", "a", "a"], window=3) is True
