"""Validate and apply non-persistent session loop overrides."""

from typing import Any

from .config import AgentProfileConfig, LoopConfig


def _check_fields(value: Any, parsed: Any, path: str = "loop") -> None:
    """Reject fields that native configuration parsing would ignore."""
    if isinstance(value, dict):
        unknown = value.keys() - parsed.keys()
        if unknown:
            raise ValueError(f"Unknown {path} fields: {sorted(unknown)}")
        for name, item in value.items():
            _check_fields(item, parsed[name], f"{path}.{name}")
    elif isinstance(value, list):
        for index, (item, result) in enumerate(zip(value, parsed)):
            _check_fields(item, result, f"{path}[{index}]")


def validate_session_loop(value: Any) -> dict[str, Any]:
    """Accept partial ordinary-mode settings using native validation."""
    if not isinstance(value, dict):
        raise ValueError("Session loop must be an object")
    unknown = value.keys() - {"iteration", "doom_loop", "rubric"}
    if unknown:
        raise ValueError(f"Unsupported session loop fields: {sorted(unknown)}")
    parsed = LoopConfig.model_validate(value, strict=True).model_dump(
        mode="json", exclude_unset=True,
    )
    _check_fields(value, parsed)
    return parsed


def apply_session_loop(
    config: AgentProfileConfig,
    value: Any,
) -> AgentProfileConfig:
    """Overlay supplied fields on a private copy of the agent profile."""
    overrides = validate_session_loop(value)
    if not overrides:
        return config
    result = config.model_copy(deep=True)
    loop = result.running.loop.model_dump()
    for name, fields in overrides.items():
        loop[name].update(fields)
    result.running.loop = LoopConfig.model_validate(loop)
    return result
