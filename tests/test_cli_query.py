from chatplayground_skill import state
from chatplayground_skill.browser import QueryResult
from chatplayground_skill.cli_query import main
from chatplayground_skill.errors import ModelNotFoundError, QueryTimeoutError, SelectorNotFoundError


def _authenticated(tmp_path):
    state.save_storage_state(tmp_path, {"cookies": [{"name": "s", "value": "v"}]})
    return tmp_path


def test_returns_2_when_not_authenticated(tmp_path, capsys):
    code = main(["hello", "--model", "gpt-5"], query_fn=lambda **_: None, state_dir=tmp_path)
    assert code == 2
    assert "login.py" in capsys.readouterr().err


def test_success_prints_reply_and_saves_thread_anchor(tmp_path, capsys):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        assert kwargs["prompt"] == "hello"
        assert kwargs["model"] == "gpt-5"
        assert kwargs["thread_anchor"] is None
        return QueryResult(reply="hi there", thread_anchor="hello")

    code = main(["hello", "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0
    assert capsys.readouterr().out.strip() == "hi there"
    assert state.get_thread_anchor(sdir, "gpt-5") == "hello"


def test_resumes_existing_thread(tmp_path):
    sdir = _authenticated(tmp_path)
    state.set_thread_anchor(sdir, "gpt-5", "first message to gpt-5")

    def fake_query_fn(**kwargs):
        assert kwargs["thread_anchor"] == "first message to gpt-5"
        return QueryResult(reply="ok", thread_anchor="first message to gpt-5")

    code = main(["follow-up", "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0


def test_reset_clears_thread_before_query(tmp_path):
    sdir = _authenticated(tmp_path)
    state.set_thread_anchor(sdir, "gpt-5", "old first message")

    def fake_query_fn(**kwargs):
        assert kwargs["thread_anchor"] is None
        return QueryResult(reply="ok", thread_anchor="new first message")

    code = main(["new first message", "--model", "gpt-5", "--reset"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0
    assert state.get_thread_anchor(sdir, "gpt-5") == "new first message"


def test_reset_is_noop_when_no_existing_thread(tmp_path):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        assert kwargs["thread_anchor"] is None
        return QueryResult(reply="ok", thread_anchor="hello")

    code = main(["hello", "--model", "never-used", "--reset"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0


def test_special_characters_in_prompt_passed_through_unchanged(tmp_path):
    sdir = _authenticated(tmp_path)
    tricky = 'quote " and newline\nand emoji \U0001F389'

    def fake_query_fn(**kwargs):
        assert kwargs["prompt"] == tricky
        return QueryResult(reply="ok", thread_anchor=tricky)

    code = main([tricky, "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0


def test_model_not_found_returns_1(tmp_path, capsys):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        raise ModelNotFoundError("nonexistent-model")

    code = main(["hello", "--model", "nonexistent-model"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 1
    assert "nonexistent-model" in capsys.readouterr().err


def test_selector_not_found_returns_3_with_message(tmp_path, capsys):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        raise SelectorNotFoundError("chat_input")

    code = main(["hello", "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 3
    assert "chat_input" in capsys.readouterr().err


def test_timeout_returns_1(tmp_path, capsys):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        raise QueryTimeoutError()

    code = main(["hello", "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 1
    assert "timed out" in capsys.readouterr().err
