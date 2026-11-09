# -*- coding: utf-8 -*-
"""``ModelConfigRequest.thinking_budget`` must carry the ``ge=1`` bound.

``ModelInfo.thinking_budget`` declares ``ge=1`` and the sibling
``max_input_length`` field of the same request model carries ``ge=1000``,
but ``thinking_budget`` had no bound, so the HTTP layer accepted values
that the write path then persisted and every read path rejected.
"""

import pytest
from pydantic import ValidationError

from qwenpaw.app.routers.providers import ModelConfigRequest


@pytest.mark.parametrize("bad_budget", [-5, 0])
def test_model_config_request_rejects_thinking_budget_below_one(bad_budget):
    with pytest.raises(ValidationError):
        ModelConfigRequest(thinking_budget=bad_budget)
    assert ModelConfigRequest(thinking_budget=1).thinking_budget == 1
