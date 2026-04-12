# -*- coding: utf-8 -*-
"""CoPaw configuration module with Pydantic Settings singleton."""

from .settings import CopawSettings

# Global singleton instance
copaw_config = CopawSettings()
