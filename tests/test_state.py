import stat

from chatplayground_skill import state


def test_ensure_state_dir_creates_with_0700(tmp_path):
    sdir = tmp_path / "state"
    state.ensure_state_dir(sdir)
    assert sdir.is_dir()
    assert stat.S_IMODE(sdir.stat().st_mode) == 0o700


def test_has_valid_session_false_when_missing(tmp_path):
    assert state.has_valid_session(tmp_path) is False


def test_has_valid_session_false_when_corrupted(tmp_path):
    (tmp_path / "storage_state.json").write_text("{not valid json")
    assert state.has_valid_session(tmp_path) is False


def test_has_valid_session_true_when_present(tmp_path):
    state.save_storage_state(tmp_path, {"cookies": [{"name": "session", "value": "abc"}], "origins": []})
    assert state.has_valid_session(tmp_path) is True


def test_has_valid_session_false_when_no_cookies(tmp_path):
    state.save_storage_state(tmp_path, {"cookies": [], "origins": []})
    assert state.has_valid_session(tmp_path) is False


def test_save_storage_state_sets_0600_permissions(tmp_path):
    state.save_storage_state(tmp_path, {"cookies": [{"name": "s", "value": "v"}]})
    path = tmp_path / "storage_state.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_load_storage_state_round_trip(tmp_path):
    data = {"cookies": [{"name": "s", "value": "v"}], "origins": []}
    state.save_storage_state(tmp_path, data)
    assert state.load_storage_state(tmp_path) == data


def test_threads_get_set_round_trip(tmp_path):
    assert state.get_thread_url(tmp_path, "gpt-5") is None
    state.set_thread_url(tmp_path, "gpt-5", "https://web.chatplayground.ai/chat/123")
    assert state.get_thread_url(tmp_path, "gpt-5") == "https://web.chatplayground.ai/chat/123"


def test_set_thread_url_preserves_other_models_entries(tmp_path):
    state.set_thread_url(tmp_path, "gpt-5", "https://web.chatplayground.ai/chat/aaa")
    state.set_thread_url(tmp_path, "claude-5", "https://web.chatplayground.ai/chat/bbb")
    assert state.get_thread_url(tmp_path, "gpt-5") == "https://web.chatplayground.ai/chat/aaa"
    assert state.get_thread_url(tmp_path, "claude-5") == "https://web.chatplayground.ai/chat/bbb"


def test_reset_thread_removes_existing(tmp_path):
    state.set_thread_url(tmp_path, "gpt-5", "https://web.chatplayground.ai/chat/aaa")
    state.reset_thread(tmp_path, "gpt-5")
    assert state.get_thread_url(tmp_path, "gpt-5") is None


def test_reset_thread_noop_when_missing(tmp_path):
    state.reset_thread(tmp_path, "never-used-model")
    assert state.get_thread_url(tmp_path, "never-used-model") is None


def test_load_threads_empty_dict_when_missing(tmp_path):
    assert state.load_threads(tmp_path) == {}


def test_load_threads_empty_dict_when_corrupted(tmp_path):
    (tmp_path / "threads.json").write_text("not json")
    assert state.load_threads(tmp_path) == {}
