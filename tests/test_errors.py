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
