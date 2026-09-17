# -*- coding: utf-8 -*-
"""``@api_action`` — three-way registrar for HTTP, CLI, and slash commands.

Auto-publishes a single method as an HTTP route, a CLI sub-command
and a slash command.

* :class:`ApiActionSpec` — frozen metadata attached by the decorator.
* :func:`api_action`     — decorator that attaches ``_api_action`` to a
                           method.
* :class:`ManagerBase`   — base class whose ``__init_subclass__`` collects
                           the ``ApiActionSpec`` instances declared on
                           each subclass into ``cls._api_actions``.

``__init_subclass__`` is used (not a metaclass) so subclasses can also
inherit from pydantic / abc bases without metaclass clashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ApiActionSpec:
    """Declarative description of one ``@api_action``-tagged method.

    ``methods`` is a subset of ``{"http", "cli", "slash"}`` — the three
    surfaces auto-published to. The default paths / sub-commands are
    derived from ``name`` at publish time; the optional
    ``http_path`` / ``cli_command`` / ``slash_command`` overrides let a
    manager pick a different public name when it needs to.
    """

    name: str
    methods: frozenset[str]
    http_method: str = "POST"
    http_path: str | None = None
    cli_command: str | None = None
    slash_command: str | None = None
    request_model: type | None = None
    response_model: type | None = None


def api_action(
    *,
    methods: set[str] | frozenset[str] | tuple[str, ...] | list[str],
    http_method: str = "POST",
    http_path: str | None = None,
    cli_command: str | None = None,
    slash_command: str | None = None,
    request_model: type | None = None,
    response_model: type | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach an :class:`ApiActionSpec` to ``fn._api_action``.

    Validates ``methods`` early so a typo (``"htttp"``) fails at import
    time rather than silently disappearing from every generated surface.
    """
    method_set = frozenset(methods)
    invalid = method_set - {"http", "cli", "slash"}
    if invalid:
        raise ValueError(
            f"@api_action received unsupported methods: {sorted(invalid)}; "
            f"allowed = {{'http', 'cli', 'slash'}}",
        )
    if not method_set:
        raise ValueError("@api_action requires at least one method")

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        # pylint: disable=protected-access
        fn._api_action = ApiActionSpec(  # type: ignore[attr-defined]
            name=fn.__name__,
            methods=method_set,
            http_method=http_method,
            http_path=http_path,
            cli_command=cli_command,
            slash_command=slash_command,
            request_model=request_model,
            response_model=response_model,
        )
        return fn

    return deco


class ManagerBase:
    """Base class collecting every ``@api_action``-tagged method on a subclass.

    Each subclass gets its own ``_api_actions`` list (built in
    ``__init_subclass__``) so the HTTP / CLI / slash registrars
    can iterate without scanning attributes themselves.

    Subclasses should override ``endpoint_prefix`` to pick the segment
    of the HTTP path that precedes the action name (e.g. ``"crons"``
    yields ``/crons/<action>``).
    """

    endpoint_prefix: str = ""
    _api_actions: list[ApiActionSpec] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._api_actions = [
            attr._api_action
            for attr in cls.__dict__.values()
            if hasattr(attr, "_api_action")
        ]


class ManagerRegistry:
    """Holds (manager_cls, instance_getter) pairs for auto-generation.

    ``instance_getter`` is a callable ``(app_state) -> manager_instance``
    that the HTTP / CLI / slash collectors call at request time.
    """

    def __init__(self) -> None:
        self._entries: list[tuple[type, Any]] = []

    def register(self, cls: type, instance_getter: Any) -> None:
        """Register a ManagerBase subclass and its instance resolver."""
        self._entries.append((cls, instance_getter))

    def iter_managers(self) -> list[tuple[type, Any]]:
        """Return all registered (cls, instance_getter) pairs."""
        return list(self._entries)


__all__ = ["ApiActionSpec", "ManagerBase", "ManagerRegistry", "api_action"]
