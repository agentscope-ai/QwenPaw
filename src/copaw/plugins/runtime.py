# -*- coding: utf-8 -*-
"""Runtime helper functions for plugins."""

from typing import List
import logging

logger = logging.getLogger(__name__)


class RuntimeHelpers:
    """Runtime helper functions accessible to plugins."""

    def __init__(self, provider_manager=None):
        """Initialize runtime helpers.

        Args:
            provider_manager: ProviderManager instance
        """
        self.provider_manager = provider_manager

    def get_provider(self, provider_id: str):
        """Get provider instance.

        Args:
            provider_id: Provider identifier

        Returns:
            Provider instance or None
        """
        if self.provider_manager:
            return self.provider_manager.get_provider(provider_id)
        return None

    def list_providers(self) -> List[str]:
        """List all available providers.

        Returns:
            List of provider IDs
        """
        if self.provider_manager:
            return [p.id for p in self.provider_manager.list_providers()]
        return []

    def log_info(self, message: str):
        """Log info message.

        Args:
            message: Log message
        """
        logger.info(message)

    def log_error(self, message: str, exc_info=False):
        """Log error message.

        Args:
            message: Log message
            exc_info: Include exception info
        """
        logger.error(message, exc_info=exc_info)

    def log_debug(self, message: str):
        """Log debug message.

        Args:
            message: Log message
        """
        logger.debug(message)
