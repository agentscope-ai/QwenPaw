# -*- coding: utf-8 -*-
"""Member model selection must not grant organization configuration access."""

import pytest
from fastapi import HTTPException

from qwenpaw.hub.model_service.runtime_policy import require_model_route


@pytest.mark.parametrize(
    (f"method", f"path"),
    [
        (f"GET", f"models/hub-managed/pool"),
        (f"PUT", f"models/hub-managed/pool/selection"),
        (f"PUT", f"models/hub-managed/models/model-id/pool"),
        (f"PUT", f"models/hub-managed/models/model-id/visibility"),
        (f"PUT", f"models/kilo/pool/selection"),
        (f"PUT", f"models/kilo"),
    ],
)
def test_member_selection_and_personal_provider_routes_allowed(method, path):
    require_model_route(path, method)


@pytest.mark.parametrize(
    (f"method", f"path", f"status"),
    [
        (f"POST", f"models/hub-managed/pool/selection", 403),
        (f"DELETE", f"models/hub-managed/pool/selection", 403),
        (f"PUT", f"models/hub-managed/pool/selection/extra", 403),
        (f"PUT", f"models/hub-managed", 403),
        (f"PUT", f"models/hub-managed/models/model-id", 403),
        (f"DELETE", f"models/custom-providers/hub-managed", 403),
        (f"POST", f"hub/model-runtime/v1/chat/completions", 404),
    ],
)
def test_org_configuration_and_gateway_remain_restricted(method, path, status):
    with pytest.raises(HTTPException) as failure:
        require_model_route(path, method)
    assert failure.value.status_code == status
