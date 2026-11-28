# -*- coding: utf-8 -*-
"""Exercise local model routes through the shared isolated App fixture."""
# pylint: disable=unused-import
from collections.abc import Iterator

import pytest

from tests.integration.conftest import AppServer, app_server


@pytest.fixture(scope="module")
def local_model_plugin(app_server: AppServer) -> Iterator[None]:  # noqa: F811
    """Install the local provider using preinstalled dependencies."""
    from qwenpaw.plugins.dependency_gate import DependencyGate
    from tests.integration.helpers import (
        OFFICIAL_PLUGINS_DIR,
        PLUGIN_HTTP_TIMEOUT,
        wait_until_plugin_loader_ready,
    )

    source = OFFICIAL_PLUGINS_DIR / "provider/local-llamacpp"
    decision = DependencyGate().evaluate(
        source / "requirements.txt",
        allow_install=False,
        plugin_id="local-llamacpp",
    )
    if not decision.already_satisfied:
        pytest.fail(
            "Prepare local model dependencies before starting pytest workers: "
            "python -m pip install -r "
            "plugins/provider/local-llamacpp/requirements.txt "
            f"({decision.reason})",
            pytrace=False,
        )

    wait_until_plugin_loader_ready(app_server)
    response = app_server.api_request(
        "POST",
        "/api/plugins/install",
        json={"source": str(source)},
        timeout=PLUGIN_HTTP_TIMEOUT,
    )
    assert response.status_code == 200, response.text
    try:
        yield
    finally:
        response = app_server.api_request(
            "DELETE",
            "/api/plugins/local-llamacpp",
            timeout=PLUGIN_HTTP_TIMEOUT,
        )
        assert response.status_code == 200, response.text
