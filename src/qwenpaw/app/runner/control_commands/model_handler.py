# -*- coding: utf-8 -*-
# pylint:disable=too-many-return-statements
"""Handler for /model command.

The /model command manages model configuration for the current agent.
"""

from __future__ import annotations

import logging

from .base import BaseControlCommandHandler, ControlContext

logger = logging.getLogger(__name__)


class ModelCommandHandler(BaseControlCommandHandler):
    """Handler for /model command.

    Features:
    - Show current model: /model
    - Show help: /model -h, /model --help, /model help
    - List all models: /model list
    - Switch model: /model <provider_id>:<model_id>
    - Reset to global default: /model reset
    - Show model info: /model info <provider_id>:<model_id>

    Usage:
        /model
        /model -h
        /model list
        /model openai:gpt-4o
        /model reset
        /model info anthropic:claude-3-5-sonnet-20241022
    """

    command_name = "/model"

    async def handle(self, context: ControlContext) -> str:
        """Handle /model command.

        Args:
            context: Control command context

        Returns:
            Response text (success or error message)
        """
        args_str = context.args.get("_raw_args", "").strip()

        if not args_str:
            return await self._show_current_model(context)
        elif args_str.lower() in ("-h", "--help", "help"):
            return self._show_help()
        elif args_str.lower() == "list":
            return await self._list_models(context)
        elif args_str.lower() == "reset":
            return await self._reset_model(context)
        elif args_str.lower() == "info":
            # Handle /model info without model spec
            return (
                "**Missing Model Specification**\n\n"
                "Please specify a model to show information.\n\n"
                "Usage: `/model info <provider>:<model>`\n\n"
                "Example: `/model info openai:gpt-4o`\n"
                "Use `/model list` to see available models."
            )
        elif args_str.lower().startswith("info "):
            model_spec = args_str[5:].strip()
            return await self._show_model_info(context, model_spec)
        else:
            return await self._switch_model(context, args_str)

    def _show_help(self) -> str:
        """Show help information for /model command.

        Returns:
            Formatted help text
        """
        return (
            "**Model Management Commands**\n\n"
            "Manage and switch AI models for the current agent.\n\n"
            "**Available Commands:**\n\n"
            "`/model` - Show current active model\n\n"
            "`/model list` - List all available models\n\n"
            "`/model <provider>:<model>` - Switch to specified model\n\n"
            "`/model reset` - Reset to global default model\n\n"
            "`/model info <provider>:<model>` - Show model information\n\n"
            "`/model help` or `/model -h` - Show this help message\n\n"
            "**Examples:**\n\n"
            "`/model` - Show current model\n\n"
            "`/model list` - List all models\n\n"
            "`/model openai:gpt-4o` - Switch to GPT-4o\n\n"
            "`/model reset` - Reset to global default\n\n"
            "`/model info openai:gpt-4o` - Show GPT-4o information\n\n\n"
            "**Capability Indicators:**\n\n"
            "🖼️ - Supports image input\n\n"
            "🎥 - Supports video input"
        )

    async def _show_current_model(self, context: ControlContext) -> str:
        """Show current active model for this agent.

        Args:
            context: Control command context

        Returns:
            Formatted response with current model info
        """
        workspace = context.workspace
        agent_config = workspace.config

        # Get agent-level active model
        active_model = agent_config.active_model

        if active_model is None or not active_model.provider_id:
            # Fallback to global active model
            from ....providers.provider_manager import ProviderManager

            manager = ProviderManager.get_instance()
            active_model = manager.get_active_model()

            if active_model is None or not active_model.provider_id:
                return (
                    "**No Active Model**\n\n"
                    "No model is currently configured.\n\n"
                    "Use `/model list` to see available models, "
                    "then use `/model <provider>:<model>` to select one."
                )

            source = "global default"
        else:
            source = "agent-specific"

        return (
            f"**Current Model** ({source})\n\n"
            f"Provider: `{active_model.provider_id}`\n"
            f"Model: `{active_model.model}` ✓"
        )

    async def _list_models(self, context: ControlContext) -> str:
        """List all available providers and models.

        Args:
            context: Control command context

        Returns:
            Formatted list of all providers and models
        """
        from ....providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        workspace = context.workspace

        # Get current active model
        active_model = workspace.config.active_model
        if active_model is None:
            active_model = manager.get_active_model()

        # Get all provider infos
        all_provider_infos = await manager.list_provider_info()

        # Filter to only show configured providers
        # (providers that have API key configured or don't require one)
        configured_providers = []
        for provider_info in all_provider_infos:
            # Skip if provider requires API key but doesn't have one
            if provider_info.require_api_key and not provider_info.api_key:
                continue
            # Skip if provider has no models
            # (check both models and extra_models)
            all_models = list(provider_info.models) + list(
                provider_info.extra_models,
            )
            if not all_models:
                continue
            configured_providers.append(provider_info)

        if not configured_providers:
            return (
                "**No Providers Configured**\n\n"
                "Please configure at least one provider with API key "
                "in the web console."
            )

        # Build response
        lines = ["**Available Models**\n"]

        total_models = 0
        for provider_info in configured_providers:
            provider_id = provider_info.id
            provider_name = provider_info.name

            # Get all models for this provider (both built-in and user-added)
            extra_models = list(provider_info.extra_models)
            all_models = list(provider_info.models) + extra_models
            extra_model_ids = {m.id for m in extra_models}

            lines.append(f"\n**Provider: {provider_name}** (`{provider_id}`)")

            for model in all_models:
                model_id = model.id

                # Check if this is the active model
                is_active = (
                    active_model is not None
                    and active_model.provider_id == provider_id
                    and active_model.model == model_id
                )

                active_marker = " **[ACTIVE]**" if is_active else ""

                # Add user-added marker
                user_added_marker = (
                    " *(user-added)*" if model_id in extra_model_ids else ""
                )

                # Add multimodal indicators
                indicators = []
                if model.supports_image:
                    indicators.append("🖼️")
                if model.supports_video:
                    indicators.append("🎥")
                indicator_str = " ".join(indicators)
                if indicator_str:
                    indicator_str = f" {indicator_str}"

                lines.append(
                    f"  - `{model_id}`{indicator_str}{user_added_marker}"
                    f"{active_marker}",
                )

                total_models += 1

        lines.append(
            f"\n---\n"
            f"Total: {len(configured_providers)} provider(s), "
            f"{total_models} model(s)\n\n"
            f"Use `/model <provider_id>:<model_id>` to switch models.",
        )

        return "\n".join(lines)

    async def _switch_model(
        self,
        context: ControlContext,
        model_spec: str,
    ) -> str:
        """Switch to a different model.

        Args:
            context: Control command context
            model_spec: Model specification in format "provider_id:model_id"

        Returns:
            Success or error message
        """
        # Parse model spec
        if ":" not in model_spec:
            return (
                "**Invalid Format**\n\n"
                "Please use format: `/model <provider>:<model>`\n\n"
                "Example: `/model openai:gpt-4o`\n"
                "Use `/model list` to see available models."
            )

        parts = model_spec.split(":", 1)
        provider_id = parts[0].strip()
        model_id = parts[1].strip()

        if not provider_id or not model_id:
            return (
                "**Invalid Format**\n\n"
                "Provider and model cannot be empty.\n\n"
                "Example: `/model openai:gpt-4o`"
            )

        # Validate provider and model
        is_valid, error_msg = await self._validate_model(
            provider_id,
            model_id,
        )
        if not is_valid:
            return (
                f"**Switch Failed**\n\n"
                f"{error_msg}\n\n"
                f"Use `/model list` to see available models."
            )

        # Update agent config
        from ....config.config import save_agent_config
        from ....config.config import ModelSlotConfig as ModelSlot

        workspace = context.workspace
        agent_config = workspace.config

        agent_config.active_model = ModelSlot(
            provider_id=provider_id,
            model=model_id,
        )

        # Save to agent.json
        try:
            save_agent_config(agent_config.id, agent_config)
        except Exception as e:
            logger.exception(f"Failed to save agent config: {e}")
            return (
                f"**Switch Failed**\n\n"
                f"Failed to save configuration: {str(e)}"
            )

        logger.info(
            f"/model switch: agent={agent_config.id} "
            f"provider={provider_id} model={model_id}",
        )

        return (
            f"**Model Switched**\n\n"
            f"Provider: `{provider_id}`\n"
            f"Model: `{model_id}`\n\n"
            f"The new model will be used for subsequent messages."
        )

    async def _reset_model(self, context: ControlContext) -> str:
        """Reset to global default model.

        Args:
            context: Control command context

        Returns:
            Success message
        """
        from ....config.config import save_agent_config
        from ....providers.provider_manager import ProviderManager

        workspace = context.workspace
        agent_config = workspace.config

        # Get global active model
        manager = ProviderManager.get_instance()
        global_model = manager.get_active_model()

        if global_model is None or not global_model.provider_id:
            return (
                "**Reset Failed**\n\n"
                "No global default model is configured.\n\n"
                "Please configure a model in the web console first."
            )

        # Clear agent-specific model (use None to indicate using global)
        agent_config.active_model = None

        # Save to agent.json
        try:
            save_agent_config(agent_config.id, agent_config)
        except Exception as e:
            logger.exception(f"Failed to save agent config: {e}")
            return (
                f"**Reset Failed**\n\n"
                f"Failed to save configuration: {str(e)}"
            )

        logger.info(
            f"/model reset: agent={agent_config.id} "
            f"using global model={global_model.provider_id}:"
            f"{global_model.model}",
        )

        return (
            f"**Model Reset**\n\n"
            f"Agent now uses global default model:\n"
            f"Provider: `{global_model.provider_id}`\n"
            f"Model: `{global_model.model}`"
        )

    async def _show_model_info(  # pylint: disable=unused-argument
        self,
        context: ControlContext,
        model_spec: str,
    ) -> str:
        """Show detailed information about a specific model.

        Args:
            context: Control command context
            model_spec: Model specification in format "provider_id:model_id"

        Returns:
            Detailed model information
        """
        # Parse model spec
        if ":" not in model_spec:
            return (
                "**Invalid Format**\n\n"
                "Please use format: `/model info <provider>:<model>`\n\n"
                "Example: `/model info openai:gpt-4o`"
            )

        parts = model_spec.split(":", 1)
        provider_id = parts[0].strip()
        model_id = parts[1].strip()

        # Get provider and model
        from ....providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()
        provider = manager.get_provider(provider_id)

        if not provider:
            return (
                f"**Provider Not Found**\n\n"
                f"Provider `{provider_id}` does not exist.\n\n"
                f"Use `/model list` to see available providers."
            )

        # Find model
        model_info = None
        for model in provider.models + provider.extra_models:
            if model.id == model_id:
                model_info = model
                break

        if not model_info:
            return (
                f"**Model Not Found**\n\n"
                f"Model `{model_id}` not found in provider "
                f"`{provider_id}`.\n\n"
                f"Use `/model list` to see available models."
            )

        # Build detailed info
        lines = [
            "**Model Information**\n",
            f"**Provider:** `{provider_id}` ({provider.name})",
            f"**Model ID:** `{model_info.id}`",
            f"**Model Name:** {model_info.name or model_info.id}",
        ]

        # Multimodal capabilities
        capabilities = []
        if model_info.supports_image:
            capabilities.append("🖼️ Image")
        if model_info.supports_video:
            capabilities.append("🎥 Video")
        if model_info.supports_multimodal is False:
            capabilities.append("📝 Text only")

        if capabilities:
            lines.append(f"**Capabilities:** {', '.join(capabilities)}")

        # Probe source
        if model_info.probe_source:
            probe_source_display = {
                "documentation": "Documentation",
                "api": "API Discovery",
                "probe": "Runtime Probe",
                "probed": "Runtime Probe",
            }.get(model_info.probe_source, model_info.probe_source)
            lines.append(f"**Source:** {probe_source_display}")

        # Provider info
        if provider.base_url:
            lines.append(f"**Base URL:** `{provider.base_url}`")

        lines.append(
            "\n---\n"
            f"Use `/model {provider_id}:{model_id}` to switch to this model.",
        )

        return "\n".join(lines)

    async def _validate_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> tuple[bool, str]:
        """Validate if provider and model exist.

        Args:
            provider_id: Provider ID
            model_id: Model ID

        Returns:
            Tuple of (is_valid, error_message)
        """
        from ....providers.provider_manager import ProviderManager

        manager = ProviderManager.get_instance()

        # Validate provider
        provider = manager.get_provider(provider_id)
        if not provider:
            return False, f"Provider `{provider_id}` not found."

        # Validate model
        if not provider.has_model(model_id):
            return (
                False,
                f"Model `{model_id}` not found in provider `{provider_id}`.",
            )

        return True, ""
