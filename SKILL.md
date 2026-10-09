---
name: chatplayground-query
description: Query the ChatPlayground chatbot (web.chatplayground.ai) and get back just the reply text, without the browsing steps filling up context. Use when the user asks to ask/query/check with ChatPlayground or a specific model hosted there (e.g. Claude, Gemini, Kimi K, GPT models) via ChatPlayground.
---

# ChatPlayground Query

Use `scripts/query.py "<prompt>" --model "<model name>"` via Bash to ask
ChatPlayground a question. Treat stdout as the literal answer — print it
or use it directly; do not re-ask the question in your own words.

`--model` must be the exact label shown in ChatPlayground's sidebar,
e.g. `"Claude (Latest Model)"`, `"Gemini (Latest Model)"`, `"Kimi K"`,
`"ChatGPT-6 Luna"`, `"DeepSeek V4 Pro"`. If unsure of the exact name, ask
the user or default to a close guess — a wrong name fails with exit 1
naming the model, not a silent wrong answer.

Each model keeps its own persistent conversation thread automatically —
a second call with the same `--model` continues that model's prior
conversation on ChatPlayground's side. Pass `--reset` to start a fresh
thread for that model instead.

Queries can take a while (ChatPlayground streams a real model response,
sometimes 10-60+ seconds). This is expected; do not treat it as hung.

## If it exits non-zero

- **Exit 2 (not authenticated):** Tell the user to run `! scripts/login.py`
  themselves in their own terminal (not through this chat's `!` prefix —
  it needs a real interactive terminal). Do not ask the user for their
  password yourself, and do not attempt to log in on their behalf — the
  login flow is interactive and must be run directly by the user so their
  credentials never pass through you.
- **Exit 3 (selector not found):** Tell the user ChatPlayground's page
  layout appears to have changed and this skill needs updating.
- **Exit 1 (other failure):** Relay the stderr message (timeout or
  unknown model name).

## Setup (one-time, if not already done)

`./setup.sh` creates a local virtualenv and installs Playwright +
Chromium. Then the user must run `! scripts/login.py` (in their own
terminal) once before the first query.
