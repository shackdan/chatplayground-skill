import re
import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import sync_playwright

from .completion import is_response_stable
from .errors import ModelNotFoundError, NotAuthenticatedError, QueryTimeoutError, SelectorNotFoundError
from .selectors import HISTORY_TITLE_MAX_CHARS, SELECTORS

BASE_URL = "https://web.chatplayground.ai/"
STAGE_TRANSITION_TIMEOUT_MS = 10_000
LOGIN_CONFIRM_TIMEOUT_MS = 20_000
# Resuming a long thread re-fetches its full history; observed to take
# longer than STAGE_TRANSITION_TIMEOUT_MS as a conversation grows.
HISTORY_LOAD_TIMEOUT_MS = 30_000
DEFAULT_QUERY_TIMEOUT_S = 90
POLL_INTERVAL_S = 1.0


def run_login(username: str, password: str) -> dict:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BASE_URL)

        page.fill(SELECTORS["login_email_input"], username)
        page.click(SELECTORS["login_submit_button"], timeout=STAGE_TRANSITION_TIMEOUT_MS)

        # Clerk advances to the password sub-step in place, signaled by a
        # URL hash change (observed as #/create or #/factor-one) rather
        # than a full page navigation.
        page.wait_for_url(re.compile(r"#/"), timeout=STAGE_TRANSITION_TIMEOUT_MS)
        page.fill(SELECTORS["login_password_input"], password)
        page.click(SELECTORS["login_submit_button"], timeout=STAGE_TRANSITION_TIMEOUT_MS)

        try:
            page.wait_for_function(
                "() => !location.pathname.startsWith('/login')",
                timeout=LOGIN_CONFIRM_TIMEOUT_MS,
            )
        except Exception:
            input(
                "Could not confirm login automatically. Complete login manually "
                "in the opened browser window, then press Enter here..."
            )
            page.wait_for_function(
                "() => !location.pathname.startsWith('/login')",
                timeout=LOGIN_CONFIRM_TIMEOUT_MS,
            )

        storage_state = context.storage_state()
        browser.close()
        return storage_state


@dataclass
class QueryResult:
    reply: str
    # The exact text of the first message ever sent to this model's
    # thread. ChatPlayground has no per-conversation URL or id, so this
    # is how a thread is identified for resumption: its Chat History
    # entry is titled from this same text, truncated to
    # HISTORY_TITLE_MAX_CHARS. Stays constant across resumes.
    thread_anchor: str


def run_query(
    prompt: str,
    model: str,
    thread_anchor: Optional[str],
    storage_state: dict,
    timeout_s: int = DEFAULT_QUERY_TIMEOUT_S,
) -> QueryResult:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=storage_state)
            page = context.new_page()
            page.goto(BASE_URL)

            if "/login" in page.url:
                raise NotAuthenticatedError()

            model_selector = SELECTORS["model_link"].format(model=model)
            try:
                page.wait_for_selector(model_selector, timeout=STAGE_TRANSITION_TIMEOUT_MS)
            except Exception:
                raise ModelNotFoundError(model)
            page.click(model_selector)

            if thread_anchor:
                title = thread_anchor[:HISTORY_TITLE_MAX_CHARS]
                history_selector = SELECTORS["history_item"].format(title=title)
                try:
                    page.click(history_selector, timeout=STAGE_TRANSITION_TIMEOUT_MS)
                except Exception:
                    raise SelectorNotFoundError("history_item")
                # The resumed conversation's prior messages load in
                # asynchronously after this click; wait for that list to
                # stop growing before using its length as prior_count
                # below, or an undercount would misidentify an existing
                # turn as the new one once the reply arrives.
                _wait_for_stable_count(page.locator(SELECTORS["assistant_content"]), HISTORY_LOAD_TIMEOUT_MS)

            _require_selector(page, "chat_input")
            page.fill(SELECTORS["chat_input"], prompt)
            _require_selector(page, "send_button")
            # On a resumed thread, prior turns already have an
            # assistant_content element present — capture the count
            # beforehand so we can tell a genuinely new response apart
            # from the previous turn's (otherwise the previous answer,
            # already "stable", would be mistaken for the new one before
            # generation even starts).
            prior_count = page.locator(SELECTORS["assistant_content"]).count()
            page.click(SELECTORS["send_button"])

            reply = _wait_for_reply(page, timeout_s, prior_count)
            new_anchor = thread_anchor if thread_anchor else prompt
            return QueryResult(reply=reply, thread_anchor=new_anchor)
        finally:
            browser.close()


def _wait_for_stable_count(locator, timeout_ms: int) -> int:
    deadline = time.monotonic() + timeout_ms / 1000
    # A resumed thread always has at least one prior message (it couldn't
    # have an anchor otherwise), and ChatPlayground shows a loading
    # spinner while fetching it — count()==0 at this point means "still
    # loading," not "confirmed empty," so wait past zero before treating
    # the count as trustworthy at all.
    while time.monotonic() < deadline and locator.count() == 0:
        time.sleep(0.3)

    previous = locator.count()
    while time.monotonic() < deadline:
        time.sleep(0.3)
        current = locator.count()
        if current == previous:
            return current
        previous = current
    return previous


def _require_selector(page, key: str) -> None:
    try:
        page.wait_for_selector(SELECTORS[key], timeout=STAGE_TRANSITION_TIMEOUT_MS)
    except Exception:
        raise SelectorNotFoundError(key)


def _wait_for_reply(page, timeout_s: int, prior_count: int) -> str:
    deadline = time.monotonic() + timeout_s
    locator = page.locator(SELECTORS["assistant_content"])

    while time.monotonic() < deadline and locator.count() <= prior_count:
        time.sleep(POLL_INTERVAL_S)
    if locator.count() <= prior_count:
        raise QueryTimeoutError()

    # Track the new turn by its fixed ordinal position (the element that
    # just appeared at index `prior_count`), not `.last` — ChatPlayground's
    # own flakiness can cause transient renders where `.last` briefly
    # doesn't point at the turn we're actually waiting for, which would
    # otherwise let an unrelated (e.g. stale) element look "stable".
    new_turn = locator.nth(prior_count)
    history = []
    while time.monotonic() < deadline:
        history.append(new_turn.inner_text().strip())
        stop_visible = page.locator(SELECTORS["stop_generating_button"]).count() > 0
        if not stop_visible and is_response_stable(history):
            return history[-1]
        time.sleep(POLL_INTERVAL_S)
    raise QueryTimeoutError()
