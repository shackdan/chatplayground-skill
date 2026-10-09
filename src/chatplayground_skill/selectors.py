# Discovered 2026-10-09 by live inspection of https://web.chatplayground.ai/
# (Clerk-hosted auth; app UI built on React + Tailwind).
SELECTORS = {
    # Matches both Clerk sub-flows: existing-user sign-in uses
    # name="identifier"; a never-seen-before email briefly shows
    # name="emailAddress" (Clerk's create-account form) before settling
    # into sign-in once the email is recognized.
    "login_email_input": 'input[name="identifier"], input[name="emailAddress"]',
    "login_password_input": 'input[name="password"]',
    # Role-based (accessible name) match, not a CSS text selector: the
    # button wraps its label in a child <span>, which makes Playwright's
    # `:text-is()` match the span instead of the button (it prefers the
    # smallest element with the exact text), so `button:text-is("Continue")`
    # never matches the button itself and page.click() hangs until timeout.
    # The role engine's accessible-name match targets the button correctly
    # and, unlike a plain text selector, does exact (not substring) name
    # matching by default — so it doesn't also match "Continue with
    # Google". The same selector is used for both the email step and the
    # password step; Clerk re-renders the same button at each stage.
    "login_submit_button": 'role=button[name="Continue"]',
    # Clicking a model's sidebar link always opens a *fresh* "New Chat"
    # composer for that model (it never auto-resumes); {model} must be
    # the exact label text shown in the sidebar, e.g. "Claude (Latest
    # Model)", "Gemini (Latest Model)", "Kimi K".
    "model_link": 'role=link[name="{model}"]',
    "chat_input": 'textarea[placeholder="Use Shift+Enter to add new line"]',
    "send_button": 'role=button[name="Send"]',
    "stop_generating_button": 'role=button[name="Stop"]',
    # Targets the rendered-answer content directly, scoped to rows whose
    # role label is "ASSISTANT" (ChatPlayground has no stable per-message
    # id). `.last` gives the most recent assistant message. Reasoning
    # models (e.g. Kimi K) render a separate collapsible "Thought" block
    # *before* this element within the same row — this selector excludes
    # it, returning only the final answer either way.
    "assistant_content": 'div.group.flex.w-full.flex-row:has(p:text-is("ASSISTANT")) [class*="streamdown-content"]',
    # ChatPlayground has no per-conversation URL or id, so a thread is
    # resumed by clicking its entry in the (per-model) Chat History list.
    # Entries are titled from the first message's text, truncated to
    # exactly 50 characters (confirmed empirically); {title} must be that
    # 50-char-truncated string for an exact match.
    "history_item": 'p.line-clamp-1:text-is("{title}")',
}

HISTORY_TITLE_MAX_CHARS = 50
