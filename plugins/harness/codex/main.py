# -*- coding: utf-8 -*-
"""Optional Codex Harness: registration is pure; the backend opens lazily."""

from qwenpaw.plugins.harnesses import (
    HarnessApprovalPreset,
    HarnessCapabilities,
    HarnessCommand,
    HarnessSpec,
)


async def create_backend(context, settings):
    from .adapter import CodexBackend

    backend = CodexBackend(context, settings)
    await backend.prepare()
    return backend


class Plugin:
    def register(self, context):
        context.register_harness(
            HarnessSpec(
                id="codex",
                label="Codex",
                create=create_backend,
                instance_settings_keys=("binary",),
                capabilities=HarnessCapabilities(
                    authentication=True,
                    model_selection=True,
                    reasoning_effort=True,
                    reasoning_stream=True,
                    tool_stream=True,
                    session_resume=True,
                    attachments=True,
                    qwenpaw_skills_projection=True,
                    qwenpaw_mcp_projection=True,
                    provider_skills_discovery=True,
                    provider_mcp_discovery=True,
                    mcp_tool_allowlist=True,
                    external_history=True,
                    commands=(
                        HarnessCommand(
                            "compact",
                            "Compact the current Codex thread",
                        ),
                        HarnessCommand(
                            "review",
                            "Review uncommitted workspace changes",
                        ),
                        HarnessCommand(
                            "skills",
                            "List skills available to Codex",
                        ),
                        HarnessCommand(
                            "status",
                            "Show Codex account and session status",
                        ),
                    ),
                    approval_presets=(
                        HarnessApprovalPreset(
                            "ask",
                            "Ask before changes",
                            "Allow workspace changes and ask before "
                            "elevated actions.",
                            {
                                "sandbox": "workspace-write",
                                "approval_policy": "on-request",
                            },
                        ),
                        HarnessApprovalPreset(
                            "read-only",
                            "Read only",
                            "Inspect files without changing them.",
                            {
                                "sandbox": "read-only",
                                "approval_policy": "on-request",
                            },
                        ),
                        HarnessApprovalPreset(
                            "workspace",
                            "Workspace access",
                            "Allow workspace changes without confirmation.",
                            {
                                "sandbox": "workspace-write",
                                "approval_policy": "never",
                            },
                        ),
                        HarnessApprovalPreset(
                            "full-access",
                            "Full access",
                            "Allow unrestricted local execution "
                            "without confirmation.",
                            {
                                "sandbox": "danger-full-access",
                                "approval_policy": "never",
                            },
                        ),
                    ),
                ),
                config_fields=(
                    {
                        "name": "binary",
                        "type": "text",
                        "label": "Codex executable",
                        "help": "Optional standalone Codex CLI path.",
                    },
                ),
                description=(
                    "Codex app-server with workspace-isolated sessions."
                ),
            ),
        )


plugin = Plugin()
