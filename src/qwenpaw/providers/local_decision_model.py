# -*- coding: utf-8 -*-
"""Native Jev decisions from a Piccolo-capable local llama.cpp runtime.

The runtime applies the checkpoint's bidirectional prompt attention and reads
candidate token logits. AgentScope retains its native request/answer mapping.
"""

from __future__ import annotations

import asyncio
import math

from agentscope.classifier import ClassifierModelBase, ChoiceAnswer
from agentscope.credential import TypeSafeCredential
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy, TypeSafeError

from .typesafe_decision_model import TypeSafeDecisionModel
from ..utils.io_utils import run_async_to_completion, run_sync_io


class LocalDecisionModel(TypeSafeDecisionModel):
    """Use Jev's protocol with an uncompressed loopback transport."""

    def __init__(
        self,
        *,
        credential,
        model,
        timeout,
        max_retries,
        provider_headers,
    ):
        # JevClassifierModel does not expose the SDK's compression option.
        # Initialize its base and client explicitly, retaining __call__ and
        # question/answer conversion. Stock llama.cpp has no zstd decoder.
        ClassifierModelBase.__init__(self, credential, model)
        self._provider_headers = dict(provider_headers)
        self.client = AsyncTypeSafeClient(
            api_key=credential.api_key.get_secret_value(),
            base_url=credential.base_url,
            model=model,
            timeout=timeout,
            retry=RetryPolicy(max_retries=max_retries),
            compression=False,
        )

    async def __call__(self, state, questions, **kwargs):
        response = await super().__call__(state, questions, **kwargs)
        for answer in response.content.values():
            if isinstance(answer, ChoiceAnswer):
                probabilities = answer.probabilities or {}
                if (
                    not probabilities
                    or not all(
                        math.isfinite(p) and 0 <= p <= 1
                        for p in probabilities.values()
                    )
                    or not math.isclose(
                        sum(probabilities.values()),
                        1,
                        abs_tol=1e-4,
                    )
                    or probabilities.get(answer.choice, -1)
                    != max(probabilities.values())
                ):
                    raise ValueError(
                        "Invalid candidate probability distribution",
                    )
        return response


class LocalDecisionProviderMixin:
    """Add native decision calls to QwenPaw's managed llama.cpp provider."""

    def as_decision_model(self, model, *, timeout=30, max_retries=1):
        from ..exceptions import AppBaseException
        from .typesafe_provider import TypeSafeEvaluationError

        try:
            self.validate_model_selection(model, "decision")
        except AppBaseException as exc:
            raise TypeSafeEvaluationError(
                "Local decision model is not configured",
            ) from exc
        base_url = self.base_url.strip().rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        if not base_url:
            raise TypeSafeEvaluationError("Local runtime is not running")
        return LocalDecisionModel(
            credential=TypeSafeCredential(
                api_key=self.api_key.strip() or "local",
                base_url=base_url,
            ),
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            provider_headers=self.custom_headers,
        )

    async def as_decision_model_async(
        self,
        model,
        *,
        timeout=30,
        max_retries=1,
    ):
        classifier = None

        def create():
            nonlocal classifier
            classifier = self.as_decision_model(
                model,
                timeout=timeout,
                max_retries=max_retries,
            )
            return classifier

        try:
            return await run_sync_io(create)
        except asyncio.CancelledError:
            if classifier is not None:
                await run_async_to_completion(classifier.client.aclose())
            raise

    async def evaluate(self, *, state, questions, model, timeout=7.0):
        classifier = await self.as_decision_model_async(
            model,
            timeout=timeout,
            max_retries=0,
        )
        try:
            return await classifier(state, questions)
        except (TypeSafeError, ValueError) as exc:
            from .typesafe_provider import TypeSafeEvaluationError

            raise TypeSafeEvaluationError(
                "Local decision request failed",
                status_code=getattr(exc, "status", None),
            ) from exc
        finally:
            await run_async_to_completion(classifier.client.aclose())
