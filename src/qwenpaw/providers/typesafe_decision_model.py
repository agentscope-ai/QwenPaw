# -*- coding: utf-8 -*-
"""AgentScope decision model with the host provider's request headers."""

from collections.abc import Mapping
from typing import Any

from agentscope.classifier import (
    ClassifierQuestion,
    ClassifierResponse,
    JevClassifierModel,
)


class TypeSafeDecisionModel(JevClassifierModel):
    """Keep AgentScope's request/response handling and bind host defaults."""

    def __init__(self, *, provider_headers: Mapping[str, str], **kwargs):
        super().__init__(**kwargs)
        self._provider_headers = dict(provider_headers)

    async def __call__(
        self,
        state: str | dict,
        questions: Mapping[str, ClassifierQuestion],
        **kwargs: Any,
    ) -> ClassifierResponse:
        headers = {
            **self._provider_headers,
            **(kwargs.pop("extra_headers", None) or {}),
        }
        return await super().__call__(
            state=state,
            questions=questions,
            extra_headers=headers,
            **kwargs,
        )
