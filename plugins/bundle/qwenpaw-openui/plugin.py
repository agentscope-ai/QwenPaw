# -*- coding: utf-8 -*-
"""Request-scoped OpenUI instructions for capable Console clients."""

from pathlib import Path

from agentscope.middleware import MiddlewareBase


class OpenUIMiddleware(MiddlewareBase):
    """Append the catalog without modifying messages or agent config."""

    def __init__(self, prompt: str):
        self.prompt = prompt

    async def on_system_prompt(self, _agent, current_prompt: str) -> str:
        if self.prompt in current_prompt:
            return current_prompt
        return f"{current_prompt.rstrip()}\n\n{self.prompt}".strip()


class OpenUIPlugin:
    """The frontend capability disappears when the plugin is disabled."""

    def register(self, api):
        prompt = (
            (Path(__file__).parent / "dist" / "system-prompt.txt")
            .read_text(encoding="utf-8")
            .strip()
        )
        if not prompt:
            raise ValueError(
                "OpenUI system prompt is empty; rebuild the plugin",
            )

        def factory(ctx, _agent_config):
            root_session = getattr(ctx, "root_session_id", None)
            if root_session and root_session != getattr(
                ctx,
                "session_id",
                None,
            ):
                return None
            request = getattr(ctx, "request", None)
            if getattr(request, "channel", None) != "console":
                return None
            context = getattr(request, "request_context", None)
            if not isinstance(context, dict):
                return None
            capabilities = context.get("ui_capabilities")
            if (
                not isinstance(capabilities, dict)
                or capabilities.get("openui") != "v1"
            ):
                return None
            if (
                context.get("source")
                in {
                    "cron",
                    "heartbeat",
                    "portability_adaptation",
                    "subagent",
                }
                or context.get("subagent_allowed_tools") is not None
            ):
                return None
            return OpenUIMiddleware(prompt)

        api.register_middleware(factory)


plugin = OpenUIPlugin()
