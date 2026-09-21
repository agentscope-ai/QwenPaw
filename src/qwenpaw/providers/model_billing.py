# -*- coding: utf-8 -*-
"""Shared, conservative classification of model-level pricing evidence."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

Billing = Literal["free", "paid", "unknown"]


def normalize_pricing(value: Any) -> dict[str, str]:
    """Keep explicit numeric prices; never manufacture missing zeroes."""
    if not isinstance(value, dict):
        return {}
    return {
        f"{key}": f"{cost}" for key, cost in value.items() if cost is not None
    }


def classify_pricing(
    pricing: dict[str, str],
    free_flag: Any = None,
) -> Billing:
    """Positive charges win; free requires complete zero rates or a flag."""
    amounts = []
    invalid = False
    for key, value in pricing.items():
        if key == f"discount":
            continue
        try:
            amount = Decimal(value)
            if not amount.is_finite() or amount < 0:
                invalid = True
            else:
                amounts.append(amount)
        except (InvalidOperation, ValueError):
            invalid = True
    if any(amount > 0 for amount in amounts) or free_flag is False:
        return f"paid"
    if free_flag is True:
        return f"free"
    if not invalid and {f"prompt", f"completion"}.issubset(pricing):
        return f"free"
    return f"unknown"


def effective_billing(model: Any) -> Billing:
    """Expire transient API promotions without expiring packaged evidence."""
    if (
        model.billing == f"free"
        and model.billing_source == f"api"
        and model.billing_checked_at
    ):
        try:
            checked = datetime.fromisoformat(model.billing_checked_at)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            if age < 0 or age > 86400:
                return f"unknown"
        except ValueError:
            return f"unknown"
    return model.billing
