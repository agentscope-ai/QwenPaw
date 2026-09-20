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

    kind: Literal["unsupported", "effort", "budget"] = f"unsupported"
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


def resolve_thinking(
    preference: ThinkingPreference,
    control: ThinkingControl,
) -> tuple[ThinkingPreference, str | None]:
    """Resolve against the actual serving model, including fallback models."""
    if preference.level == f"inherit":
        return preference, None
    if control.kind == f"unsupported":
        return ThinkingPreference(), f"unsupported"
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
