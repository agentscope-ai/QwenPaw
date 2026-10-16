# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Module-level ``return`` shapes the browser worker accepts or rejects.

The worker lowers a module-level ``return`` into ``raise BlockReturn(value)``,
and ``execute_request`` turns that signal into a success result. A return
inside ``finally`` therefore replaces whatever exception is already
propagating, so the caller is told the code succeeded.
"""

from __future__ import annotations

import pytest

from qwenpaw.browser.execution import worker

FAILING_BODY = (
    "def click():\n    raise RuntimeError('button never appeared')\n"
)


def _outcome(code: str) -> object:
    """Run prepared code the way the worker reports its result."""
    exec_code, eval_code = worker._prepare(code)
    namespace = {"__qwenpaw_block_return__": worker.BlockReturn}
    try:
        exec(exec_code, namespace)
        if eval_code is not None:
            return eval(eval_code, namespace)
        return None
    except worker.BlockReturn as returned:
        return returned.value


def test_return_in_finally_is_rejected():
    code = FAILING_BODY + "try:\n    click()\nfinally:\n    return 'ok'\n"
    with pytest.raises(worker.BrowserError, match="finally"):
        worker._prepare(code)


def test_return_in_try_body_with_handler_is_still_rejected():
    code = (
        FAILING_BODY
        + "try:\n    click()\n    return 'ok'\n"
        + "except RuntimeError:\n    pass\n"
    )
    with pytest.raises(worker.BrowserError, match=r"try/except"):
        worker._prepare(code)


def test_cleanup_finally_is_allowed():
    assert _outcome("try:\n    return 'content'\nfinally:\n    pass\n") == (
        "content"
    )


def test_return_in_else_is_allowed():
    code = (
        "try:\n    pass\nexcept RuntimeError:\n    pass\n"
        + "else:\n    return 'ok'\n"
    )
    assert _outcome(code) == "ok"


def test_function_level_return_in_finally_is_allowed():
    code = (
        "def f():\n"
        "    try:\n"
        "        return 'first'\n"
        "    finally:\n"
        "        cleanup = 1\n"
        "result = f()\n"
        "result\n"
    )
    assert _outcome(code) == "first"
