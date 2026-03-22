# -*- coding: utf-8 -*-
"""Property-based tests for ModelInfo multimodal default values.

# Feature: multimodal-model-support, Property 1: ModelInfo 默认值不变量
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from copaw.providers.provider import ModelInfo as ProviderModelInfo
from copaw.providers.provider import ProviderInfo
from copaw.providers.models import ModelInfo as ModelsModelInfo


# ---------------------------------------------------------------------------
# Property 1: ModelInfo 默认值不变量
# For any ModelInfo created without specifying supports_multimodal,
# supports_image, or supports_video, all three SHALL default to False.
# **Validates: Requirements 1.1**
# ---------------------------------------------------------------------------


@given(
    model_id=st.text(min_size=1, max_size=50),
    name=st.text(min_size=1, max_size=50),
)
@settings(max_examples=100)
def test_provider_model_info_defaults_to_false(
    model_id: str,
    name: str,
) -> None:
    """provider.py ModelInfo: multimodal defaults to None."""
    info = ProviderModelInfo(id=model_id, name=name)
    assert info.supports_multimodal is None
    assert info.supports_image is None
    assert info.supports_video is None


@given(
    model_id=st.text(min_size=1, max_size=50),
    name=st.text(min_size=1, max_size=50),
)
@settings(max_examples=100)
def test_models_model_info_defaults_to_false(model_id: str, name: str) -> None:
    """models.py ModelInfo: multimodal defaults to None."""
    info = ModelsModelInfo(id=model_id, name=name)
    assert info.supports_multimodal is None
    assert info.supports_image is None
    assert info.supports_video is None


# ---------------------------------------------------------------------------
# Feature: multimodal-model-support, Property 2: ModelInfo 序列化往返
# For any ModelInfo with any valid id, name, and supports_multimodal value,
# serializing to JSON (via model_dump()) then deserializing (via
# model_validate()) SHALL produce an equivalent ModelInfo object with the
# same supports_multimodal value.
# **Validates: Requirements 1.4, 1.5**
# ---------------------------------------------------------------------------


@given(
    model_id=st.text(min_size=1, max_size=50),
    name=st.text(min_size=1, max_size=50),
    supports_multimodal=st.one_of(st.booleans(), st.none()),
    supports_image=st.one_of(st.booleans(), st.none()),
    supports_video=st.one_of(st.booleans(), st.none()),
)
@settings(max_examples=100)
def test_provider_model_info_serialization_roundtrip(
    model_id: str,
    name: str,
    supports_multimodal: bool,
    supports_image: bool,
    supports_video: bool,
) -> None:
    """provider.py ModelInfo: roundtrip serialization."""
    original = ProviderModelInfo(
        id=model_id,
        name=name,
        supports_multimodal=supports_multimodal,
        supports_image=supports_image,
        supports_video=supports_video,
    )
    data = original.model_dump()
    restored = ProviderModelInfo.model_validate(data)
    assert restored == original
    assert restored.supports_multimodal == original.supports_multimodal
    assert restored.supports_image == original.supports_image
    assert restored.supports_video == original.supports_video


@given(
    model_id=st.text(min_size=1, max_size=50),
    name=st.text(min_size=1, max_size=50),
    supports_multimodal=st.one_of(st.booleans(), st.none()),
    supports_image=st.one_of(st.booleans(), st.none()),
    supports_video=st.one_of(st.booleans(), st.none()),
)
@settings(max_examples=100)
def test_models_model_info_serialization_roundtrip(
    model_id: str,
    name: str,
    supports_multimodal: bool,
    supports_image: bool,
    supports_video: bool,
) -> None:
    """models.py ModelInfo: roundtrip serialization."""
    original = ModelsModelInfo(
        id=model_id,
        name=name,
        supports_multimodal=supports_multimodal,
        supports_image=supports_image,
        supports_video=supports_video,
    )
    data = original.model_dump()
    restored = ModelsModelInfo.model_validate(data)
    assert restored == original
    assert restored.supports_multimodal == original.supports_multimodal
    assert restored.supports_image == original.supports_image
    assert restored.supports_video == original.supports_video


# ---------------------------------------------------------------------------
# Feature: multimodal-model-support, Property 6: 探测结果持久化
# After probing, serializing (model_dump) then deserializing (model_validate)
# SHALL preserve the supports_multimodal value.
# The composite flag supports_multimodal = supports_image OR supports_video.
# **Validates: Requirements 4.1, 4.2**
# ---------------------------------------------------------------------------


@given(
    model_id=st.text(min_size=1, max_size=50),
    name=st.text(min_size=1, max_size=50),
    supports_image=st.booleans(),
    supports_video=st.booleans(),
)
@settings(max_examples=100)
def test_provider_model_info_probe_persistence(
    model_id: str,
    name: str,
    supports_image: bool,
    supports_video: bool,
) -> None:
    """provider.py ModelInfo: probe result survives serialize/deserialize."""
    supports_multimodal = supports_image or supports_video
    original = ProviderModelInfo(
        id=model_id,
        name=name,
        supports_image=supports_image,
        supports_video=supports_video,
        supports_multimodal=supports_multimodal,
    )

    # Simulate persistence: serialize to dict (JSON-ready) then restore
    data = original.model_dump()
    restored = ProviderModelInfo.model_validate(data)

    assert restored.supports_multimodal == supports_multimodal
    assert restored.supports_image == supports_image
    assert restored.supports_video == supports_video


@given(
    model_id=st.text(min_size=1, max_size=50),
    name=st.text(min_size=1, max_size=50),
    supports_image=st.booleans(),
    supports_video=st.booleans(),
)
@settings(max_examples=100)
def test_models_model_info_probe_persistence(
    model_id: str,
    name: str,
    supports_image: bool,
    supports_video: bool,
) -> None:
    """models.py ModelInfo: probe result survives serialize/deserialize."""
    supports_multimodal = supports_image or supports_video
    original = ModelsModelInfo(
        id=model_id,
        name=name,
        supports_image=supports_image,
        supports_video=supports_video,
        supports_multimodal=supports_multimodal,
    )

    # Simulate persistence: serialize to dict (JSON-ready) then restore
    data = original.model_dump()
    restored = ModelsModelInfo.model_validate(data)

    assert restored.supports_multimodal == supports_multimodal
    assert restored.supports_image == supports_image
    assert restored.supports_video == supports_video


# ---------------------------------------------------------------------------
# Feature: multimodal-model-support, Property 3: ProviderInfo 模型字段完整性
# For any ProviderInfo instance, every ModelInfo in its models and
# extra_models lists SHALL have supports_multimodal, supports_image, and
# supports_video boolean fields present in its serialized representation.
# **Validates: Requirements 1.2, 3.1**
# -------------------------------------------------------------------

# Strategy: generate a random ModelInfo with all fields randomised
_model_info_st = st.builds(
    ProviderModelInfo,
    id=st.text(min_size=1, max_size=30),
    name=st.text(min_size=1, max_size=30),
    supports_multimodal=st.one_of(st.booleans(), st.none()),
    supports_image=st.one_of(st.booleans(), st.none()),
    supports_video=st.one_of(st.booleans(), st.none()),
)

# Strategy: generate a random ProviderInfo with random models / extra_models
_provider_info_st = st.builds(
    ProviderInfo,
    id=st.text(min_size=1, max_size=30),
    name=st.text(min_size=1, max_size=30),
    models=st.lists(_model_info_st, min_size=0, max_size=5),
    extra_models=st.lists(_model_info_st, min_size=0, max_size=5),
)


@given(provider_info=_provider_info_st)
@settings(max_examples=100)
def test_provider_info_serialized_models_contain_multimodal_fields(
    provider_info: ProviderInfo,
) -> None:
    """ProviderInfo: serialized models have multimodal fields."""
    data = provider_info.model_dump()

    multimodal_keys = {
        "supports_multimodal",
        "supports_image",
        "supports_video",
    }

    for model_dict in data["models"]:
        assert multimodal_keys.issubset(model_dict.keys()), (
            f"models entry missing multimodal fields: "
            f"{multimodal_keys - model_dict.keys()}"
        )
        assert isinstance(
            model_dict["supports_multimodal"],
            (bool, type(None)),
        )
        assert isinstance(model_dict["supports_image"], (bool, type(None)))
        assert isinstance(model_dict["supports_video"], (bool, type(None)))

    for model_dict in data["extra_models"]:
        assert multimodal_keys.issubset(model_dict.keys()), (
            f"extra_models entry missing multimodal fields: "
            f"{multimodal_keys - model_dict.keys()}"
        )
        assert isinstance(
            model_dict["supports_multimodal"],
            (bool, type(None)),
        )
        assert isinstance(model_dict["supports_image"], (bool, type(None)))
        assert isinstance(model_dict["supports_video"], (bool, type(None)))
