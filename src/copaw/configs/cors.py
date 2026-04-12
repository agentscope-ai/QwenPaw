# -*- coding: utf-8 -*-
from pydantic import Field
from pydantic_settings import BaseSettings


class CorsSettings(BaseSettings):
    COPAW_CORS_ORIGINS: str = Field(
        description=(
            "Comma-separated allowed CORS origins "
            "(Env: COPAW_CORS_ORIGINS='http://localhost:5173')"
        ),
        default="",
    )
