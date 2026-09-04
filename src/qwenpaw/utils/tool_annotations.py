# -*- coding: utf-8 -*-
"""Resolve stringified (PEP 563) tool annotations to real type objects.

agentscope's ``FunctionTool`` builds a Pydantic model from a tool function's
signature — it iterates ``inspect.signature(func).parameters`` and feeds each
``param.annotation`` into ``pydantic.create_model()`` under the name
``_StructuredOutputDynamicClass``, then calls ``.model_json_schema()``.

When the tool's *module* uses ``from __future__ import annotations`` (PEP 563),
those annotations are plain strings (e.g. ``"Optional[Path]"``). Pydantic then
treats each string as a forward reference and resolves it in the model's module
namespace — which is *agentscope's* ``tool/_utils.py`` and only imports
``Any``/``Dict``/``Callable``. Any tool parameter typed with ``Optional`` /
``Union`` / a custom class therefore raises::

    pydantic.errors.PydanticUserError: `_StructuredOutputDynamicClass` is not
    fully defined; you should define `Optional`, then call
    `_StructuredOutputDynamicClass.model_rebuild()`.

which aborts tool registration at startup (QwenPaw issue #7082).

Resolving the annotations to concrete objects in the function's *own* module
namespace (where ``Optional`` etc. are imported) before agentscope introspects
the function sidesteps the failure: agentscope then sees real types and never
creates an unresolved forward reference.
"""

from __future__ import annotations

import functools
import inspect
import logging
import typing
from typing import Any, Callable

logger = logging.getLogger(__name__)


def resolve_tool_annotations(func: Callable[..., Any]) -> Callable[..., Any]:
    """Best-effort replace stringified annotations on *func* with real types.

    Mutates the underlying function's ``__annotations__`` in place and returns
    *func* so callers can wrap inline. It is a no-op when the annotations are
    already concrete objects, when the function exposes no annotations, or when
    the type hints cannot be resolved (in which case the original — possibly
    stringified — annotations are left untouched, i.e. behaviour is no worse
    than before).
    """
    target = func
    if isinstance(target, functools.partial):
        target = target.func
    target = inspect.unwrap(target)

    raw = getattr(target, "__annotations__", None)
    if not isinstance(raw, dict) or not raw:
        return func
    if not any(isinstance(value, str) for value in raw.values()):
        # Already concrete (no PEP 563 strings, or pre-resolved).
        return func

    try:
        hints = typing.get_type_hints(target)
    except Exception as exc:  # noqa: BLE001 - defensive; never break tool init
        logger.debug(
            "resolve_tool_annotations: could not resolve hints for %r (%s); "
            "leaving annotations untouched",
            getattr(target, "__name__", target),
            exc,
        )
        return func

    # Only overwrite the entries we actually resolved; keep anything else
    # (e.g. names get_type_hints could not evaluate) exactly as it was.
    resolved = {name: hints[name] for name in raw if name in hints}
    if resolved:
        target.__annotations__ = {**raw, **resolved}
    return func
