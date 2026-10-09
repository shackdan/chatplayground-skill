import stat

from chatplayground_skill import state
from chatplayground_skill.cli_login import main


def test_saves_storage_state_from_injected_login(tmp_path):
    fake_storage_state = {"cookies": [{"name": "session", "value": "abc123"}], "origins": []}

    code = main(
        argv=[],
        run_login_fn=lambda user, pw: fake_storage_state,
        state_dir=tmp_path,
        username="me@example.com",
        password="super-secret",
    )

    assert code == 0
    assert state.load_storage_state(tmp_path) == fake_storage_state


def test_storage_state_file_has_0600_permissions(tmp_path):
    main(
        argv=[],
        run_login_fn=lambda user, pw: {"cookies": [{"name": "s", "value": "v"}]},
        state_dir=tmp_path,
        username="me@example.com",
        password="super-secret",
    )
    path = tmp_path / "storage_state.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_password_never_printed(tmp_path, capsys):
    main(
        argv=[],
        run_login_fn=lambda user, pw: {"cookies": [{"name": "s", "value": "v"}]},
        state_dir=tmp_path,
        username="me@example.com",
        password="super-secret-password",
    )
    captured = capsys.readouterr()
    assert "super-secret-password" not in captured.out
    assert "super-secret-password" not in captured.err


def test_credentials_passed_through_to_login_fn(tmp_path):
    seen = {}

    def fake_login(user, pw):
        seen["user"] = user
        seen["pw"] = pw
        return {"cookies": [{"name": "s", "value": "v"}]}

    main(argv=[], run_login_fn=fake_login, state_dir=tmp_path, username="me@example.com", password="super-secret")
    assert seen == {"user": "me@example.com", "pw": "super-secret"}


def test_uses_1password_credentials_when_available(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("should not prompt when 1Password supplies credentials")

    monkeypatch.setattr("builtins.input", explode)
    monkeypatch.setattr("getpass.getpass", explode)

    seen = {}

    def fake_login(user, pw):
        seen["user"], seen["pw"] = user, pw
        return {"cookies": [{"name": "s", "value": "v"}]}

    code = main(
        argv=[],
        run_login_fn=fake_login,
        state_dir=tmp_path,
        get_1password_credentials=lambda: ("1p-user@example.com", "1p-secret"),
    )
    assert code == 0
    assert seen == {"user": "1p-user@example.com", "pw": "1p-secret"}


def test_falls_back_to_prompt_when_1password_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "prompted-user@example.com")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "prompted-secret")

    seen = {}

    def fake_login(user, pw):
        seen["user"], seen["pw"] = user, pw
        return {"cookies": [{"name": "s", "value": "v"}]}

    code = main(
        argv=[],
        run_login_fn=fake_login,
        state_dir=tmp_path,
        get_1password_credentials=lambda: None,
    )
    assert code == 0
    assert seen == {"user": "prompted-user@example.com", "pw": "prompted-secret"}


def test_1password_password_never_printed(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("unused")))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": (_ for _ in ()).throw(AssertionError("unused")))

    main(
        argv=[],
        run_login_fn=lambda user, pw: {"cookies": [{"name": "s", "value": "v"}]},
        state_dir=tmp_path,
        get_1password_credentials=lambda: ("1p-user@example.com", "1p-super-secret-password"),
    )
    captured = capsys.readouterr()
    assert "1p-super-secret-password" not in captured.out
    assert "1p-super-secret-password" not in captured.err


def test_explicit_credentials_skip_1password_lookup(tmp_path):
    def explode():
        raise AssertionError("should not consult 1Password when credentials are given explicitly")

    code = main(
        argv=[],
        run_login_fn=lambda user, pw: {"cookies": [{"name": "s", "value": "v"}]},
        state_dir=tmp_path,
        username="me@example.com",
        password="super-secret",
        get_1password_credentials=explode,
    )
    assert code == 0
