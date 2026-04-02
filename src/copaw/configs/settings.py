# -*- coding: utf-8 -*-
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .app import AppSettings
from .cors import CorsSettings
from .memory import MemorySettings
from .model import ModelSettings

# Repo root: src/copaw/configs/settings.py -> 4 parents -> repo root
_ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"


class CopawSettings(  # pylint: disable=too-many-ancestors
    AppSettings,
    CorsSettings,
    MemorySettings,
    ModelSettings,
):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(  # pylint: disable=unused-argument
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
        )
