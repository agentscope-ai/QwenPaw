# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

import pytest
from fastapi import FastAPI

from api.dependencies import creator_error_handler
from api.router import router
from domain.errors import CreatorError
from services.project_files.facade import clear_creator_file_service_registry


@pytest.fixture()
def api_runtime_root(tmp_path, monkeypatch):
    root = tmp_path / "creator-api"
    monkeypatch.setenv("CREATOR_DATA_ROOT", str(root))
    root.mkdir(parents=True)
    clear_creator_file_service_registry()
    try:
        yield root
    finally:
        clear_creator_file_service_registry()


@pytest.fixture()
def app(api_runtime_root):
    application = FastAPI()
    application.add_exception_handler(CreatorError, creator_error_handler)
    application.include_router(router)
    return application
