# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.personal_library.repository import PostgresPersonalLibraryRepository


def test_postgres_repository_rejects_unsafe_schema_name() -> None:
    with pytest.raises(ValueError, match="invalid_database_schema"):
        PostgresPersonalLibraryRepository(schema="qwenpaw; DROP SCHEMA public")
