# -*- coding: utf-8 -*-
"""MiniMax service capabilities and request policy."""

from copy import deepcopy
from typing import ClassVar

from ..anthropic_provider import AnthropicProvider


class MiniMaxProvider(AnthropicProvider):
    """Keep service-specific policy separate from wire protocol support."""

    cache_modes: ClassVar[frozenset[str]] = frozenset(
        [f"implicit", f"anthropic"],
    )
    cache_documentation: ClassVar[
        str | None
    ] = f"https://platform.minimax.io/docs/api-reference/text-prompt-caching"

    @staticmethod
    def _current_model_kwargs(model_id: str, kwargs: dict) -> dict:
        """Normalize current direct models without altering legacy IDs."""
        if model_id not in {f"MiniMax-M3.1-Flash", f"MiniMax-M3"}:
            return kwargs
        result = deepcopy(kwargs)
        extra = result.get(f"extra_body")
        # SDK extra_body wins over named arguments, so normalize both layers.
        if isinstance(extra, dict):
            for key in (
                f"thinking",
                f"disable_thinking",
                f"thinking_enable",
                f"thinking_budget",
                f"reasoning_effort",
                f"output_config",
                f"service_tier",
            ):
                if key in extra:
                    result[key] = extra.pop(key)
        enabled = result.pop(f"thinking_enable", None)
        disabled = result.pop(f"disable_thinking", False)
        result.pop(f"thinking_budget", None)
        thinking = result.pop(f"thinking", {}) or {}
        effort = result.pop(f"reasoning_effort", None)
        output = dict(result.pop(f"output_config", {}) or {})
        effort = output.pop(f"effort", effort)
        if model_id == f"MiniMax-M3.1-Flash":
            result[f"thinking"] = {f"type": f"adaptive"}
            output[f"effort"] = (
                effort
                if effort in {f"low", f"medium", f"high", f"xhigh", f"max"}
                else f"max"
            )
            result.pop(f"service_tier", None)
        elif thinking or enabled is not None or disabled:
            adaptive = (
                thinking[f"type"] in {f"adaptive", f"enabled"}
                if f"type" in thinking
                else enabled is True
            )
            result[f"thinking"] = {
                f"type": (
                    f"adaptive" if adaptive and not disabled else f"disabled"
                ),
            }
        if output:
            result[f"output_config"] = output
        return result

    def get_effective_generate_kwargs(self, model_id: str) -> dict:
        """Apply policy before legacy AgentScope thinking parameters split."""
        return self._current_model_kwargs(
            model_id,
            super().get_effective_generate_kwargs(model_id),
        )

    def prepare_request(
        self,
        model_id: str,
        protocol: str,
        kwargs: dict,
    ) -> dict:
        """Guard per-call overrides at the final direct Anthropic boundary."""
        return self._current_model_kwargs(
            model_id,
            super().prepare_request(model_id, protocol, kwargs),
        )

    def cache_capabilities(self, model_id: str) -> frozenset[str]:
        """Limit explicit cache markers to documented M2 offerings."""
        supported = {
            f"MiniMax-M2",
            f"MiniMax-M2-Stable",
            f"MiniMax-M2.1",
            f"MiniMax-M2.1-highspeed",
            f"MiniMax-M2.5",
            f"MiniMax-M2.5-highspeed",
            f"MiniMax-M2.7",
            f"MiniMax-M2.7-highspeed",
        }
        return self.cache_modes if model_id in supported else frozenset()
