# -*- coding: utf-8 -*-
"""Model-declared reasoning controls and request-local preferences."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ThinkingLevel = Literal[
    "inherit",
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "budget",
]


class ThinkingPreference(BaseModel):
    """A user's intent, independent of provider wire parameters."""

    level: ThinkingLevel = f"inherit"
    budget_tokens: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode=f"after")
    def validate_budget(self):
        """Require a numeric value only in budget mode."""
        if (self.level == f"budget") != (self.budget_tokens is not None):
            raise ValueError(f"Budget mode requires budget_tokens exclusively")
        return self


class ThinkingControl(BaseModel):
    """Verified control surface carried by each model card."""

    kind: Literal["unknown", "unsupported", "effort", "budget"] = f"unknown"
    efforts: list[
        Literal[
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ]
    ] = Field(default_factory=list)
    supports_off: bool = False
    budget_min: int | None = Field(default=None, ge=1)
    budget_max: int | None = Field(default=None, ge=1)
    budget_default: int | None = Field(default=None, ge=1)
    wire: Literal[
        "native",
        "anthropic_budget",
        "gemini_budget",
        "anthropic_adaptive",
        "gemini_level",
        "compat_budget",
        "compat_effort",
    ] = f"native"

    @model_validator(mode=f"after")
    def validate_control(self):
        """Reject unusable model-card control ranges."""
        if self.kind == f"effort" and not self.efforts:
            raise ValueError(f"Effort control requires supported efforts")
        if self.kind == f"budget" and (
            self.budget_min is None
            or self.budget_max is None
            or self.budget_min > self.budget_max
        ):
            raise ValueError(f"Budget control requires an ordered range")
        if self.budget_default is not None and (
            self.kind != f"budget"
            or not self.budget_min <= self.budget_default <= self.budget_max
        ):
            raise ValueError(f"Default budget is outside the model range")
        return self


# Each control type returns its own explicit incompatibility reason.
# pylint: disable-next=too-many-return-statements
def resolve_thinking(
    preference: ThinkingPreference,
    control: ThinkingControl,
) -> tuple[ThinkingPreference, str | None]:
    """Resolve against the actual serving model, including fallback models."""
    if preference.level == f"inherit":
        return preference, None
    if control.kind in {f"unknown", f"unsupported"}:
        return ThinkingPreference(), control.kind
    if preference.level == f"off":
        if control.supports_off:
            return preference, None
        return ThinkingPreference(), f"cannot_disable"
    if control.kind == f"budget":
        low, high = control.budget_min, control.budget_max
        assert low is not None and high is not None
        ratios = {
            f"minimal": 0,
            f"low": 0.15,
            f"medium": 0.4,
            f"high": 0.75,
            f"xhigh": 1,
            f"max": 1,
        }
        requested = preference.budget_tokens
        if requested is None:
            requested = round(low + (high - low) * ratios[preference.level])
        budget = min(high, max(low, requested))
        return (
            ThinkingPreference(level=f"budget", budget_tokens=budget),
            f"adapted" if budget != preference.budget_tokens else None,
        )
    if preference.level in control.efforts:
        return preference, None
    order = [f"minimal", f"low", f"medium", f"high", f"xhigh", f"max"]
    if preference.level == f"budget":
        return ThinkingPreference(), f"incompatible_control"
    else:
        target = preference.level
    allowed = [item for item in control.efforts if item in order]
    effort = (
        min(
            allowed,
            key=lambda item: abs(order.index(item) - order.index(target)),
        )
        if allowed
        else control.efforts[0]
    )
    return ThinkingPreference(level=effort), f"adapted"


def model_default_thinking(
    params: dict,
    control: ThinkingControl,
    *,
    default_enabled: bool | None = None,
    default_effort: str | None = None,
    default_budget: int | None = None,
    native_anthropic: bool = False,
) -> ThinkingPreference:
    """Read configured request values before model metadata defaults.

    Shared by the display and provider construction paths. Provider adapters
    normalize their native parameters before calling this resolver.
    """
    params = {**params, **(params.get(f"extra_body") or {})}
    params = {**params, **(params.get(f"chat_template_kwargs") or {})}
    thinking = params.get(f"thinking") or {}
    reasoning = params.get(f"reasoning") or {}
    config = params.get(f"thinking_config") or {}
    enabled = params.get(
        f"enable_thinking",
        params.get(f"thinking_enable"),
    )
    if params.get(f"disable_thinking") is True:
        enabled = False
    effort = params.get(
        f"reasoning_effort",
        reasoning.get(
            f"effort",
            (params.get(f"output_config") or {}).get(
                f"effort",
                config.get(f"thinking_level"),
            ),
        ),
    )
    budget = params.get(
        f"thinking_budget",
        thinking.get(
            f"budget_tokens",
            config.get(f"thinking_budget"),
        ),
    )
    if budget is None and effort is None and not native_anthropic:
        if enabled is None:
            enabled = default_enabled
        effort = default_effort
        budget = default_budget
    if (
        enabled is False
        or thinking.get(f"type") == f"disabled"
        or reasoning.get(f"enabled") is False
        or effort in {f"none", f"off"}
        or budget == 0
    ):
        return ThinkingPreference(level=f"off")
    if budget is None and effort in {
        f"minimal",
        f"low",
        f"medium",
        f"high",
        f"xhigh",
        f"max",
    }:
        if control.kind == f"effort" and effort in control.efforts:
            return ThinkingPreference(level=effort)
        return ThinkingPreference()
    if control.kind == f"budget":
        if budget is None and not native_anthropic:
            budget = control.budget_default
        if (
            budget is not None
            and control.budget_min is not None
            and control.budget_max is not None
            and control.budget_min <= budget <= control.budget_max
        ):
            return ThinkingPreference(level=f"budget", budget_tokens=budget)
    return ThinkingPreference()
