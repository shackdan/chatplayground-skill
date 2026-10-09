# ChatPlayground Query Skill — Design Spec

**Date:** 2026-10-09
**Status:** Approved for implementation planning

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
- Not unit-testable in the traditional sense (drives a live third-party
  site); verification is manual (see §8).

## Architecture Overview

A standalone Playwright-driven script pair owns all browser interaction
and all credential handling, running out-of-band from Claude's own
tool-calling loop. Claude's only interface to the system is a single Bash
invocation of `query.py` per question, which returns exactly one string:
the chatbot's reply.

```
User → Claude → Bash: scripts/query.py "<prompt>" [--model NAME] [--reset]
                           │
                           ├─ not authenticated → exit 2, stderr hint
                           └─ success → stdout: reply text only
```

Login is a separate, human-run step:

```
User (via `! scripts/login.py`) → headed browser → getpass prompt
    → fills ChatPlayground login form → saves session cookies
```

Claude never calls `login.py` itself — it only ever tells the user to run
it via `! scripts/login.py`, per the existing convention for interactive
logins the user's own terminal must handle.

## File Layout

Repo root (`/Users/dan/Documents/code/chatplayground-skill`) is the skill
directory itself:

```
chatplayground-skill/
  SKILL.md                 # instructions for Claude
  setup.sh                 # one-time: pip install playwright; playwright install chromium
  scripts/
    login.py               # interactive, human-run, headed browser
    query.py                # the only entry point Claude ever calls
    _common.py              # shared Playwright helpers + selectors
  state/                    # chmod 700; gitignored — never committed
    storage_state.json      # Playwright cookies/localStorage, chmod 600
    threads.json            # {model_name: chat_url}
  docs/
    superpowers/specs/
      2026-10-09-chatplayground-query-design.md   # this file
  .gitignore                # must exclude state/
```

Note: `state/` holds session cookies and must never be committed —
`.gitignore` is created alongside the rest of the skill during
implementation, before anything is ever written to `state/`.

## Component Detail

### 1. `login.py` — credential capture & auth

- Run only by the human, interactively, typically via `! scripts/login.py`.
- Launches Chromium **headed** (visible window) via Playwright, navigates
  to ChatPlayground's login page.
- Prompts for username and password at the controlling terminal using
  `getpass.getpass()` — input is masked and never echoed, and this value
  never leaves the Python process (not printed, not returned, not logged).
- Fills the username/password fields and submits using the in-memory
  values.
- **Fallback for bot-detection/MFA/CAPTCHA:** if the script can't confirm
  login succeeded within a short timeout, it prints "complete login
  manually in the window, then press Enter here" and waits on stdin. The
  user can always just type directly into the real visible page as a
  manual escape hatch — Claude is not involved in this path at all.
- On confirmed login (presence of a known logged-in-only element),
  captures `context.storage_state()` and writes it to
  `state/storage_state.json` (`chmod 600`). The raw password is discarded
  when the process exits; it is never written to disk.

### 2. `query.py` — the only Claude-facing entry point

Usage: `query.py "<prompt text>" [--model NAME] [--reset]`

- Loads `state/storage_state.json` into a **headless** Playwright context.
  If the file is missing or the loaded session is logged-out, exit code
  `2` with a one-line stderr message ("not authenticated — ask the user
  to run `! scripts/login.py`"). Claude relays this to the user verbatim;
  it never attempts to log in itself.
- Resolves which thread to use from `state/threads.json` (see §3).
- Types the prompt into the chat input and submits.
- Waits for generation to finish: polls for the "stop generating"
  control to disappear, or for the last assistant bubble's text to stay
  unchanged across two consecutive polls, whichever comes first, capped
  by an overall timeout (default 90s, configurable via env var).
- Extracts only the last assistant message's text content and prints
  **that string alone** to stdout. No HTML, no screenshots, no
  intermediate state ever reaches stdout/Claude.
- Exit codes: `0` success, `1` generic failure (e.g. timeout), `2` not
  authenticated, `3` selector/layout mismatch (site changed — message
  names the missing selector so a human can fix `_common.py`).

### 3. Thread/model state management (`threads.json`)

- A flat JSON map: `{"<model name>": "<chat URL or id>"}`.
- On each query, if the requested `--model` has an entry, `query.py`
  navigates to that URL and appends to the existing thread — giving
  persistent, per-model conversation history across separate invocations.
- If no entry exists for that model, `query.py` starts a new chat,
  selects the model via ChatPlayground's model picker, sends the first
  message, and records the resulting thread URL under that model name.
- `--reset` deletes the current model's entry before proceeding, forcing
  a brand-new thread (old thread is left alone on ChatPlayground's side,
  just orphaned from our state file).
- This means switching models never mixes histories — each model gets
  its own persisted thread, created lazily on first use.

### 4. Error handling & edge cases

| Condition | Behavior |
|---|---|
| No `storage_state.json` / session expired | exit 2, stderr hint to run `login.py` |
| ChatPlayground DOM/selectors changed | exit 3, stderr names the missing selector |
| Response generation exceeds timeout | exit 1, stderr says timeout, no partial text returned |
| `--model` not found in ChatPlayground's picker | exit 1, stderr lists it couldn't find that model |
| Login bot-detection/CAPTCHA/MFA | `login.py` falls back to manual-completion prompt (not an error — part of normal flow) |

### 5. Secrets at rest

- `state/` directory: `chmod 700`.
- `state/storage_state.json`: `chmod 600`. Contains only session
  cookies/localStorage — the same trust level as any "stay logged in"
  browser session, not a credential vault.
- The raw password exists only in `login.py`'s process memory for the
  duration of the login attempt. It is never written to any file, never
  printed, never passed as a CLI argument or environment variable, and
  never returned to Claude.
- `threads.json` contains only chat URLs/ids, no sensitive content beyond
  what ChatPlayground itself already exposes to an authenticated session.
- `state/` is excluded from git via `.gitignore` from the very first
  commit.

### 6. SKILL.md instructions (summary of what Claude is told)

- To answer a question via ChatPlayground, run `scripts/query.py
  "<prompt>" [--model NAME]` via Bash and treat stdout as the answer.
- If it exits 2, tell the user to run `! scripts/login.py` themselves —
  do not attempt to supply credentials yourself in any form.
- If it exits 3, report that ChatPlayground's page layout appears to have
  changed and the skill needs updating.
- Never ask the user for their password directly; the skill's own login
  flow handles that out-of-band.

### 7. Setup / dependencies

- `setup.sh` runs once: `pip install playwright && playwright install
  chromium`.
- SKILL.md notes this prerequisite and the one-time `login.py` run before
  first use.

### 8. Testing approach

No unit tests (live third-party site, no sandbox/API). Manual
verification after implementation:

1. Run `login.py` for real; confirm `storage_state.json` is created with
   correct permissions and login succeeds.
2. Run `query.py` with a fresh model → confirms new-thread creation and
   `threads.json` entry.
3. Run `query.py` again with the same model → confirms thread resume
   (prior context present in ChatPlayground's own UI).
4. Run `query.py` with a different `--model` → confirms a separate thread
   is created and no history bleeds across models.
5. Run `query.py --reset` → confirms old thread entry is dropped and a
   new one created.
6. Manually expire/delete `storage_state.json` → confirms `query.py`
   exits 2 with the correct hint, and does not crash or hang.

## Open Questions / Future Work (not blocking implementation)

- Exact DOM selectors for ChatPlayground's login form, chat input, send
  control, model picker, and response bubble are unknown until inspected
  during implementation (planned via one-time manual/claude-in-chrome
  discovery, not a runtime dependency).
- Response-completion detection heuristic (stop-button vs text-stability)
  may need tuning once the real UI is inspected.
