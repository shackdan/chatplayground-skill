import json
import subprocess

from chatplayground_skill import onepassword


def _fake_run(returncode=0, stdout="", stderr=""):
    def run_fn(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)

    return run_fn


def _fields_json(username="me@example.com", password="super-secret"):
    # `op item get --fields ... --format json` returns a top-level JSON
    # array of field objects, not {"fields": [...]}.
    return json.dumps(
        [
            {"label": "username", "value": username},
            {"label": "password", "value": password},
        ]
    )


def test_returns_none_when_op_not_installed(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: None)
    assert onepassword.get_credentials() is None


def test_returns_credentials_on_success(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: "/opt/homebrew/bin/op")
    run_fn = _fake_run(returncode=0, stdout=_fields_json("me@example.com", "super-secret"))
    assert onepassword.get_credentials(run_fn=run_fn) == (
        "me@example.com",
        "super-secret",
    )


def test_returns_none_when_op_exits_nonzero(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: "/opt/homebrew/bin/op")
    run_fn = _fake_run(returncode=1, stdout="", stderr="[ERROR] item not found")
    assert onepassword.get_credentials(run_fn=run_fn) is None


def test_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: "/opt/homebrew/bin/op")
    run_fn = _fake_run(returncode=0, stdout="not json")
    assert onepassword.get_credentials(run_fn=run_fn) is None


def test_returns_none_when_fields_missing(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: "/opt/homebrew/bin/op")
    run_fn = _fake_run(returncode=0, stdout=json.dumps([{"label": "username", "value": "me@example.com"}]))
    assert onepassword.get_credentials(run_fn=run_fn) is None


def test_item_and_vault_passed_through_to_op_invocation(monkeypatch):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: "/opt/homebrew/bin/op")
    captured = {}

    def run_fn(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout=_fields_json(), stderr="")

    onepassword.get_credentials(item="chatplayground.ai", vault="automation", run_fn=run_fn)
    assert "chatplayground.ai" in captured["args"]
    assert "automation" in captured["args"]
    # --vault must immediately precede the vault name, not just appear
    # anywhere, or op would silently search the wrong vault.
    assert captured["args"][captured["args"].index("--vault") + 1] == "automation"


def test_password_never_printed(monkeypatch, capsys):
    monkeypatch.setattr(onepassword.shutil, "which", lambda name: "/opt/homebrew/bin/op")
    run_fn = _fake_run(returncode=0, stdout=_fields_json("me@example.com", "super-secret-password"))
    onepassword.get_credentials(run_fn=run_fn)
    captured = capsys.readouterr()
    assert "super-secret-password" not in captured.out
    assert "super-secret-password" not in captured.err
