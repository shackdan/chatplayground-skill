# ChatPlayground Query Skill — Design Spec

**Date:** 2026-10-09
**Status:** Implemented and verified against the live site

> This doc was revised after implementation to describe what was
> actually built. The original design (written before any live
> inspection) assumed a single-screen login form and URL-addressable
> conversations; neither held up once the real site was inspected. See
> §9 for a record of what changed and why.

## Purpose

A personal Claude Code skill that lets Claude query the chatbot at
`https://web.chatplayground.ai/` on the user's behalf, while:

1. Keeping Claude's own context small — the full browser interaction
   (navigation, typing, waiting, DOM inspection) never appears in Claude's
   transcript; only the final answer text does.
2. Handling ChatPlayground's login (username/password) without the
   password ever becoming part of Claude's context — not as a tool-call
   argument, not as printed output, not stored in a way Claude can read.

This is the first subsystem of its kind for the user; no existing flow is
being modified.

## Non-goals

- No generic "any chatbot" support — this skill is specific to
  ChatPlayground's current UI.
- No multi-user/multi-account support — one ChatPlayground login per
  machine user.
- No automated handling of CAPTCHA/MFA challenges — manual fallback only
  (see §4).
- Full browser-driving code (`browser.py`) is not unit-tested (drives a
  live third-party site); it was verified manually and is covered by
  automated tests only at the module boundaries around it (state
  persistence, CLI argument handling, exit-code mapping).

## Architecture Overview

A small Python package (`src/chatplayground_skill/`) separates pure/
testable logic from the one module that drives Playwright. Two thin
executable scripts are what Claude and the user actually invoke. Claude's
only interface to the system is a single Bash invocation of `query.py`
per question, which returns exactly one string: the chatbot's reply.

```
User → Claude → Bash: scripts/query.py "<prompt>" --model "<name>" [--reset]
                           │
                           ├─ not authenticated → exit 2, stderr hint
                           ├─ model not found    → exit 1, stderr names it
                           ├─ selector mismatch  → exit 3, stderr names it
                           ├─ timed out          → exit 1
                           └─ success → stdout: reply text only
```

Login is a separate, human-run step, run in a real terminal (not through
Claude's chat `!` prefix, which has no interactive stdin):

```
User (in their own terminal: ./scripts/login.py) → headed browser
    → getpass prompt → fills ChatPlayground's two-step Clerk login
    → saves session cookies
```

Claude never calls `login.py` itself — it only ever tells the user to run
it themselves.

## File Layout

Repo root (`chatplayground-skill/`) is the skill directory itself:

```
chatplayground-skill/
  SKILL.md                      # instructions for Claude
  setup.sh                      # creates .venv, installs playwright + pytest, installs chromium
  conftest.py                   # adds src/ to sys.path for pytest
  .gitignore                    # excludes state/, .venv/, __pycache__/, .pytest_cache/
  scripts/
    login.py                    # interactive, human-run, headed browser
    query.py                    # the only entry point Claude ever calls
  src/chatplayground_skill/
    __init__.py
    errors.py                   # NotAuthenticatedError, SelectorNotFoundError,
                                 #   QueryTimeoutError, ModelNotFoundError
    state.py                    # storage_state.json + threads.json persistence
    completion.py                # is_response_stable() — pure text-stability heuristic
    selectors.py                 # SELECTORS dict (every CSS/role selector) + HISTORY_TITLE_MAX_CHARS
    browser.py                   # run_login(), run_query() — all Playwright code
    cli_login.py                 # argparse + getpass wiring for login.py
    cli_query.py                 # argparse + orchestration + exit-code mapping for query.py
  tests/
    test_errors.py, test_state.py, test_completion.py,
    test_cli_login.py, test_cli_query.py, test_scripts_smoke.py
  state/                         # chmod 700; gitignored — never committed
    storage_state.json           # Playwright cookies/localStorage, chmod 600
    threads.json                 # {model_name: first_message_text} — see §3
  docs/superpowers/
    specs/2026-10-09-chatplayground-query-design.md    # this file
    plans/2026-10-09-chatplayground-query.md
  .venv/                         # gitignored; created by setup.sh
```

`scripts/login.py` and `scripts/query.py` are thin wrappers: each checks
whether it's running under `.venv`'s interpreter (`sys.prefix !=
sys.base_prefix`) and, if not, re-execs itself via `os.execv` into
`.venv/bin/python3` before importing anything — so they work correctly
regardless of which `python3` invoked them. This was a real bug found
during testing: the obvious `#!/usr/bin/env python3` shebang silently ran
under system Python (no Playwright installed) whenever the script wasn't
invoked with the venv already active.

## Component Detail

### 1. `cli_login.py` + `scripts/login.py` — credential capture & auth

- Run only by the human, interactively, in their own terminal (`!
  scripts/login.py` doesn't work — the chat harness's `!` prefix has no
  interactive stdin for `input()`/`getpass()` to read from).
- `cli_login.main()` prompts for email via `input()` and password via
  `getpass.getpass()` — masked, never echoed, never leaves the process
  (not printed, not returned, not logged). Both are injectable parameters
  for testing.
- Calls `browser.run_login(username, password)`, then
  `state.save_storage_state()` with the result.

### 2. `browser.run_login()` — the actual login automation

ChatPlayground uses **Clerk** for auth, which turned out to be a
two-stage, single-page flow, not a single form:

1. Fill the email field (`input[name="identifier"]`, or briefly
   `input[name="emailAddress"]` if Clerk hasn't yet recognized the
   address), click Continue.
2. Clerk re-renders the same page with a password field added, signaled
   by a URL hash change (`#/create` or similar) rather than a real
   navigation — `page.wait_for_url(re.compile(r"#/"))` is used to detect
   this.
3. Fill the password field, click Continue again.

The Continue button is matched via `role=button[name="Continue"]`
(accessible-name match), not a CSS text selector — Playwright's
`:text-is()` prefers the *smallest* element containing the exact text,
which is the button's inner `<span>`, not the `<button>` itself, so
`button:text-is("Continue")` silently never matches and hangs until
timeout. This was found and fixed during implementation.

- Launches **headed** (visible) Chromium so the user can see what's
  happening and intervene if needed.
- **Fallback for bot-detection/MFA/CAPTCHA:** if login can't be confirmed
  automatically within a timeout, prints "complete login manually in the
  window, then press Enter here" and waits on stdin. The user can always
  type directly into the real visible page — Claude is not involved.
- On confirmed login (URL no longer under `/login`), returns
  `context.storage_state()` (cookies + localStorage only — never the
  password).

### 3. `cli_query.py` + `scripts/query.py` — the only Claude-facing entry point

Usage: `query.py "<prompt text>" --model "<name>" [--reset] [--timeout N]`

- Loads `state/storage_state.json`. If missing or logged-out
  (`state.has_valid_session()` false), exit `2` with a one-line stderr
  message. Claude relays this verbatim; it never attempts to log in
  itself.
- If `--reset`, drops the stored anchor for that model first.
- Resolves the thread anchor via `state.get_thread_anchor()` (see §4),
  calls `browser.run_query()`, maps any raised error to an exit code (see
  §5), and on success saves the (possibly new) anchor and prints the
  reply — nothing else — to stdout.

### 4. `browser.run_query()` — the query automation

`run_query(prompt, model, thread_anchor, storage_state, timeout_s) ->
QueryResult(reply, thread_anchor)`, run **headless**.

- Navigates to the base URL; if redirected to `/login`, raises
  `NotAuthenticatedError`.
- Clicks the model's sidebar link — `role=link[name="<model>"]`, where
  `<model>` must be the *exact* label ChatPlayground shows (e.g.
  `"Claude (Latest Model)"`, `"Kimi K"`). If that link never appears,
  raises `ModelNotFoundError`. Clicking it always opens a **fresh** "New
  Chat" composer for that model — it never auto-resumes a prior
  conversation, which is why thread resumption (below) is a separate
  step.
- If a `thread_anchor` is supplied (resuming), clicks that model's Chat
  History entry whose title exactly matches the anchor truncated to 50
  characters (see §5 for why), then waits for that conversation's prior
  messages to actually finish loading before proceeding — a loading
  spinner means `count()==0` can mean "still fetching," not "confirmed
  empty," which caused a real bug where the previous turn's answer was
  mistaken for a brand-new one (see §9).
- Fills the chat textarea, clicks Send, and waits for a reply: the
  response is tracked by its *fixed index* in the list of
  `assistant_content` elements (the position it appears at once a new
  element shows up) rather than by `.last`, specifically because
  `.last` was observed to transiently point at a stale/wrong element
  during ChatPlayground's own flaky re-renders (see §9).
- Returns `QueryResult(reply=..., thread_anchor=...)` — `thread_anchor`
  stays the same as what was passed in on a resume, or becomes `prompt`
  itself the first time a model is used.

### 5. Thread/model state management (`threads.json`)

ChatPlayground has **no per-conversation URL or ID** — every chat lives
at the same `/chat` path, and the only stable text in the DOM is the
auto-generated Chat History title, which is the first message of that
conversation truncated to exactly 50 characters (confirmed empirically
across ~80 real history entries). So instead of storing a URL,
`threads.json` maps `{model_name: first_message_text}` — the *anchor*.

- On each query: `state.get_thread_anchor(model)`. If set, `run_query`
  resumes by clicking the Chat History entry whose title equals
  `anchor[:50]`. If unset, it's a fresh thread.
- After a successful query, `cli_query.py` calls
  `state.set_thread_anchor(model, result.thread_anchor)` — unchanged on a
  resume, or the first-ever prompt on a fresh thread.
- `--reset` calls `state.reset_thread(model)` first, forcing a fresh
  thread (the old conversation is untouched on ChatPlayground's side,
  just orphaned from `threads.json`).
- Each model's entry is independent (`state.set_thread_anchor` only
  touches that model's key), so switching models never mixes histories.
- Known limitation: two different first messages to the same model that
  happen to share the same 50-character prefix would collide. Judged an
  acceptable edge case rather than something worth engineering around.

### 6. Error handling & edge cases

| Condition | Behavior |
|---|---|
| No `storage_state.json` / session expired | exit 2, stderr hint to run `login.py` |
| `--model` value has no matching sidebar link | exit 1, `ModelNotFoundError`, stderr names it |
| Resuming a thread whose history entry can't be found | exit 3, `SelectorNotFoundError("history_item")` |
| ChatPlayground DOM/selectors changed elsewhere | exit 3, stderr names the missing selector |
| Response generation exceeds timeout | exit 1, `QueryTimeoutError`, no partial text returned |
| Login bot-detection/CAPTCHA/MFA | `login.py` falls back to manual-completion prompt (not an error) |
| Corrupted/truncated `storage_state.json` or `threads.json` | treated as missing/empty, not a crash |

### 7. Secrets at rest

- `state/` directory: `chmod 700`. `state/storage_state.json`: `chmod
  600`. Contains only session cookies/localStorage — the same trust
  level as any "stay logged in" browser session, not a credential vault.
- The raw password exists only in `cli_login.py`'s process memory for the
  duration of the login attempt. Never written to disk, printed, passed
  as a CLI argument, or set as an env var — covered by an automated test
  (`test_password_never_printed`) that asserts a fake password never
  appears in captured stdout/stderr.
- `threads.json` contains only message text the user already sent
  through ChatPlayground — no additional sensitivity beyond what the
  authenticated session already exposes.
- `state/` and `.venv/` are excluded via `.gitignore` from the first
  commit onward.

### 8. SKILL.md instructions (summary of what Claude is told)

- Run `scripts/query.py "<prompt>" --model "<exact sidebar label>"` via
  Bash; treat stdout as the answer.
- `--model` must match ChatPlayground's sidebar label exactly.
- Exit 2 → tell the user to run `! scripts/login.py` themselves in a real
  terminal; never supply credentials yourself.
- Exit 3 → tell the user ChatPlayground's layout may have changed.
- Exit 1 → relay the stderr message (timeout or unknown model).
- Queries can legitimately take 10-60+ seconds; that's expected.

### 9. As-built deviations from the original design

The original design (written before any live inspection) assumed a
single-screen login form and URL-addressable conversations. Both
assumptions broke once the real site was inspected, and the design
adapted during implementation rather than going back through a new
brainstorming cycle, since the changes were implementation-detail
substitutions within already-approved module boundaries, not an
architecture change:

- **Clerk two-step login**, not a single form (§2).
- **No conversation URLs/IDs exist** — `threads.json` stores a
  first-message "anchor" and resumes via Chat History title matching,
  not a saved URL (§5). This was the most consequential discovery;
  confirmed via `AskUserQuestion` before implementing.
- **Reasoning models render a "Thought" block** (observed on Kimi K)
  that had to be explicitly excluded from the extracted reply via a
  `streamdown-content`-scoped selector, rather than reading the whole
  message row's text.
- **Two real race conditions**, both found only by testing against the
  live, authenticated site (not reproducible with fakes/mocks):
  1. Resuming a thread and immediately computing "how many prior turns
     exist" raced against ChatPlayground's own loading spinner — a
     `count()==0` reading during that spinner was wrongly treated as
     "confirmed empty," corrupting the new-turn detection.
  2. Tracking the new reply via `.last` rather than its fixed list index
     let a transient, unrelated element look like "the stable final
     answer" during the app's own flaky re-renders.
- `run_login`/`run_query`'s selectors (`role=button[name="Continue"]`,
  `role=link[name="{model}"]`, etc.) are all byproducts of live
  inspection rather than guesses — see `selectors.py` for the full set
  and rationale comments.

## Testing approach

Unlike the original plan (which assumed no automated tests at all beyond
manual verification), most of the package *is* unit-tested — only
`browser.py` (the Playwright-driving code) is excluded, since it drives a
live third-party site with no sandbox/API:

- `errors.py`, `state.py`, `completion.py`: full pytest coverage,
  including corrupted-file handling, permission bits, and cross-model
  isolation in `threads.json`.
- `cli_login.py`, `cli_query.py`: pytest coverage via dependency-injected
  fake `run_login_fn`/`query_fn`, covering every exit code, `--reset`
  behavior, special characters in prompts, and (critically) that a fake
  password never appears in captured stdout/stderr.
- `scripts/login.py`, `scripts/query.py`: subprocess smoke tests,
  including one that deliberately invokes them with system Python (not
  `.venv`'s) to guard against the venv re-exec regression found during
  testing.
- `browser.py`: manually verified end-to-end against the real site —
  login, fresh-thread query, resumed-thread query, model switch,
  `--reset`, and model-not-found — all confirmed working as of
  2026-10-09.
