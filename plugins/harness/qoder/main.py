# -*- coding: utf-8 -*-
"""Optional Qoder registration; clients and state open only on real calls."""

from qwenpaw.plugins.harnesses import (
    HarnessApprovalPreset,
    HarnessCapabilities,
    HarnessCommand,
    HarnessSpec,
)


async def create_backend(context, settings):
    from .adapter import QoderBackend

    backend = QoderBackend(context, settings)
    await backend.prepare()
    return backend


class Plugin:
    def register(self, context):
        context.register_harness(
            HarnessSpec(
                id="qoder",
                label="Qoder",
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
                    mcp_tool_allowlist=True,
                    commands=(
                        HarnessCommand(
                            "compact",
                            "Compact the current Qoder session",
                        ),
                    ),
                    approval_presets=(
                        HarnessApprovalPreset(
                            "ask",
                            "Ask before actions",
                            "Ask before file changes and command execution.",
                            {"permission_mode": "default"},
                        ),
                        HarnessApprovalPreset(
                            "accept-edits",
                            "Accept edits",
                            "Allow file edits while keeping other safeguards.",
                            {"permission_mode": "acceptEdits"},
                        ),
                        HarnessApprovalPreset(
                            "plan",
                            "Plan only",
                            "Analyze and plan without changing files.",
                            {"permission_mode": "plan"},
                        ),
                        HarnessApprovalPreset(
                            "auto",
                            "Automatic",
                            "Let Qoder decide which safe actions can run.",
                            {"permission_mode": "auto"},
                        ),
                        HarnessApprovalPreset(
                            "full-access",
                            "Full access",
                            "Skip permission checks in a trusted workspace.",
                            {"permission_mode": "bypassPermissions"},
                        ),
                    ),
                ),
                config_fields=(
                    {
                        "name": "binary",
                        "type": "text",
                        "label": "Qoder executable",
                        "help": "Optional standalone Qoder CLI path.",
                    },
                ),
                description="Qoder SDK with workspace-isolated sessions.",
            ),
        )


plugin = Plugin()
