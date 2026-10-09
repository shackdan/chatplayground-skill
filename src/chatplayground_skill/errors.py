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
