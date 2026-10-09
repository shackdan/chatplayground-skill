import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_login_script_help():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "login.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_login_script_help_reexecs_into_venv_when_run_under_system_python():
    # Regression test: invoking the script with a *different* interpreter
    # than .venv's must still work, by re-exec'ing into .venv/bin/python3
    # rather than failing with ModuleNotFoundError on a missing dependency.
    system_python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"
    result = subprocess.run(
        [system_python, str(REPO_ROOT / "scripts" / "login.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
