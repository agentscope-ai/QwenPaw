# -*- coding: utf-8 -*-
"""Fallback helpers for VLM routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

from ..providers import ResolvedModelConfig

T = TypeVar("T")


@dataclass
class VlmFallbackAttempt:
    provider_id: str
    model: str
    error: str


@dataclass
class VlmFallbackResult(Generic[T]):
    result: T
    used: ResolvedModelConfig
    attempts: list[VlmFallbackAttempt]


async def run_with_vlm_fallback(
    primary: ResolvedModelConfig,
    fallbacks: list[ResolvedModelConfig],
    run: Callable[[ResolvedModelConfig], Awaitable[T]],
) -> VlmFallbackResult[T]:
    """Try primary VLM model first, then fallback models."""
    candidates = [primary, *fallbacks]
    attempts: list[VlmFallbackAttempt] = []
    last_error: Exception | None = None

    for cfg in candidates:
        try:
            result = await run(cfg)
            return VlmFallbackResult(result=result, used=cfg, attempts=attempts)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            attempts.append(
                VlmFallbackAttempt(
                    provider_id=cfg.provider_id,
                    model=cfg.model,
                    error=str(exc),
                ),
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("No VLM candidates configured")

