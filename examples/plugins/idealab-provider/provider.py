# -*- coding: utf-8 -*-
"""Alibaba IdeaLab Provider Implementation."""

import logging
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo

logger = logging.getLogger(__name__)


class IdeaLabProvider(OpenAIProvider):
    """Alibaba IdeaLab Provider.

    Inherits from OpenAIProvider because IdeaLab API is OpenAI-compatible.
    """

    def __init__(self, **kwargs):
        """Initialize IdeaLab Provider.

        Args:
            **kwargs: Provider information as keyword arguments
        """
        super().__init__(**kwargs)

        # Ensure correct base_url
        if not self.base_url:
            self.base_url = "https://idealab.alibaba-inc.com/api/openai/v1"

        logger.info(
            f"IdeaLab Provider initialized with base_url: {self.base_url}"
        )

    @classmethod
    def get_default_models(cls):
        """Get default models supported by IdeaLab.

        Returns:
            List[ModelInfo]: List of model information
        """
        return [
            ModelInfo(
                id="qwen3-coder-plus",
                name="Qwen3 Coder Plus",
                supports_multimodal=False,
                supports_image=False,
                supports_video=False,
            ),
            ModelInfo(
                id="qwen3.6-plus",
                name="Qwen 3.6 Plus",
                supports_multimodal=True,
                supports_image=True,
                supports_video=False,
            ),
            ModelInfo(
                id="pitaya-03-20",
                name="Pitaya 03-20",
                supports_multimodal=True,
                supports_image=True,
                supports_video=False,
            ),
        ]
