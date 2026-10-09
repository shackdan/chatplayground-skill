import argparse
import os
import sys
from pathlib import Path
from typing import Callable, Optional

from . import state
from .browser import QueryResult
from .browser import run_query as default_run_query
from .errors import ModelNotFoundError, NotAuthenticatedError, QueryTimeoutError, SelectorNotFoundError

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"


def _default_state_dir() -> Path:
    override = os.environ.get("CHATPLAYGROUND_STATE_DIR")
    return Path(override) if override else DEFAULT_STATE_DIR


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="query.py")
    parser.add_argument("prompt", help="the question to send to ChatPlayground")
    parser.add_argument("--model", required=True, help="which model's thread to use")
    parser.add_argument("--reset", action="store_true", help="start a new thread for this model")
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("CHATPLAYGROUND_QUERY_TIMEOUT", "90")),
    )
    return parser


def main(
    argv: Optional[list] = None,
    query_fn: Callable[..., QueryResult] = default_run_query,
    state_dir: Optional[Path] = None,
) -> int:
    args = build_arg_parser().parse_args(argv)
    sdir = state_dir if state_dir is not None else _default_state_dir()

    if not state.has_valid_session(sdir):
        print("not authenticated — ask the user to run `! scripts/login.py`", file=sys.stderr)
        return 2

    if args.reset:
        state.reset_thread(sdir, args.model)

    thread_anchor = state.get_thread_anchor(sdir, args.model)
    storage_state = state.load_storage_state(sdir)

    try:
        result = query_fn(
            prompt=args.prompt,
            model=args.model,
            thread_anchor=thread_anchor,
            storage_state=storage_state,
            timeout_s=args.timeout,
        )
    except NotAuthenticatedError:
        print("not authenticated — ask the user to run `! scripts/login.py`", file=sys.stderr)
        return 2
    except SelectorNotFoundError as exc:
        print(
            f"ChatPlayground's page layout appears to have changed "
            f"(missing selector: {exc.selector_name}) — the skill needs updating",
            file=sys.stderr,
        )
        return 3
    except ModelNotFoundError as exc:
        print(f"model not found: {exc.model_name}", file=sys.stderr)
        return 1
    except QueryTimeoutError:
        print("timed out waiting for a response", file=sys.stderr)
        return 1

    state.set_thread_anchor(sdir, args.model, result.thread_anchor)
    print(result.reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
