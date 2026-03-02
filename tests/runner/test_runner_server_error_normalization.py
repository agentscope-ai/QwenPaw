# -*- coding: utf-8 -*-

from copaw.app.runner.runner import _normalize_user_facing_exception


def _make_exception(class_name: str, message: str) -> Exception:
    cls = type(class_name, (Exception,), {})
    return cls(message)


def test_normalize_upstream_5xx_exception() -> None:
    exc = _make_exception(
        "InternalServerError",
        "Error code: 502 - {'type': 'server_error'}",
    )
    normalized = _normalize_user_facing_exception(exc)

    assert isinstance(normalized, RuntimeError)
    assert "server error" in str(normalized).lower()


def test_keep_non_5xx_exception_unchanged() -> None:
    exc = _make_exception("InternalServerError", "Error code: 429")
    normalized = _normalize_user_facing_exception(exc)

    assert normalized is exc
