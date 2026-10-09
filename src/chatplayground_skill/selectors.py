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
    # Exact text match avoids ambiguity with the "Continue with Google"
    # button, which also contains the substring "Continue". The same
    # selector is used for both the email step and the password step —
    # Clerk re-renders the same button with the same exact label at each
    # stage of the form.
    "login_submit_button": 'button:text-is("Continue")',
}
