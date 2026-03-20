# -*- coding: utf-8 -*-
"""Configuration for File System Backend.

This module provides configuration management for switching between
local and OpenSandbox cloud file system backends.
"""

import os
from typing import Optional, Dict, Any


class FSBackendConfig:
    """File System Backend configuration.

    Attributes:
        mode: Backend mode ('local' or 'opensandbox').
        opensandbox_api_key: OpenSandbox API key (required for cloud mode).
        opensandbox_domain: OpenSandbox server domain.
        opensandbox_image: Container image for sandbox creation.
        opensandbox_timeout: Sandbox timeout in seconds.
        working_dir: Working directory for local mode / cloud workspace path.
    """

    def __init__(
        self,
        mode: str = 'local',
        opensandbox_api_key: Optional[str] = None,
        opensandbox_domain: Optional[str] = None,
        opensandbox_image: str = 'python:3.11',
        opensandbox_timeout: int = 3600,
        working_dir: Optional[str] = None,
    ):
        self.mode = mode
        self.opensandbox_api_key = (
            opensandbox_api_key or os.environ.get('OPEN_SANDBOX_API_KEY')
        )
        self.opensandbox_domain = (
            opensandbox_domain or os.environ.get('OPEN_SANDBOX_DOMAIN')
        )
        self.opensandbox_image = opensandbox_image
        self.opensandbox_timeout = opensandbox_timeout
        self.working_dir = working_dir

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'FSBackendConfig':
        """Create config from dictionary."""
        return cls(
            mode=config_dict.get('mode', 'local'),
            opensandbox_api_key=config_dict.get('opensandbox_api_key'),
            opensandbox_domain=config_dict.get('opensandbox_domain'),
            opensandbox_image=config_dict.get('opensandbox_image', 'python:3.11'),
            opensandbox_timeout=config_dict.get('opensandbox_timeout', 3600),
            working_dir=config_dict.get('working_dir'),
        )

    @classmethod
    def from_env(cls) -> 'FSBackendConfig':
        """Create config from environment variables.

        Environment variables:
            COPAW_FS_MODE: Backend mode ('local' or 'opensandbox')
            OPEN_SANDBOX_API_KEY: OpenSandbox API key
            OPEN_SANDBOX_DOMAIN: OpenSandbox server domain
            COPAW_OPENSANDBOX_IMAGE: Container image (default: python:3.11)
            COPAW_OPENSANDBOX_TIMEOUT: Sandbox timeout seconds (default: 3600)
            COPAW_WORKING_DIR: Working directory
        """
        return cls(
            mode=os.environ.get('COPAW_FS_MODE', 'local'),
            opensandbox_api_key=os.environ.get('OPEN_SANDBOX_API_KEY'),
            opensandbox_domain=os.environ.get('OPEN_SANDBOX_DOMAIN'),
            opensandbox_image=os.environ.get(
                'COPAW_OPENSANDBOX_IMAGE', 'python:3.11'
            ),
            opensandbox_timeout=int(os.environ.get(
                'COPAW_OPENSANDBOX_TIMEOUT', '3600'
            )),
            working_dir=os.environ.get('COPAW_WORKING_DIR'),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'mode': self.mode,
            'opensandbox_api_key': (
                self.opensandbox_api_key[:10] + '...'
                if self.opensandbox_api_key
                else None
            ),
            'opensandbox_domain': self.opensandbox_domain,
            'opensandbox_image': self.opensandbox_image,
            'opensandbox_timeout': self.opensandbox_timeout,
            'working_dir': self.working_dir,
        }

    def validate(self) -> tuple[bool, str]:
        """Validate configuration."""
        if self.mode not in ('local', 'opensandbox'):
            return False, (
                f"Invalid mode: {self.mode}. "
                f"Must be 'local' or 'opensandbox'"
            )
        if self.mode == 'opensandbox' and not self.opensandbox_api_key:
            return False, "OPEN_SANDBOX_API_KEY is required for cloud mode"
        return True, ""


# Default configuration instance
_default_config: Optional[FSBackendConfig] = None


def get_config() -> FSBackendConfig:
    """Get the current file system backend configuration."""
    global _default_config
    if _default_config is None:
        _default_config = FSBackendConfig.from_env()
    return _default_config


def set_config(config: FSBackendConfig):
    """Set the file system backend configuration."""
    global _default_config
    _default_config = config


def load_config_from_dict(config_dict: Dict[str, Any]) -> FSBackendConfig:
    """Load configuration from dictionary."""
    config = FSBackendConfig.from_dict(config_dict)
    set_config(config)
    return config


def is_cloud_mode() -> bool:
    """Check if cloud mode is enabled."""
    return get_config().mode == 'opensandbox'
