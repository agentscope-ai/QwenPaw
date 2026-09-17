# -*- coding: utf-8 -*-
"""Stable storage mode values shared by settings and repository selection."""

from enum import StrEnum


class StorageMode(StrEnum):
    """Available persistence paths during the incremental migration."""

    LEGACY = "legacy"
    POSTGRES = "postgres"
