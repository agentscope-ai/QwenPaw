# -*- coding: utf-8 -*-
"""Auto-register HTTP routes and slash commands from ``@api_action``.

``register_http_routes`` scans every :class:`ManagerBase` subclass in a
:class:`ManagerRegistry` and creates FastAPI endpoints for actions whose
``methods`` include ``"http"``.

``collect_slash_specs_from_api_actions`` does the same for ``"slash"``
methods, returning :class:`CommandSpec` instances for the per-workspace
:class:`SlashCommandRegistry`.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ..api_action import ApiActionSpec, ManagerRegistry
    from ..runtime.slash_command_registry import CommandSpec

logger = logging.getLogger(__name__)


def _extract_path_params(http_path: str | None) -> list[str]:
    """Extract ``{name}`` parameter names from an HTTP path template."""
    if not http_path:
        return []
    return re.findall(r"\{(\w+)\}", http_path)


# ======================================================================
# HTTP route auto-registration
# ======================================================================


def _make_endpoint(
    spec: "ApiActionSpec",
    instance_getter: Any,
    app: "FastAPI",
) -> Any:
    """Build a FastAPI endpoint closure with a clean signature.

    Closure vars must be hidden from ``inspect.signature``
    so FastAPI doesn't treat them as query params.
    Handles path parameters (``{job_id}`` style) and optional request body.
    """
    request_model = spec.request_model
    path_params = _extract_path_params(spec.http_path)

    if request_model is None and not path_params:

        async def endpoint() -> Any:
            mgr = instance_getter(app)
            return await getattr(mgr, spec.name)()

        return endpoint

    if request_model is None:

        async def endpoint_path(**kwargs: Any) -> Any:
            mgr = instance_getter(app)
            return await getattr(mgr, spec.name)(**kwargs)

        endpoint_path.__signature__ = inspect.Signature(
            parameters=[
                inspect.Parameter(
                    name,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=str,
                )
                for name in path_params
            ],
        )
        return endpoint_path

    if not path_params:

        async def endpoint_body(body: Any) -> Any:
            mgr = instance_getter(app)
            return await getattr(mgr, spec.name)(body)

        endpoint_body.__signature__ = inspect.Signature(
            parameters=[
                inspect.Parameter(
                    "body",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=request_model,
                ),
            ],
        )
        return endpoint_body

    async def endpoint_full(body: Any, **kwargs: Any) -> Any:
        mgr = instance_getter(app)
        return await getattr(mgr, spec.name)(body, **kwargs)

    params = [
        inspect.Parameter(
            "body",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=request_model,
        ),
    ]
    params.extend(
        inspect.Parameter(
            name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=str,
        )
        for name in path_params
    )
    endpoint_full.__signature__ = inspect.Signature(parameters=params)
    return endpoint_full


def register_http_routes(
    app: "FastAPI",
    registry: "ManagerRegistry",
) -> int:
    """Scan *registry* and mount auto-generated HTTP routes on *app*.

    Returns the number of routes registered.
    """
    count = 0
    for mgr_cls, instance_getter in registry.iter_managers():
        prefix = getattr(mgr_cls, "endpoint_prefix", "") or ""
        for spec in getattr(mgr_cls, "_api_actions", []):
            if "http" not in spec.methods:
                continue
            path = spec.http_path or f"/{prefix}/{spec.name}"
            try:
                app.add_api_route(
                    path,
                    _make_endpoint(spec, instance_getter, app),
                    methods=[spec.http_method],
                    response_model=spec.response_model,
                    name=f"auto_{mgr_cls.__name__}_{spec.name}",
                )
                count += 1
                logger.info(
                    "auto-registered HTTP %s %s",
                    spec.http_method,
                    path,
                )
            except Exception:
                logger.exception(
                    "Failed to register HTTP route %s %s",
                    spec.http_method,
                    path,
                )
    return count


# ======================================================================
# Slash command auto-collection
# ======================================================================


def collect_slash_specs_from_api_actions(
    registry: "ManagerRegistry",
) -> "list[CommandSpec]":
    """Convert ``@api_action(methods={..., "slash"})`` specs to CommandSpecs.

    Each CommandSpec adapter calls ``instance_getter(app_state)`` at
    dispatch time then invokes the manager method with parsed args.
    """
    from ..runtime.slash_command_registry import CommandSpec

    specs: list[CommandSpec] = []
    for mgr_cls, instance_getter in registry.iter_managers():
        for action_spec in getattr(mgr_cls, "_api_actions", []):
            if "slash" not in action_spec.methods:
                continue

            cmd_name = action_spec.slash_command or action_spec.name

            async def _adapter(
                ctx: Any,
                args: str,
                _spec: Any = action_spec,
                _get: Any = instance_getter,
            ) -> Any:
                import json as _json

                from agentscope.message import Msg
                from agentscope.message._block import TextBlock

                app_state = getattr(ctx, "app_services", None)
                mgr = _get(app_state)
                method = getattr(mgr, _spec.name)
                stripped = args.strip()
                if stripped and _spec.request_model is not None:
                    try:
                        data = _json.loads(stripped)
                    except _json.JSONDecodeError:
                        return Msg(
                            name="assistant",
                            role="assistant",
                            content=[
                                TextBlock(
                                    type="text",
                                    text=(
                                        f"Error: expected JSON for "
                                        f"/{_spec.slash_command or _spec.name}"
                                    ),
                                ),
                            ],
                        )
                    model_instance = _spec.request_model(**data)
                    result = await method(model_instance)
                elif stripped:
                    result = await method(stripped)
                else:
                    result = await method()
                if isinstance(result, Msg):
                    return result
                return Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(type="text", text=str(result))],
                )

            specs.append(
                CommandSpec(
                    name=cmd_name,
                    handler=_adapter,
                    category="auto",
                    help_text=(
                        f"Auto-generated from "
                        f"{mgr_cls.__name__}.{action_spec.name}"
                    ),
                ),
            )
    return specs


__all__ = [
    "collect_slash_specs_from_api_actions",
    "register_http_routes",
]
