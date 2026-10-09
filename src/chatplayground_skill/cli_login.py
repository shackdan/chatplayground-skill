import argparse
import getpass
import sys
from pathlib import Path
from typing import Callable, Optional

from . import onepassword, state
from .browser import run_login as default_run_login

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="login.py",
        description="Log in to ChatPlayground interactively and save the session.",
    )


def main(
    argv: Optional[list] = None,
    run_login_fn: Callable[[str, str], dict] = default_run_login,
    state_dir: Optional[Path] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    get_1password_credentials: Callable[[], Optional[tuple]] = onepassword.get_credentials,
) -> int:
    build_arg_parser().parse_args(argv)
    sdir = state_dir if state_dir is not None else DEFAULT_STATE_DIR

    user, pw = username, password
    if user is None and pw is None:
        creds = get_1password_credentials()
        if creds is not None:
            user, pw = creds
            print(f"using 1Password item '{onepassword.DEFAULT_ITEM}' for credentials")

    if user is None:
        user = input("ChatPlayground email: ")
    if pw is None:
        pw = getpass.getpass("ChatPlayground password: ")

    storage_state = run_login_fn(user, pw)
    state.save_storage_state(sdir, storage_state)
    print("login succeeded; session saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
