# -*- coding: utf-8 -*-
# White-box assertions and pytest fixture parameters are intentional.
# pylint: disable=protected-access
"""One pricing contract for APIs, cards, filters and provider badges."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from qwenpaw.providers.model_billing import classify_pricing
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.provider_model_state import (
    serialize_model_state,
    restore_model_state,
)
from qwenpaw.providers.model_pool import ModelPoolQuery, model_pool_page
from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider_catalog import (
    PROVIDER_DASHSCOPE,
    PROVIDER_ZHIPU_CN_CODINGPLAN,
    PROVIDER_ZHIPU_INTL_CODINGPLAN,
    PROVIDER_SILICONFLOW_CN,
    PROVIDER_SILICONFLOW_INTL,
)


@pytest.mark.parametrize(
    f"pricing,flag,expected",
    [
        ({}, None, f"unknown"),
        ({f"prompt": f"0"}, None, f"unknown"),
        ({f"prompt": f"0", f"completion": f"0"}, None, f"free"),
        ({f"prompt": f"0", f"completion": f"1"}, True, f"paid"),
        (
            {f"prompt": f"0", f"completion": f"0", f"request": f"1"},
            None,
            f"paid",
        ),
        ({f"prompt": f"NaN", f"completion": f"0"}, None, f"unknown"),
        ({f"prompt": f"-1", f"completion": f"-1"}, None, f"unknown"),
        ({f"prompt": f"Infinity", f"completion": f"0"}, None, f"unknown"),
        ({}, True, f"free"),
        ({}, False, f"paid"),
    ],
)
def test_price_evidence(pricing, flag, expected):
    assert classify_pricing(pricing, flag) == expected


def test_generic_discovery_preserves_api_prices():
    payload = SimpleNamespace(
        data=[
            SimpleNamespace(
                id=f"private-model",
                pricing={f"prompt": f"0", f"completion": f"0"},
            ),
        ],
    )
    model = OpenAIProvider._normalize_models_payload(payload)[0]
    assert model.billing == f"free"
    assert model.pricing == {f"prompt": f"0", f"completion": f"0"}
    assert model.billing_source == f"api"


@pytest.mark.parametrize(
    f"model_id",
    [
        f"tencent/Hunyuan-MT-7B",
        f"THUDM/GLM-4-9B-0414",
        f"Qwen/Qwen3.5-4B",
    ],
)
def test_siliconflow_free_cards_are_region_specific(model_id):
    cn = PROVIDER_SILICONFLOW_CN.model_copy(deep=True)
    intl = PROVIDER_SILICONFLOW_INTL.model_copy(deep=True)
    assert cn.resolve_model_info(model_id).billing == f"free"
    assert intl.resolve_model_info(model_id).billing != f"free"
    pool = model_pool_page(cn, ModelPoolQuery(billing=f"free"))
    assert model_id in {model.id for model in pool.models}
    assert pool.selected_count == 0


def test_api_paid_price_overrides_free_catalog():
    provider = PROVIDER_SILICONFLOW_CN.model_copy(deep=True)
    model_id = f"Qwen/Qwen3.5-4B"
    provider.discovered_models = [
        ModelInfo(
            id=model_id,
            name=model_id,
            billing=f"paid",
            billing_source=f"api",
            pricing={f"prompt": f"0.1", f"completion": f"0.2"},
        ),
    ]
    card = provider.resolve_model_info(model_id)
    assert card.billing == f"paid"
    assert not card.is_free


def test_same_model_on_custom_endpoint_does_not_inherit_free_price():
    provider = OpenAIProvider(
        id=f"custom",
        name=f"Custom",
        base_url=f"https://custom.example/v1",
    )
    assert provider.resolve_model_info(f"Qwen/Qwen3.5-4B").billing == (
        f"unknown"
    )


async def test_provider_badges_ignore_static_free_flag():
    provider = OpenAIProvider(
        id=f"custom",
        name=f"Custom",
        meta={f"is_free_tier": True},
    )
    assert not (await provider.get_info()).is_free_tier
    provider.discovered_models = [
        ModelInfo(
            id=f"free",
            name=f"Free",
            billing=f"free",
            billing_source=f"api",
        ),
    ]
    assert (await provider.get_info()).is_free_tier


async def test_catalog_badge_does_not_require_selected_models():
    provider = PROVIDER_SILICONFLOW_CN.model_copy(deep=True)
    info = await provider.get_info(include_candidates=False)
    assert info.is_free_tier
    assert not info.models
    assert not info.discovered_models


def test_expired_api_promotion_is_unknown_in_pool_and_card():
    provider = OpenAIProvider(
        id=f"custom",
        name=f"Custom",
        discovered_models=[
            ModelInfo(
                id=f"promo",
                name=f"Promo",
                billing=f"free",
                is_free=True,
                billing_source=f"api",
                billing_checked_at=(
                    datetime.now(timezone.utc) - timedelta(days=2)
                ).isoformat(),
            ),
        ],
    )
    assert provider.resolve_model_info(f"promo").billing == f"unknown"
    assert (
        model_pool_page(provider, ModelPoolQuery(billing=f"free")).total == 0
    )


def test_pricing_evidence_survives_saved_state():
    model = ModelInfo(
        id=f"paid",
        name=f"Paid",
        billing=f"paid",
        billing_source=f"api",
        pricing={f"prompt": f"0.1"},
    )
    restored = ModelInfo(id=model.id, name=model.name)
    restore_model_state(restored, serialize_model_state(model))
    assert restored.billing == model.billing
    assert restored.billing_source == model.billing_source
    assert restored.pricing == model.pricing


def test_discount_is_not_a_usage_charge():
    assert (
        classify_pricing(
            {
                f"prompt": f"0",
                f"completion": f"0",
                f"discount": f"0.5",
            },
        )
        == f"free"
    )


@pytest.mark.parametrize(
    f"provider",
    [
        PROVIDER_ZHIPU_CN_CODINGPLAN,
        PROVIDER_ZHIPU_INTL_CODINGPLAN,
    ],
)
async def test_subscription_endpoint_does_not_inherit_free_model(provider):
    assert provider.resolve_model_info(f"glm-4.7-flash").billing == f"paid"
    assert not (await provider.get_info()).is_free_tier


def test_trial_quota_is_not_zero_price():
    card = PROVIDER_DASHSCOPE.resolve_model_info(f"qwen-plus")
    assert card.billing == f"paid"
    assert card.capability_provenance[f"billing"][f"reference"] == (
        f"https://help.aliyun.com/zh/model-studio/model-pricing"
    )


def test_updated_catalog_replaces_saved_catalog_billing():
    provider = PROVIDER_ZHIPU_CN_CODINGPLAN.model_copy(deep=True)
    provider.models = [
        ModelInfo(
            id=f"glm-4.7-flash",
            name=f"Flash",
            billing=f"free",
            is_free=True,
            billing_source=f"catalog",
        ),
    ]
    assert provider.resolve_model_info(f"glm-4.7-flash").billing == f"paid"
