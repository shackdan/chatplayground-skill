import re

from playwright.sync_api import sync_playwright

from .selectors import SELECTORS

BASE_URL = "https://web.chatplayground.ai/"
STAGE_TRANSITION_TIMEOUT_MS = 10_000
LOGIN_CONFIRM_TIMEOUT_MS = 20_000


def run_login(username: str, password: str) -> dict:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(BASE_URL)

        page.fill(SELECTORS["login_email_input"], username)
        page.click(SELECTORS["login_submit_button"])

        # Clerk advances to the password sub-step in place, signaled by a
        # URL hash change (observed as #/create or #/factor-one) rather
        # than a full page navigation.
        page.wait_for_url(re.compile(r"#/"), timeout=STAGE_TRANSITION_TIMEOUT_MS)
        page.fill(SELECTORS["login_password_input"], password)
        page.click(SELECTORS["login_submit_button"])

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
