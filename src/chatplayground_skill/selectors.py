# Discovered 2026-10-09 by live inspection of https://web.chatplayground.ai/
# (Clerk-hosted auth). Query/model-picker/chat selectors are not yet
# discovered — they're added when the query path is implemented.
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
}
