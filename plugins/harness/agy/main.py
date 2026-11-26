# -*- coding: utf-8 -*-
"""Optional Antigravity registration; server processes open only on real calls."""

from qwenpaw.plugins.harnesses import (
    HarnessApprovalPreset,
    HarnessCapabilities,
    HarnessCommand,
    HarnessSpec,
)


async def create_backend(context, settings):
    from .adapter import AgyBackend

    backend = AgyBackend(context, settings)
    await backend.prepare()
    return backend


class Plugin:
    def register(self, context):
        context.register_harness(
            HarnessSpec(
                id="agy",
                label="Antigravity",
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
                    qwenpaw_mcp_projection=True,
                    commands=(
                        HarnessCommand(
                            "swarm",
                            "Run the task as a swarm: several agents working "
                            "on it in parallel (uses much quota)",
                            accepts_arguments=True,
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
                            "Allow file edits in the workspace and ask "
                            "before commands.",
                            {"permission_mode": "accept-edits"},
                        ),
                        HarnessApprovalPreset(
                            "plan",
                            "Plan only",
                            "Plan carefully before executing a task.",
                            {"permission_mode": "plan"},
                        ),
                        HarnessApprovalPreset(
                            "auto",
                            "Automatic",
                            "Allow edits and safe commands; ask before "
                            "irreversible actions.",
                            {"permission_mode": "auto"},
                        ),
                        HarnessApprovalPreset(
                            "full-access",
                            "Full access",
                            "Approve every permission request without "
                            "confirmation.",
                            {"permission_mode": "bypassPermissions"},
                        ),
                    ),
                ),
                config_fields=(
                    {
                        "name": "binary",
                        "type": "text",
                        "label": "Antigravity CLI executable",
                        "help": "Optional standalone Antigravity CLI path.",
                    },
                ),
                description=(
                    "Antigravity CLI via Agent Client Protocol (agy acp)."
                ),
            ),
        )


plugin = Plugin()
