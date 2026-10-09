# ChatPlayground Query Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill that queries ChatPlayground (web.chatplayground.ai) via a single Bash call per question, returning only the reply text, with login handled entirely out-of-band so credentials never enter Claude's context.

**Architecture:** A small Python package (`src/chatplayground_skill/`) separates pure/testable logic (state persistence, response-completion heuristic, CLI orchestration with dependency-injected browser calls) from the one file that actually drives Playwright (`browser.py`, verified manually since it drives a live third-party site). Two thin executable scripts (`scripts/query.py`, `scripts/login.py`) are what Claude and the user actually invoke.

**Tech Stack:** Python 3.10+, Playwright (sync API), pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-chatplayground-query-design.md`

## Global Constraints

- `state/` directory permissions: `0700`. `state/storage_state.json` permissions: `0600`.
- `state/` must be listed in `.gitignore` before any other file is committed — it must never enter git history.
- The raw password must never be written to disk, printed, logged, passed as a CLI argument, or set as an environment variable — it lives only in `login.py`'s process memory for the duration of the login attempt.
- `query.py` exit codes: `0` success, `1` generic failure (timeout, unknown model), `2` not authenticated, `3` selector/layout mismatch.
- Default response-wait timeout: 90 seconds, overridable via `CHATPLAYGROUND_QUERY_TIMEOUT` env var or `--timeout`.
- `--model` is a required argument to `query.py` (caller specifies the model per query, per the approved design).
- Each model gets its own persisted conversation thread in `state/threads.json`; switching models never mixes histories.
- `query.py` must print nothing but the reply text to stdout on success — no HTML, no screenshots, no intermediate state.

## Review Focus

- An unknown/misspelled `--model` value must produce a clear error (exit 1 naming the model), not silently create a thread against the wrong model. → tested in Task 6.
- Prompts containing quotes, newlines, or other special characters must reach ChatPlayground unchanged, not be mangled by argument parsing. → tested in Task 6.
- A corrupted or truncated `storage_state.json` (e.g. from an interrupted write) must be treated as "not authenticated," never crash with a raw JSON error. → tested in Task 2.
- Setting one model's thread URL must never clobber another model's previously stored entry in `threads.json`. → tested in Task 2.
- `--reset` on a model with no existing thread must be a no-op, not an error. → tested in Task 2 and Task 6.

---

### Task 1: Project scaffolding + errors module

**Files:**
- Create: `.gitignore`
- Create: `setup.sh`
- Create: `conftest.py`
- Create: `src/chatplayground_skill/__init__.py`
- Create: `src/chatplayground_skill/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Produces: `NotAuthenticatedError`, `SelectorNotFoundError(selector_name: str)` (has `.selector_name`), `QueryTimeoutError`, `ModelNotFoundError(model_name: str)` (has `.model_name`) — all importable from `chatplayground_skill.errors`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_errors.py
from chatplayground_skill.errors import (
    ModelNotFoundError,
    NotAuthenticatedError,
    QueryTimeoutError,
    SelectorNotFoundError,
)


def test_not_authenticated_error_is_exception():
    assert isinstance(NotAuthenticatedError(), Exception)


def test_query_timeout_error_is_exception():
    assert isinstance(QueryTimeoutError(), Exception)


def test_selector_not_found_error_stores_selector_name():
    err = SelectorNotFoundError("chat_input")
    assert err.selector_name == "chat_input"
    assert "chat_input" in str(err)


def test_model_not_found_error_stores_model_name():
    err = ModelNotFoundError("gpt-5")
    assert err.model_name == "gpt-5"
    assert "gpt-5" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chatplayground_skill'`

- [ ] **Step 3: Create scaffolding files**

```gitignore
# .gitignore
state/
__pycache__/
*.pyc
.pytest_cache/
```

```bash
#!/usr/bin/env bash
# setup.sh
set -euo pipefail
pip install --user playwright pytest
python3 -m playwright install chromium
```

```python
# conftest.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
```

```python
# src/chatplayground_skill/__init__.py
```

- [ ] **Step 4: Write the implementation**

```python
# src/chatplayground_skill/errors.py
class NotAuthenticatedError(Exception):
    """Raised when the stored session is missing or ChatPlayground reports logged-out."""


class SelectorNotFoundError(Exception):
    def __init__(self, selector_name: str):
        self.selector_name = selector_name
        super().__init__(f"selector '{selector_name}' not found on page")


class QueryTimeoutError(Exception):
    """Raised when response generation does not finish within the timeout."""


class ModelNotFoundError(Exception):
    def __init__(self, model_name: str):
        self.model_name = model_name
        super().__init__(f"model '{model_name}' not found in ChatPlayground's picker")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_errors.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Make setup.sh executable and commit**

```bash
chmod +x setup.sh
git add .gitignore setup.sh conftest.py src/chatplayground_skill/__init__.py src/chatplayground_skill/errors.py tests/test_errors.py
git commit -m "Add project scaffolding and errors module"
```

---

### Task 2: State module (storage_state + threads.json management)

**Files:**
- Create: `src/chatplayground_skill/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing beyond stdlib.
- Produces (all take `state_dir: Path` as first arg): `ensure_state_dir(state_dir)`, `has_valid_session(state_dir) -> bool`, `save_storage_state(state_dir, data: dict)`, `load_storage_state(state_dir) -> dict`, `load_threads(state_dir) -> dict`, `save_threads(state_dir, threads: dict)`, `get_thread_url(state_dir, model: str) -> str | None`, `set_thread_url(state_dir, model: str, url: str)`, `reset_thread(state_dir, model: str)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_state.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chatplayground_skill.state'`

- [ ] **Step 3: Write the implementation**

```python
# src/chatplayground_skill/state.py
import json
import os
import stat
from pathlib import Path
from typing import Optional


def ensure_state_dir(state_dir: Path) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, stat.S_IRWXU)


def _storage_state_path(state_dir: Path) -> Path:
    return state_dir / "storage_state.json"


def _threads_path(state_dir: Path) -> Path:
    return state_dir / "threads.json"


def _atomic_write(path: Path, content: str, mode: int) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content)
    os.chmod(tmp_path, mode)
    os.replace(tmp_path, path)


def has_valid_session(state_dir: Path) -> bool:
    path = _storage_state_path(state_dir)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return bool(data.get("cookies"))


def save_storage_state(state_dir: Path, data: dict) -> None:
    ensure_state_dir(state_dir)
    _atomic_write(_storage_state_path(state_dir), json.dumps(data), stat.S_IRUSR | stat.S_IWUSR)


def load_storage_state(state_dir: Path) -> dict:
    path = _storage_state_path(state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def load_threads(state_dir: Path) -> dict:
    path = _threads_path(state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_threads(state_dir: Path, threads: dict) -> None:
    ensure_state_dir(state_dir)
    _atomic_write(_threads_path(state_dir), json.dumps(threads), stat.S_IRUSR | stat.S_IWUSR)


def get_thread_url(state_dir: Path, model: str) -> Optional[str]:
    return load_threads(state_dir).get(model)


def set_thread_url(state_dir: Path, model: str, url: str) -> None:
    threads = load_threads(state_dir)
    threads[model] = url
    save_threads(state_dir, threads)


def reset_thread(state_dir: Path, model: str) -> None:
    threads = load_threads(state_dir)
    if model in threads:
        del threads[model]
        save_threads(state_dir, threads)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_state.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/chatplayground_skill/state.py tests/test_state.py
git commit -m "Add state module for session and thread persistence"
```

---

### Task 3: Completion heuristic module

**Files:**
- Create: `src/chatplayground_skill/completion.py`
- Test: `tests/test_completion.py`

**Interfaces:**
- Produces: `is_response_stable(history: list[str], window: int = 2) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_completion.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_completion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chatplayground_skill.completion'`

- [ ] **Step 3: Write the implementation**

```python
# src/chatplayground_skill/completion.py
def is_response_stable(history: list, window: int = 2) -> bool:
    if len(history) < window:
        return False
    recent = history[-window:]
    if any(not text.strip() for text in recent):
        return False
    return len(set(recent)) == 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_completion.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/chatplayground_skill/completion.py tests/test_completion.py
git commit -m "Add response-completion heuristic"
```

---

### Task 4: Discover ChatPlayground selectors

This task is manual-discovery-driven, not TDD: the exact CSS selectors for
ChatPlayground's UI cannot be known without inspecting the live site (this
was flagged as an explicit open question in the spec). The task's
deliverable is still concrete and independently verifiable via the smoke
script in Step 3.

**Files:**
- Create: `src/chatplayground_skill/selectors.py`
- Create: `scripts/dev_check_selectors.py` (manual dev tool, not part of the automated test suite)

**Interfaces:**
- Produces: `SELECTORS: dict` with exactly these keys: `login_email_input`, `login_password_input`, `login_submit_button`, `logged_in_indicator`, `new_chat_button`, `model_picker_trigger`, `model_option`, `chat_input`, `send_button`, `stop_generating_button`, `assistant_message_bubble`.

- [ ] **Step 1: Create `src/chatplayground_skill/selectors.py`**

Create the file with a module-level `SELECTORS: dict` containing exactly
the eleven keys listed above. Two keys have a required shape:

- `model_option` must contain a literal `{model}` format placeholder, so
  that `SELECTORS["model_option"].format(model=model)` yields a selector
  matching one specific model's row in the model picker (e.g. something
  shaped like `"[data-model-name='{model}']"`, using whatever attribute
  or text ChatPlayground actually exposes).
- `assistant_message_bubble` must resolve to only the single most recent
  assistant message (e.g. via a `:last-of-type`-style selector), not all
  messages in the thread.

Leave this as a committed-but-incomplete file for now — Step 2 fills in
real values before this task is considered done.

- [ ] **Step 2: Inspect the live site and fill in every selector**

Open `https://web.chatplayground.ai/` in a real browser (regular Chrome
with DevTools, or the claude-in-chrome skill if driving it interactively)
and log in with a real account. Inspect and record the exact CSS selector
for each of:

- The login form's email input, password input, and submit button.
- An element that is present only when logged in (for `logged_in_indicator`).
- The "new chat" control.
- The model picker's trigger element, and one option row within it (to
  derive the `{model}`-templated `model_option` selector).
- The chat message textarea and its send button.
- The "stop generating" control that appears while a response is streaming.
- The chat bubble containing the most recent assistant message.

Fill all eleven values into `SELECTORS` in `selectors.py`.

- [ ] **Step 3: Create the verification smoke script**

```python
#!/usr/bin/env python3
# scripts/dev_check_selectors.py
"""Manual dev tool: verifies every static SELECTORS entry resolves on the
live site. Run after editing selectors.py and after logging in once via
scripts/login.py. Not part of the automated test suite."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from playwright.sync_api import sync_playwright

from chatplayground_skill import state
from chatplayground_skill.selectors import SELECTORS

STATE_DIR = Path(__file__).resolve().parent.parent / "state"
BASE_URL = "https://web.chatplayground.ai/"

STATIC_KEYS = [
    "login_email_input",
    "login_password_input",
    "login_submit_button",
    "logged_in_indicator",
    "new_chat_button",
    "model_picker_trigger",
    "chat_input",
    "send_button",
]


def main() -> int:
    storage_state = state.load_storage_state(STATE_DIR)
    ok = True
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(storage_state=storage_state or None)
        page = context.new_page()
        page.goto(BASE_URL)
        for key in STATIC_KEYS:
            selector = SELECTORS[key]
            found = page.query_selector(selector) is not None
            print(f"{'OK  ' if found else 'FAIL'} {key}: {selector!r}")
            ok = ok and found
        input("Inspect model_option / stop_generating_button / "
              "assistant_message_bubble manually, then press Enter to close...")
        browser.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

(`model_option`, `stop_generating_button`, and `assistant_message_bubble`
depend on transient page state — an open picker or an in-flight response —
so they're checked visually in the manual pause rather than by the static
loop.)

- [ ] **Step 4: Run the smoke script and iterate until every static key passes**

Run: `! python3 scripts/dev_check_selectors.py`
Expected: every `STATIC_KEYS` line prints `OK`. If any prints `FAIL`, fix
that selector in `selectors.py` and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/chatplayground_skill/selectors.py scripts/dev_check_selectors.py
git commit -m "Add discovered ChatPlayground DOM selectors and verification tool"
```

---

### Task 5: Browser automation module (login + query driving)

Not unit-tested (drives a live third-party site via a real browser, per
the spec's testing approach) — verified by import-sanity here and full
manual end-to-end verification in Task 10.

**Files:**
- Create: `src/chatplayground_skill/browser.py`

**Interfaces:**
- Consumes: `SELECTORS` (Task 4), `is_response_stable` (Task 3), `NotAuthenticatedError`, `SelectorNotFoundError`, `ModelNotFoundError`, `QueryTimeoutError` (Task 1).
- Produces: `run_login(username: str, password: str) -> dict`, `QueryResult` dataclass with fields `reply: str`, `thread_url: str`, `run_query(prompt: str, model: str, thread_url: str | None, storage_state: dict, timeout_s: int = 90) -> QueryResult`, `BASE_URL: str`, `DEFAULT_QUERY_TIMEOUT_S: int`.

- [ ] **Step 1: Write the implementation**

```python
# src/chatplayground_skill/browser.py
import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright

from .completion import is_response_stable
from .errors import (
    ModelNotFoundError,
    NotAuthenticatedError,
    QueryTimeoutError,
    SelectorNotFoundError,
)
from .selectors import SELECTORS

BASE_URL = "https://web.chatplayground.ai/"
LOGIN_CONFIRM_TIMEOUT_MS = 15_000
POLL_INTERVAL_S = 1.0
DEFAULT_QUERY_TIMEOUT_S = 90


def run_login(username: str, password: str) -> dict:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BASE_URL)
        page.fill(SELECTORS["login_email_input"], username)
        page.fill(SELECTORS["login_password_input"], password)
        page.click(SELECTORS["login_submit_button"])

        try:
            page.wait_for_selector(SELECTORS["logged_in_indicator"], timeout=LOGIN_CONFIRM_TIMEOUT_MS)
        except Exception:
            input(
                "Could not confirm login automatically. Complete login manually "
                "in the opened browser window, then press Enter here..."
            )
            page.wait_for_selector(SELECTORS["logged_in_indicator"], timeout=LOGIN_CONFIRM_TIMEOUT_MS)

        storage_state = context.storage_state()
        browser.close()
        return storage_state


@dataclass
class QueryResult:
    reply: str
    thread_url: str


def run_query(
    prompt: str,
    model: str,
    thread_url: Optional[str],
    storage_state: dict,
    timeout_s: int = DEFAULT_QUERY_TIMEOUT_S,
) -> QueryResult:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(storage_state=storage_state)
        page = context.new_page()

        page.goto(thread_url if thread_url else BASE_URL)

        if not _is_logged_in(page):
            browser.close()
            raise NotAuthenticatedError()

        if not thread_url:
            _start_new_thread_for_model(page, model)

        _require_selector(page, "chat_input")
        page.fill(SELECTORS["chat_input"], prompt)
        _require_selector(page, "send_button")
        page.click(SELECTORS["send_button"])

        reply = _wait_for_reply(page, timeout_s)
        result = QueryResult(reply=reply, thread_url=page.url)
        browser.close()
        return result


def _is_logged_in(page) -> bool:
    try:
        page.wait_for_selector(SELECTORS["logged_in_indicator"], timeout=5_000)
        return True
    except Exception:
        return False


def _require_selector(page, key: str) -> None:
    try:
        page.wait_for_selector(SELECTORS[key], timeout=10_000)
    except Exception:
        raise SelectorNotFoundError(key)


def _start_new_thread_for_model(page, model: str) -> None:
    _require_selector(page, "new_chat_button")
    page.click(SELECTORS["new_chat_button"])
    _require_selector(page, "model_picker_trigger")
    page.click(SELECTORS["model_picker_trigger"])

    option_selector = SELECTORS["model_option"].format(model=model)
    try:
        page.wait_for_selector(option_selector, timeout=5_000)
    except Exception:
        raise ModelNotFoundError(model)
    page.click(option_selector)


def _wait_for_reply(page, timeout_s: int) -> str:
    deadline = time.monotonic() + timeout_s
    history = []
    while time.monotonic() < deadline:
        try:
            bubble = page.query_selector(SELECTORS["assistant_message_bubble"])
            text = bubble.inner_text() if bubble else ""
        except Exception:
            text = ""
        history.append(text)
        stop_visible = page.query_selector(SELECTORS["stop_generating_button"]) is not None
        if not stop_visible and is_response_stable(history):
            return history[-1]
        time.sleep(POLL_INTERVAL_S)
    raise QueryTimeoutError()
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python3 -c "import sys; sys.path.insert(0, 'src'); import chatplayground_skill.browser"`
Expected: no output, exit code 0 (confirms no syntax errors and that
Playwright is installed correctly).

- [ ] **Step 3: Commit**

```bash
git add src/chatplayground_skill/browser.py
git commit -m "Add Playwright-driven login and query automation"
```

---

### Task 6: `cli_query` — argument parsing, orchestration, exit codes

**Files:**
- Create: `src/chatplayground_skill/cli_query.py`
- Test: `tests/test_cli_query.py`

**Interfaces:**
- Consumes: `state.has_valid_session`, `state.get_thread_url`, `state.set_thread_url`, `state.reset_thread`, `state.load_storage_state` (Task 2); `browser.run_query`, `browser.QueryResult` (Task 5); `NotAuthenticatedError`, `SelectorNotFoundError`, `ModelNotFoundError`, `QueryTimeoutError` (Task 1).
- Produces: `build_arg_parser() -> argparse.ArgumentParser`, `main(argv: list | None = None, query_fn=browser.run_query, state_dir: Path | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_query.py
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


def test_success_prints_reply_and_saves_thread_url(tmp_path, capsys):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        assert kwargs["prompt"] == "hello"
        assert kwargs["model"] == "gpt-5"
        assert kwargs["thread_url"] is None
        return QueryResult(reply="hi there", thread_url="https://web.chatplayground.ai/chat/1")

    code = main(["hello", "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0
    assert capsys.readouterr().out.strip() == "hi there"
    assert state.get_thread_url(sdir, "gpt-5") == "https://web.chatplayground.ai/chat/1"


def test_resumes_existing_thread(tmp_path):
    sdir = _authenticated(tmp_path)
    state.set_thread_url(sdir, "gpt-5", "https://web.chatplayground.ai/chat/existing")

    def fake_query_fn(**kwargs):
        assert kwargs["thread_url"] == "https://web.chatplayground.ai/chat/existing"
        return QueryResult(reply="ok", thread_url="https://web.chatplayground.ai/chat/existing")

    code = main(["hello", "--model", "gpt-5"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0


def test_reset_clears_thread_before_query(tmp_path):
    sdir = _authenticated(tmp_path)
    state.set_thread_url(sdir, "gpt-5", "https://web.chatplayground.ai/chat/old")

    def fake_query_fn(**kwargs):
        assert kwargs["thread_url"] is None
        return QueryResult(reply="ok", thread_url="https://web.chatplayground.ai/chat/new")

    code = main(["hello", "--model", "gpt-5", "--reset"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0
    assert state.get_thread_url(sdir, "gpt-5") == "https://web.chatplayground.ai/chat/new"


def test_reset_is_noop_when_no_existing_thread(tmp_path):
    sdir = _authenticated(tmp_path)

    def fake_query_fn(**kwargs):
        assert kwargs["thread_url"] is None
        return QueryResult(reply="ok", thread_url="https://web.chatplayground.ai/chat/new")

    code = main(["hello", "--model", "never-used", "--reset"], query_fn=fake_query_fn, state_dir=sdir)
    assert code == 0


def test_special_characters_in_prompt_passed_through_unchanged(tmp_path):
    sdir = _authenticated(tmp_path)
    tricky = 'quote " and newline\nand emoji \U0001F389'

    def fake_query_fn(**kwargs):
        assert kwargs["prompt"] == tricky
        return QueryResult(reply="ok", thread_url="https://web.chatplayground.ai/chat/1")

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_query.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chatplayground_skill.cli_query'`

- [ ] **Step 3: Write the implementation**

```python
# src/chatplayground_skill/cli_query.py
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

    thread_url = state.get_thread_url(sdir, args.model)
    storage_state = state.load_storage_state(sdir)

    try:
        result = query_fn(
            prompt=args.prompt,
            model=args.model,
            thread_url=thread_url,
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

    state.set_thread_url(sdir, args.model, result.thread_url)
    print(result.reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_query.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/chatplayground_skill/cli_query.py tests/test_cli_query.py
git commit -m "Add query CLI orchestration with exit-code mapping"
```

---

### Task 7: `cli_login` — credential capture & orchestration

**Files:**
- Create: `src/chatplayground_skill/cli_login.py`
- Test: `tests/test_cli_login.py`

**Interfaces:**
- Consumes: `state.save_storage_state` (Task 2); `browser.run_login` (Task 5).
- Produces: `build_arg_parser() -> argparse.ArgumentParser`, `main(argv: list | None = None, run_login_fn=browser.run_login, state_dir: Path | None = None, username: str | None = None, password: str | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_login.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_login.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chatplayground_skill.cli_login'`

- [ ] **Step 3: Write the implementation**

```python
# src/chatplayground_skill/cli_login.py
import argparse
import getpass
import sys
from pathlib import Path
from typing import Callable, Optional

from . import state
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
) -> int:
    build_arg_parser().parse_args(argv)
    sdir = state_dir if state_dir is not None else DEFAULT_STATE_DIR

    user = username if username is not None else input("ChatPlayground email: ")
    pw = password if password is not None else getpass.getpass("ChatPlayground password: ")

    storage_state = run_login_fn(user, pw)
    state.save_storage_state(sdir, storage_state)
    print("login succeeded; session saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_login.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/chatplayground_skill/cli_login.py tests/test_cli_login.py
git commit -m "Add login CLI with getpass-based credential capture"
```

---

### Task 8: Thin executable scripts

**Files:**
- Create: `scripts/query.py`
- Create: `scripts/login.py`
- Test: `tests/test_scripts_smoke.py`

**Interfaces:**
- Consumes: `cli_query.main` (Task 6), `cli_login.main` (Task 7).
- Produces: two executables Claude/the user actually invoke: `scripts/query.py` and `scripts/login.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scripts_smoke.py
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_query_script_help():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "query.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_login_script_help():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "login.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scripts_smoke.py -v`
Expected: FAIL (`scripts/query.py`/`scripts/login.py` don't exist yet — non-zero exit, `FileNotFoundError` or similar)

- [ ] **Step 3: Write the implementations**

```python
#!/usr/bin/env python3
# scripts/query.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chatplayground_skill.cli_query import main

if __name__ == "__main__":
    sys.exit(main())
```

```python
#!/usr/bin/env python3
# scripts/login.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from chatplayground_skill.cli_login import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Make executable and run tests to verify they pass**

```bash
chmod +x scripts/query.py scripts/login.py
```

Run: `pytest tests/test_scripts_smoke.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/query.py scripts/login.py tests/test_scripts_smoke.py
git commit -m "Add thin executable entry points for query and login"
```

---

### Task 9: SKILL.md

**Files:**
- Create: `SKILL.md`

**Interfaces:**
- Consumes: exit-code contract from Task 6 (`0`/`1`/`2`/`3`) and the `! scripts/login.py` convention from Task 7/8.
- Produces: the skill definition Claude Code loads to know when/how to use this skill.

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: chatplayground-query
description: Query the ChatPlayground chatbot (web.chatplayground.ai) and get back just the reply text, without the browsing steps filling up context. Use when the user asks to ask/query/check with ChatPlayground or a specific model hosted there.
---

# ChatPlayground Query

Use `scripts/query.py "<prompt>" --model <model name>` via Bash to ask
ChatPlayground a question. Treat stdout as the literal answer — print it
or use it directly; do not re-ask the question in your own words.

Each model keeps its own persistent conversation thread automatically.
Pass `--reset` to start a fresh thread for that model.

## If it exits non-zero

- **Exit 2 (not authenticated):** Tell the user to run `! scripts/login.py`
  themselves in their own terminal. Do not ask the user for their
  password yourself, and do not attempt to log in on their behalf — the
  login flow is interactive and must be run directly by the user so their
  credentials never pass through you.
- **Exit 3 (selector not found):** Tell the user ChatPlayground's page
  layout appears to have changed and this skill needs updating.
- **Exit 1 (other failure):** Relay the stderr message (timeout or
  unknown model name).

## Setup (one-time, if not already done)

`./setup.sh` installs Playwright and Chromium. Then the user must run
`! scripts/login.py` once before the first query.
```

- [ ] **Step 2: Commit**

```bash
git add SKILL.md
git commit -m "Add SKILL.md"
```

---

### Task 10: Final manual end-to-end verification

No new source files — this is the manual verification pass from the
spec's Testing Approach section, run against the real site.

**Files:** none (verification only)

- [ ] **Step 1: Run the full automated test suite**

Run: `pytest -v`
Expected: all tests from Tasks 1–8 PASS.

- [ ] **Step 2: Real login**

Run: `! scripts/login.py`
Expected: browser opens, login succeeds (manually if automated fill is
blocked), `state/storage_state.json` is created with `0600` permissions.

- [ ] **Step 3: Fresh-thread query**

Run: `! scripts/query.py "What is 2+2?" --model <a real model name from the picker>`
Expected: exit 0, stdout is a plausible answer, `state/threads.json` gains
an entry for that model.

- [ ] **Step 4: Thread-resume query**

Run: `! scripts/query.py "What did I just ask you?" --model <same model>`
Expected: exit 0, the reply shows ChatPlayground retained the prior
message (confirms thread resumption, not a fresh chat).

- [ ] **Step 5: Model-switch query**

Run: `! scripts/query.py "What is 2+2?" --model <a different real model>`
Expected: exit 0, a new entry is added to `threads.json` for this model,
and the first model's entry is untouched.

- [ ] **Step 6: Reset query**

Run: `! scripts/query.py "Hello again" --model <first model> --reset`
Expected: exit 0, `threads.json`'s entry for the first model is replaced
with a new thread URL.

- [ ] **Step 7: Expired-session handling**

Run: `rm state/storage_state.json && ! scripts/query.py "test" --model <a real model>`
Expected: exit 2, stderr tells the user to run `! scripts/login.py`, no
crash or hang. Re-run `! scripts/login.py` afterward to restore the
session for normal use.

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "Complete chatplayground-query skill" --allow-empty
```
