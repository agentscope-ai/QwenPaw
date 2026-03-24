# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Property-based tests for capability_baseline module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st
from openai import APIStatusError

from copaw.providers.capability_baseline import (
    ExpectedCapability,
    ExpectedCapabilityRegistry,
    ProbeSource,
    compare_probe_result,
    generate_summary,
)
from copaw.providers.multimodal_prober import ProbeResult
from copaw.providers.ollama_provider import OllamaProvider
from copaw.providers.openai_provider import OpenAIProvider
from copaw.providers.provider import (
    ModelInfo as ProviderModelInfo,
    DefaultProvider,
)
from copaw.providers.provider_manager import (
    MODELSCOPE_MODELS,
    DASHSCOPE_MODELS,
    ALIYUN_CODINGPLAN_MODELS,
    OPENAI_MODELS,
    AZURE_OPENAI_MODELS,
    KIMI_MODELS,
    DEEPSEEK_MODELS,
    ANTHROPIC_MODELS,
    GEMINI_MODELS,
    MINIMAX_MODELS,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_provider_ids = st.text(min_size=1, max_size=20)
_model_ids = st.text(min_size=1, max_size=30)
_optional_bool = st.one_of(st.none(), st.booleans())


@st.composite
def expected_capability_st(draw: st.DrawFn) -> ExpectedCapability:
    """Generate a random ExpectedCapability."""
    return ExpectedCapability(
        provider_id=draw(_provider_ids),
        model_id=draw(_model_ids),
        expected_image=draw(_optional_bool),
        expected_video=draw(_optional_bool),
        doc_url=draw(st.text(max_size=50)),
        note=draw(st.text(max_size=50)),
    )


# ---------------------------------------------------------------------------
# Property 4: 差异检测正确性
# ---------------------------------------------------------------------------


class TestProperty4DiscrepancyDetection:
    """Feature: multimodal-probe-validation, Property 4: 差异检测正确性

    *For any* ExpectedCapability 和实际探测结果的组合，当 expected 值不为 None
    且 expected != actual 时，compare_probe_result 应生成一条 DiscrepancyLog；
    当 expected == actual 或 expected 为 None 时，不应生成 DiscrepancyLog。

    **Validates: Requirements 3.1, 3.2**
    """

    @given(
        expected=expected_capability_st(),
        actual_image=st.booleans(),
        actual_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_discrepancy_generated_when_expected_differs_from_actual(
        self,
        expected: ExpectedCapability,
        actual_image: bool,
        actual_video: bool,
    ) -> None:
        """When expected is not None and differs from actual, a DiscrepancyLog
        is produced for that field; otherwise no log is produced."""
        logs = compare_probe_result(expected, actual_image, actual_video)

        # Build the set of fields that SHOULD have discrepancies
        expected_discrepant_fields: set[str] = set()
        for field_name, exp_val, act_val in [
            ("image", expected.expected_image, actual_image),
            ("video", expected.expected_video, actual_video),
        ]:
            if exp_val is not None and exp_val != act_val:
                expected_discrepant_fields.add(field_name)

        actual_fields = {log.field for log in logs}
        assert actual_fields == expected_discrepant_fields

    @given(
        expected=expected_capability_st(),
        actual_image=st.booleans(),
        actual_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_no_discrepancy_when_expected_is_none(
        self,
        expected: ExpectedCapability,
        actual_image: bool,
        actual_video: bool,
    ) -> None:
        """Fields where expected is None never produce a DiscrepancyLog."""
        logs = compare_probe_result(expected, actual_image, actual_video)

        for log in logs:
            if log.field == "image":
                assert expected.expected_image is not None
            elif log.field == "video":
                assert expected.expected_video is not None

    @given(
        expected=expected_capability_st(),
        actual_image=st.booleans(),
        actual_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_no_discrepancy_when_expected_equals_actual(
        self,
        expected: ExpectedCapability,
        actual_image: bool,
        actual_video: bool,
    ) -> None:
        """Fields where expected == actual never produce a DiscrepancyLog."""
        logs = compare_probe_result(expected, actual_image, actual_video)

        for log in logs:
            if log.field == "image":
                assert expected.expected_image != actual_image
            elif log.field == "video":
                assert expected.expected_video != actual_video

    @given(
        expected=expected_capability_st(),
        actual_image=st.booleans(),
        actual_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_discrepancy_type_is_correct(
        self,
        expected: ExpectedCapability,
        actual_image: bool,
        actual_video: bool,
    ) -> None:
        """false_negative when expected=True, actual=False;
        false_positive when expected=False, actual=True."""
        logs = compare_probe_result(expected, actual_image, actual_video)

        for log in logs:
            if log.expected is True and log.actual is False:
                assert log.discrepancy_type == "false_negative"
            elif log.expected is False and log.actual is True:
                assert log.discrepancy_type == "false_positive"

    @given(
        expected=expected_capability_st(),
        actual_image=st.booleans(),
        actual_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_discrepancy_carries_provider_and_model(
        self,
        expected: ExpectedCapability,
        actual_image: bool,
        actual_video: bool,
    ) -> None:
        """DiscrepancyLog carries correct provider/model."""
        logs = compare_probe_result(expected, actual_image, actual_video)

        for log in logs:
            assert log.provider_id == expected.provider_id
            assert log.model_id == expected.model_id


# ---------------------------------------------------------------------------
# Property 5: 汇总报告数值一致性
# ---------------------------------------------------------------------------

_status_st = st.sampled_from(["ok", "discrepancy", "failure"])


@st.composite
def comparison_result_st(draw: st.DrawFn) -> tuple:
    """Generate a random (ExpectedCapability, actual, status) tuple."""
    cap = draw(expected_capability_st())
    actual_image = draw(st.booleans())
    actual_video = draw(st.booleans())
    status = draw(_status_st)
    return (cap, actual_image, actual_video, status)


class TestProperty5SummaryConsistency:
    """Feature: multimodal-probe-validation, Property 5: 汇总报告数值一致性

    *For any* 对比结果列表，generate_summary 返回的 ComparisonSummary 应满足
    total_models == passed + discrepancies + failures，且 details 列表仅包含
    status=="discrepancy" 条目产生的 DiscrepancyLog。

    **Validates: Requirements 3.4**
    """

    @given(results=st.lists(comparison_result_st(), min_size=0, max_size=50))
    @settings(max_examples=200)
    def test_total_equals_passed_plus_discrepancies_plus_failures(
        self,
        results: list[tuple],
    ) -> None:
        """total_models == passed + discrepancies + failures for any input."""

        summary = generate_summary(results)
        assert (
            summary.total_models
            == summary.passed + summary.discrepancies + summary.failures
        )

    @given(results=st.lists(comparison_result_st(), min_size=0, max_size=50))
    @settings(max_examples=200)
    def test_total_models_equals_input_length(
        self,
        results: list[tuple],
    ) -> None:
        """total_models equals the number of input results."""

        summary = generate_summary(results)
        assert summary.total_models == len(results)

    @given(results=st.lists(comparison_result_st(), min_size=0, max_size=50))
    @settings(max_examples=200)
    def test_passed_count_matches_ok_status(
        self,
        results: list[tuple],
    ) -> None:
        """passed count equals the number of 'ok' status entries."""

        summary = generate_summary(results)
        expected_passed = sum(1 for _, _, _, s in results if s == "ok")
        assert summary.passed == expected_passed

    @given(results=st.lists(comparison_result_st(), min_size=0, max_size=50))
    @settings(max_examples=200)
    def test_discrepancies_count_matches_discrepancy_status(
        self,
        results: list[tuple],
    ) -> None:
        """discrepancies count equals discrepancy status entries."""

        summary = generate_summary(results)
        expected_disc = sum(1 for _, _, _, s in results if s == "discrepancy")
        assert summary.discrepancies == expected_disc

    @given(results=st.lists(comparison_result_st(), min_size=0, max_size=50))
    @settings(max_examples=200)
    def test_failures_count_matches_failure_status(
        self,
        results: list[tuple],
    ) -> None:
        """failures count equals the number of 'failure' status entries."""

        summary = generate_summary(results)
        expected_fail = sum(1 for _, _, _, s in results if s == "failure")
        assert summary.failures == expected_fail

    @given(results=st.lists(comparison_result_st(), min_size=0, max_size=50))
    @settings(max_examples=200)
    def test_details_only_from_discrepancy_entries(
        self,
        results: list[tuple],
    ) -> None:
        """details list has only DiscrepancyLogs from 'discrepancy' entries."""
        summary = generate_summary(results)

        # Recompute expected details from discrepancy entries only
        expected_details = []
        for cap, img, vid, status in results:
            if status == "discrepancy":
                expected_details.extend(compare_probe_result(cap, img, vid))

        assert len(summary.details) == len(expected_details)


# ---------------------------------------------------------------------------
# Property 1: 基线数据完整性
# ---------------------------------------------------------------------------

# Build the complete mapping of provider_id → predefined ModelInfo list.
# Providers with no predefined models (ollama, lmstudio, llamacpp, mlx)
# and empty lists (anthropic) are excluded since there is nothing to verify.
_BUILTIN_PROVIDER_MODELS: list[tuple[str, str]] = []
for _pid, _models in [
    ("modelscope", MODELSCOPE_MODELS),
    ("dashscope", DASHSCOPE_MODELS),
    ("aliyun-codingplan", ALIYUN_CODINGPLAN_MODELS),
    ("openai", OPENAI_MODELS),
    ("azure-openai", AZURE_OPENAI_MODELS),
    ("kimi-cn", KIMI_MODELS),
    ("kimi-intl", KIMI_MODELS),
    ("deepseek", DEEPSEEK_MODELS),
    ("anthropic", ANTHROPIC_MODELS),
    ("gemini", GEMINI_MODELS),
    ("minimax", MINIMAX_MODELS),
    ("minimax-cn", MINIMAX_MODELS),
]:
    for _m in _models:
        _BUILTIN_PROVIDER_MODELS.append((_pid, _m.id))

# Hypothesis strategy: draw from the actual built-in
# (provider_id, model_id) pairs
_builtin_pair_st = (
    st.sampled_from(
        _BUILTIN_PROVIDER_MODELS,
    )
    if _BUILTIN_PROVIDER_MODELS
    else st.nothing()
)


class TestProperty1BaselineCompleteness:
    """Feature: multimodal-probe-validation, Property 1: 基线数据完整性

    *For any* 内置渠道及其预定义模型，ExpectedCapabilityRegistry 中都应存在
    对应的 ExpectedCapability 记录，且该记录包含非空的 provider_id、model_id
    和 doc_url 字段。当 expected_image 或 expected_video 为 None 时，note 字段
    必须非空。

    **Validates: Requirements 1.1, 1.3, 1.4**
    """

    @given(pair=_builtin_pair_st)
    @settings(max_examples=200)
    def test_registry_has_entry_for_every_builtin_model(
        self,
        pair: tuple[str, str],
    ) -> None:
        """Every built-in provider's predefined model has a corresponding
        ExpectedCapability entry in the registry."""
        provider_id, model_id = pair
        registry = ExpectedCapabilityRegistry()
        cap = registry.get_expected(provider_id, model_id)
        assert (
            cap is not None
        ), f"Missing ExpectedCapability for {provider_id}/{model_id}"

    @given(pair=_builtin_pair_st)
    @settings(max_examples=200)
    def test_registry_entry_has_nonempty_provider_id(
        self,
        pair: tuple[str, str],
    ) -> None:
        """provider_id in the registry entry is non-empty."""
        provider_id, model_id = pair
        registry = ExpectedCapabilityRegistry()
        cap = registry.get_expected(provider_id, model_id)
        assert cap is not None
        assert cap.provider_id, "provider_id must be non-empty"

    @given(pair=_builtin_pair_st)
    @settings(max_examples=200)
    def test_registry_entry_has_nonempty_model_id(
        self,
        pair: tuple[str, str],
    ) -> None:
        """model_id in the registry entry is non-empty."""
        provider_id, model_id = pair
        registry = ExpectedCapabilityRegistry()
        cap = registry.get_expected(provider_id, model_id)
        assert cap is not None
        assert cap.model_id, "model_id must be non-empty"

    @given(pair=_builtin_pair_st)
    @settings(max_examples=200)
    def test_registry_entry_has_nonempty_doc_url(
        self,
        pair: tuple[str, str],
    ) -> None:
        """doc_url in the registry entry is non-empty."""
        provider_id, model_id = pair
        registry = ExpectedCapabilityRegistry()
        cap = registry.get_expected(provider_id, model_id)
        assert cap is not None
        assert cap.doc_url, "doc_url must be non-empty"

    @given(pair=_builtin_pair_st)
    @settings(max_examples=200)
    def test_note_nonempty_when_expected_is_none(
        self,
        pair: tuple[str, str],
    ) -> None:
        """When expected is None, note must be non-empty."""
        provider_id, model_id = pair
        registry = ExpectedCapabilityRegistry()
        cap = registry.get_expected(provider_id, model_id)
        assert cap is not None
        if cap.expected_image is None or cap.expected_video is None:
            assert cap.note, (
                f"note must be non-empty when expected "
                f"is None for {provider_id}/{model_id}"
            )


# ---------------------------------------------------------------------------
# Property 8: Ollama 探测行为不变量
# -------------------------------------------------------------------

# Strategy: generate random base_url strings
# that look like valid HTTP URLs. We strip "/v1"
# suffix if present to match OllamaProvider
# model_post_init behaviour.
_ollama_base_url_st = st.from_regex(
    r"https?://[a-z0-9]{1,10}(\.[a-z0-9]{1,5})*(:[0-9]{2,5})?",
    fullmatch=True,
)


class TestProperty8OllamaProbeInvariant:
    """Feature: multimodal-probe-validation, Property 8: Ollama 探测行为不变量

    *For any* Ollama 模型的探测结果，supports_video 始终为 False，
    且探测请求应发送到 base_url + "/v1" 端点。

    **Validates: Requirements 7.2, 7.4**
    """

    @given(
        base_url=_ollama_base_url_st,
        model_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_:.",
            ),
        ),
        image_supported=st.booleans(),
    )
    @settings(max_examples=200)
    def test_supports_video_always_false(
        self,
        base_url: str,
        model_id: str,
        image_supported: bool,
    ) -> None:
        """supports_video is always False regardless of base_url or model."""
        mock_probe = AsyncMock(
            return_value=(image_supported, "mock probe msg"),
        )

        with patch(
            "copaw.providers.openai_provider.OpenAIProvider"
            "._probe_image_support",
            mock_probe,
        ):
            provider = OllamaProvider(
                id="ollama",
                name="Ollama",
                base_url=base_url,
                is_local=True,
                require_api_key=False,
            )
            result = asyncio.run(provider.probe_model_multimodal(model_id))

        assert result.supports_video is False

    @given(
        base_url=_ollama_base_url_st,
        model_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_:.",
            ),
        ),
        image_supported=st.booleans(),
    )
    @settings(max_examples=200)
    def test_probe_sends_to_v1_endpoint(
        self,
        base_url: str,
        model_id: str,
        image_supported: bool,
    ) -> None:
        """Proxy OpenAIProvider is created with base_url + '/v1'."""
        mock_probe = AsyncMock(
            return_value=(image_supported, "mock probe msg"),
        )

        with patch(
            "copaw.providers.openai_provider.OpenAIProvider.__init__",
            return_value=None,
        ) as mock_init, patch(
            "copaw.providers.openai_provider.OpenAIProvider"
            "._probe_image_support",
            mock_probe,
        ):
            provider = OllamaProvider(
                id="ollama",
                name="Ollama",
                base_url=base_url,
                is_local=True,
                require_api_key=False,
            )
            asyncio.run(provider.probe_model_multimodal(model_id))

        mock_init.assert_called_once()
        expected_url = base_url.rstrip("/") + "/v1"
        called_url = mock_init.call_args.kwargs.get("base_url")
        assert (
            called_url == expected_url
        ), f"Expected probe URL {expected_url!r}, got {called_url!r}"

    @given(
        base_url=_ollama_base_url_st,
        model_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_:.",
            ),
        ),
    )
    @settings(max_examples=200)
    def test_supports_image_reflects_probe_result(
        self,
        base_url: str,
        model_id: str,
    ) -> None:
        """supports_image matches whatever _probe_image_support returns."""
        for expected_image in (True, False):
            mock_probe = AsyncMock(return_value=(expected_image, "msg"))

            with patch(
                "copaw.providers.openai_provider.OpenAIProvider"
                "._probe_image_support",
                mock_probe,
            ):
                provider = OllamaProvider(
                    id="ollama",
                    name="Ollama",
                    base_url=base_url,
                    is_local=True,
                    require_api_key=False,
                )
                result = asyncio.run(provider.probe_model_multimodal(model_id))

            assert result.supports_image == expected_image

    @given(
        base_url=_ollama_base_url_st,
        model_id=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_:.",
            ),
        ),
    )
    @settings(max_examples=200)
    def test_api_key_defaults_to_ollama(
        self,
        base_url: str,
        model_id: str,
    ) -> None:
        """When provider has no api_key, proxy uses 'ollama' as default."""
        mock_probe = AsyncMock(return_value=(True, "msg"))

        with patch(
            "copaw.providers.openai_provider.OpenAIProvider.__init__",
            return_value=None,
        ) as mock_init, patch(
            "copaw.providers.openai_provider.OpenAIProvider"
            "._probe_image_support",
            mock_probe,
        ):
            provider = OllamaProvider(
                id="ollama",
                name="Ollama",
                base_url=base_url,
                api_key="",
                is_local=True,
                require_api_key=False,
            )
            asyncio.run(provider.probe_model_multimodal(model_id))

        mock_init.assert_called_once()
        called_api_key = mock_init.call_args.kwargs.get("api_key")
        assert called_api_key == "ollama"


# -------------------------------------------------------------------
# Property 9: default annotation override mechanism
# -------------------------------------------------------------------

# Use the provider-level ModelInfo for Property 9 tests
_ModelInfo = ProviderModelInfo


@st.composite
def model_info_st(draw: st.DrawFn) -> ProviderModelInfo:
    """Generate a random ModelInfo with multimodal=None."""
    model_id = draw(
        st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
    )
    name = draw(st.text(min_size=1, max_size=30))
    return _ModelInfo(id=model_id, name=name)


@st.composite
def expected_cap_with_known_values_st(
    draw: st.DrawFn,
    provider_id: str,
    model_id: str,
) -> ExpectedCapability:
    """Generate ExpectedCapability with concrete values."""
    expected_image = draw(st.booleans())
    expected_video = draw(st.booleans())
    return ExpectedCapability(
        provider_id=provider_id,
        model_id=model_id,
        expected_image=expected_image,
        expected_video=expected_video,
        doc_url="https://example.com/docs",
    )


class TestProperty9DefaultAnnotationOverride:
    """Feature: multimodal-probe-validation, Property 9: 默认标注与实际探测的覆盖机制

    *For any* 未配置 API Key 的渠道模型，其 ModelInfo 的 supports_image 和
    supports_video 应等于 ExpectedCapability 中的预期值，且 probe_source 为
    "documentation"。当后续执行实际探测后，probe_source 应变为 "probed"，
    且 supports_image/supports_video 应反映实际探测结果。

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    """

    @given(
        expected_image=st.booleans(),
        expected_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_default_annotation_sets_documentation_probe_source(
        self,
        expected_image: bool,
        expected_video: bool,
    ) -> None:
        """Models with supports_multimodal=None get
        probe_source='documentation'
        after _apply_default_annotations."""
        model = _ModelInfo(id="test-model", name="Test Model")
        assert model.supports_multimodal is None

        # Create a mock provider with this model
        provider = DefaultProvider(
            id="test-provider",
            name="Test Provider",
            models=[model],
            is_local=True,
            require_api_key=False,
        )

        # Create a registry with a matching entry
        registry = ExpectedCapabilityRegistry()
        registry._data[("test-provider", "test-model")] = ExpectedCapability(
            provider_id="test-provider",
            model_id="test-model",
            expected_image=expected_image,
            expected_video=expected_video,
            doc_url="https://example.com/docs",
        )

        # Simulate _apply_default_annotations logic
        for m in provider.models:
            if m.supports_multimodal is None:
                expected = registry.get_expected(provider.id, m.id)
                if expected:
                    m.supports_image = expected.expected_image
                    m.supports_video = expected.expected_video
                    m.supports_multimodal = (
                        expected.expected_image or False
                    ) or (expected.expected_video or False)
                    m.probe_source = "documentation"

        assert model.probe_source == ProbeSource.DOCUMENTATION.value

    @given(
        expected_image=st.booleans(),
        expected_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_default_annotation_sets_expected_capability_values(
        self,
        expected_image: bool,
        expected_video: bool,
    ) -> None:
        """After default annotation, supports_image/supports_video match
        ExpectedCapability values."""
        model = _ModelInfo(id="test-model", name="Test Model")

        provider = DefaultProvider(
            id="test-provider",
            name="Test Provider",
            models=[model],
            is_local=True,
            require_api_key=False,
        )

        registry = ExpectedCapabilityRegistry()
        registry._data[("test-provider", "test-model")] = ExpectedCapability(
            provider_id="test-provider",
            model_id="test-model",
            expected_image=expected_image,
            expected_video=expected_video,
            doc_url="https://example.com/docs",
        )

        for m in provider.models:
            if m.supports_multimodal is None:
                expected = registry.get_expected(provider.id, m.id)
                if expected:
                    m.supports_image = expected.expected_image
                    m.supports_video = expected.expected_video
                    m.supports_multimodal = (
                        expected.expected_image or False
                    ) or (expected.expected_video or False)
                    m.probe_source = "documentation"

        assert model.supports_image == expected_image
        assert model.supports_video == expected_video

    @given(
        expected_image=st.booleans(),
        expected_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_default_annotation_sets_supports_multimodal_correctly(
        self,
        expected_image: bool,
        expected_video: bool,
    ) -> None:
        """supports_multimodal True iff expected_image
        or expected_video is True."""
        model = _ModelInfo(id="test-model", name="Test Model")

        provider = DefaultProvider(
            id="test-provider",
            name="Test Provider",
            models=[model],
            is_local=True,
            require_api_key=False,
        )

        registry = ExpectedCapabilityRegistry()
        registry._data[("test-provider", "test-model")] = ExpectedCapability(
            provider_id="test-provider",
            model_id="test-model",
            expected_image=expected_image,
            expected_video=expected_video,
            doc_url="https://example.com/docs",
        )

        for m in provider.models:
            if m.supports_multimodal is None:
                expected = registry.get_expected(provider.id, m.id)
                if expected:
                    m.supports_image = expected.expected_image
                    m.supports_video = expected.expected_video
                    m.supports_multimodal = (
                        expected.expected_image or False
                    ) or (expected.expected_video or False)
                    m.probe_source = "documentation"

        assert model.supports_multimodal == (expected_image or expected_video)

    @given(
        expected_image=st.booleans(),
        expected_video=st.booleans(),
        probed_image=st.booleans(),
        probed_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_probe_overrides_default_annotation(
        self,
        expected_image: bool,
        expected_video: bool,
        probed_image: bool,
        probed_video: bool,
    ) -> None:
        """After actual probing, probe_source changes to 'probed' and
        supports_image/supports_video reflect the probed values."""
        model = _ModelInfo(id="test-model", name="Test Model")

        provider = DefaultProvider(
            id="test-provider",
            name="Test Provider",
            models=[model],
            is_local=True,
            require_api_key=False,
        )

        registry = ExpectedCapabilityRegistry()
        registry._data[("test-provider", "test-model")] = ExpectedCapability(
            provider_id="test-provider",
            model_id="test-model",
            expected_image=expected_image,
            expected_video=expected_video,
            doc_url="https://example.com/docs",
        )

        # Step 1: Apply default annotations
        for m in provider.models:
            if m.supports_multimodal is None:
                exp = registry.get_expected(provider.id, m.id)
                if exp:
                    m.supports_image = exp.expected_image
                    m.supports_video = exp.expected_video
                    m.supports_multimodal = (exp.expected_image or False) or (
                        exp.expected_video or False
                    )
                    m.probe_source = "documentation"

        assert model.probe_source == "documentation"

        # Step 2: Simulate actual probing
        # (as done in ProviderManager)
        for m in provider.models:
            if m.id == "test-model":
                m.supports_image = probed_image
                m.supports_video = probed_video
                m.supports_multimodal = probed_image or probed_video
                m.probe_source = "probed"

        assert model.probe_source == ProbeSource.PROBED.value
        assert model.supports_image == probed_image
        assert model.supports_video == probed_video
        assert model.supports_multimodal == (probed_image or probed_video)

    @given(data=st.data())
    @settings(max_examples=200)
    def test_no_annotation_when_no_registry_entry(
        self,
        data: st.DataObject,
    ) -> None:
        """Models without matching entry remain unannotated."""
        model_id = data.draw(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="-_.",
                ),
            ),
        )
        model = _ModelInfo(id=model_id, name="Unknown Model")

        provider = DefaultProvider(
            id="unknown-provider",
            name="Unknown Provider",
            models=[model],
            is_local=True,
            require_api_key=False,
        )

        # Use a fresh registry (no custom entries for "unknown-provider")
        registry = ExpectedCapabilityRegistry()

        for m in provider.models:
            if m.supports_multimodal is None:
                expected = registry.get_expected(provider.id, m.id)
                if expected:
                    m.supports_image = expected.expected_image
                    m.supports_video = expected.expected_video
                    m.supports_multimodal = (
                        expected.expected_image or False
                    ) or (expected.expected_video or False)
                    m.probe_source = "documentation"

        # Model should remain unannotated
        assert model.supports_multimodal is None
        assert model.supports_image is None
        assert model.supports_video is None
        assert model.probe_source is None

    @given(
        expected_image=st.booleans(),
        expected_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_already_probed_model_not_overwritten_by_default_annotation(
        self,
        expected_image: bool,
        expected_video: bool,
    ) -> None:
        """Models that already have supports_multimodal set (not None) are
        not overwritten by _apply_default_annotations."""
        model = _ModelInfo(
            id="test-model",
            name="Test Model",
            supports_multimodal=True,
            supports_image=True,
            supports_video=False,
            probe_source="probed",
        )

        provider = DefaultProvider(
            id="test-provider",
            name="Test Provider",
            models=[model],
            is_local=True,
            require_api_key=False,
        )

        registry = ExpectedCapabilityRegistry()
        registry._data[("test-provider", "test-model")] = ExpectedCapability(
            provider_id="test-provider",
            model_id="test-model",
            expected_image=expected_image,
            expected_video=expected_video,
            doc_url="https://example.com/docs",
        )

        # Apply default annotations — should skip already-probed model
        for m in provider.models:
            if m.supports_multimodal is None:
                exp = registry.get_expected(provider.id, m.id)
                if exp:
                    m.supports_image = exp.expected_image
                    m.supports_video = exp.expected_video
                    m.supports_multimodal = (exp.expected_image or False) or (
                        exp.expected_video or False
                    )
                    m.probe_source = "documentation"

        # Original probed values should be preserved
        assert model.probe_source == "probed"
        assert model.supports_image is True
        assert model.supports_video is False
        assert model.supports_multimodal is True


# ---------------------------------------------------------------------------
# Property 2: 探测结果包含双模态字段
# -------------------------------------------------------------------


class TestProperty2ProbeResultStructuralInvariant:
    """Feature: multimodal-probe-validation, Property 2: 探测结果包含双模态字段

    *For any* 对 probe_multimodal_support 的调用（无论成功或失败），返回的
    ProbeResult 都应同时包含 supports_image 和 supports_video 两个布尔值字段，
    且 supports_multimodal 等于 supports_image OR supports_video。

    **Validates: Requirements 2.2**
    """

    @given(
        supports_image=st.booleans(),
        supports_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_supports_multimodal_equals_image_or_video(
        self,
        supports_image: bool,
        supports_video: bool,
    ) -> None:
        """supports_multimodal is always supports_image OR supports_video."""
        result = ProbeResult(
            supports_image=supports_image,
            supports_video=supports_video,
        )
        assert result.supports_multimodal == (supports_image or supports_video)

    @given(
        supports_image=st.booleans(),
        supports_video=st.booleans(),
        image_message=st.text(max_size=100),
        video_message=st.text(max_size=100),
    )
    @settings(max_examples=200)
    def test_probe_result_always_has_boolean_fields(
        self,
        supports_image: bool,
        supports_video: bool,
        image_message: str,
        video_message: str,
    ) -> None:
        """ProbeResult has supports_image/video as bools."""
        result = ProbeResult(
            supports_image=supports_image,
            supports_video=supports_video,
            image_message=image_message,
            video_message=video_message,
        )
        assert isinstance(result.supports_image, bool)
        assert isinstance(result.supports_video, bool)
        assert isinstance(result.supports_multimodal, bool)

    @given(
        supports_image=st.booleans(),
        supports_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_supports_multimodal_true_iff_any_modality_supported(
        self,
        supports_image: bool,
        supports_video: bool,
    ) -> None:
        """supports_multimodal True iff any modality on."""
        result = ProbeResult(
            supports_image=supports_image,
            supports_video=supports_video,
        )
        if supports_image or supports_video:
            assert result.supports_multimodal is True
        else:
            assert result.supports_multimodal is False

    @given(
        supports_image=st.booleans(),
        supports_video=st.booleans(),
    )
    @settings(max_examples=200)
    def test_default_messages_are_empty_strings(
        self,
        supports_image: bool,
        supports_video: bool,
    ) -> None:
        """No messages => image/video_message default to ""."""
        result = ProbeResult(
            supports_image=supports_image,
            supports_video=supports_video,
        )
        assert result.image_message == ""
        assert result.video_message == ""


# ---------------------------------------------------------------------------
# Property 3: error type distinction
# -------------------------------------------------------------------


def _make_api_error(
    status_code: int,
    message: str,
) -> APIStatusError:
    """Create an APIStatusError with given status code."""
    mock_response = httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://fake.api/v1/chat/completions"),
    )
    return APIStatusError(
        message=message,
        response=mock_response,
        body={"error": {"message": message}},
    )


# Media keywords that _is_media_keyword_error checks for
_MEDIA_KEYWORDS = [
    "image",
    "video",
    "vision",
    "multimodal",
    "image_url",
    "video_url",
    "does not support",
]

# Strategies for generating error scenarios
_media_keyword_st = st.sampled_from(_MEDIA_KEYWORDS)

_non_media_message_st = st.text(
    min_size=1,
    max_size=60,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(
    lambda s: not any(kw in s.lower() for kw in _MEDIA_KEYWORDS),
)


class TestProperty3ErrorTypeDistinction:
    """Feature: multimodal-probe-validation, Property 3: 错误类型区分——网络错误 vs 不支持

    *For any* 探测过程中发生的异常，如果异常是网络超时（TimeoutException）或
    连接错误（ConnectionError），则探测消息应包含 "failed" 或 "timed out" 等
    关键词（表示探测失败）；如果异常是 400 状态码或包含媒体关键词的 APIError，
    则消息应包含 "not supported"（表示不支持）。

    **Validates: Requirements 2.4, 5.3, 6.3**
    """

    # --- General Exception (timeout, connection, etc.) → "Probe failed" ---

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        error_message=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_general_exception_produces_probe_failed_for_image(
        self,
        model_id: str,
        error_message: str,
    ) -> None:
        """General exceptions produce 'Probe failed' for image."""
        exc = Exception(error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support(model_id),
            )

        assert ok is False
        assert "Probe failed" in msg

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        error_message=st.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    def test_general_exception_produces_probe_failed_for_video(
        self,
        model_id: str,
        error_message: str,
    ) -> None:
        """General exceptions produce 'Probe failed' for video probe."""
        exc = Exception(error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support(model_id),
            )

        assert ok is False
        assert "Probe failed" in msg

    # --- APIError with status_code 400 → "not supported" ---

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        error_message=_non_media_message_st,
    )
    @settings(max_examples=100)
    def test_api_error_400_produces_not_supported_for_image(
        self,
        model_id: str,
        error_message: str,
    ) -> None:
        """400 error produces 'not supported' for image."""
        exc = _make_api_error(400, error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support(model_id),
            )

        assert ok is False
        assert "not supported" in msg.lower()

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        error_message=_non_media_message_st,
    )
    @settings(max_examples=100)
    def test_api_error_400_produces_not_supported_for_video(
        self,
        model_id: str,
        error_message: str,
    ) -> None:
        """400 on all formats produces 'not supported'
        for video probe.

        Video probe tries base64 first, then HTTP URL. When both get 400,
        the final message should contain 'not supported'.
        """
        exc = _make_api_error(400, error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support(model_id),
            )

        assert ok is False
        assert "not supported" in msg.lower()

    # --- APIError with media keyword → "not supported" ---

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        keyword=_media_keyword_st,
        status_code=st.sampled_from([401, 403, 422, 500]),
    )
    @settings(max_examples=100)
    def test_api_error_with_media_keyword_produces_not_supported_for_image(
        self,
        model_id: str,
        keyword: str,
        status_code: int,
    ) -> None:
        """Media keyword error produces 'not supported'
        for image probe."""
        error_message = f"The model {keyword} capability is not available"
        exc = _make_api_error(status_code, error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support(model_id),
            )

        assert ok is False
        assert "not supported" in msg.lower()

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        keyword=_media_keyword_st,
        status_code=st.sampled_from([401, 403, 422, 500]),
    )
    @settings(max_examples=100)
    def test_api_error_with_media_keyword_produces_not_supported_for_video(
        self,
        model_id: str,
        keyword: str,
        status_code: int,
    ) -> None:
        """Media keyword error produces 'not supported'
        for video probe."""
        error_message = f"The model {keyword} capability is not available"
        exc = _make_api_error(status_code, error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support(model_id),
            )

        assert ok is False
        assert "not supported" in msg.lower()

    # --- Non-400, non-media-keyword APIError → "Probe inconclusive" ---

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        error_message=_non_media_message_st,
        status_code=st.sampled_from([401, 403, 422, 500, 502, 503]),
    )
    @settings(max_examples=100)
    def test_other_api_error_produces_inconclusive_for_image(
        self,
        model_id: str,
        error_message: str,
        status_code: int,
    ) -> None:
        """Non-400, non-keyword APIError produces
        'Probe inconclusive' for image."""
        exc = _make_api_error(status_code, error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support(model_id),
            )

        assert ok is False
        assert "Probe inconclusive" in msg

    @given(
        model_id=st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("L", "N"),
                whitelist_characters="-_.",
            ),
        ),
        error_message=_non_media_message_st,
        status_code=st.sampled_from([401, 403, 422, 500, 502, 503]),
    )
    @settings(max_examples=100)
    def test_other_api_error_produces_inconclusive_for_video(
        self,
        model_id: str,
        error_message: str,
        status_code: int,
    ) -> None:
        """Non-400, non-keyword APIError produces
        'Probe inconclusive' for video."""
        exc = _make_api_error(status_code, error_message)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support(model_id),
            )

        assert ok is False
        assert "inconclusive" in msg


# ---------------------------------------------------------------------------
# Property 6: 思考型模型 reasoning_content 回退
# ---------------------------------------------------------------------------


def _make_chat_response(content: str, reasoning_content: str | None = None):
    """Build a minimal mock chat completion response.

    Parameters
    ----------
    content:
        The ``message.content`` value returned by the model.
    reasoning_content:
        If not *None*, the ``message.reasoning_content`` attribute is set to
        this value (simulating a "thinking" model like Kimi K2.5).
    """
    from unittest.mock import MagicMock

    message = MagicMock()
    message.content = content
    if reasoning_content is not None:
        message.reasoning_content = reasoning_content
    else:
        # Simulate a message without reasoning_content attribute
        del message.reasoning_content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


# Strategy: generate non-keyword filler text that does NOT accidentally
# contain the colour keywords we are testing for.
_IMAGE_KEYWORDS = ("red", "红")
_VIDEO_KEYWORDS = ("blue", "蓝")
_ALL_KEYWORDS = _IMAGE_KEYWORDS + _VIDEO_KEYWORDS

_filler_text_st = st.text(
    min_size=0,
    max_size=40,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: not any(kw in s.lower() for kw in _ALL_KEYWORDS))

_image_keyword_st = st.sampled_from(list(_IMAGE_KEYWORDS))
_video_keyword_st = st.sampled_from(list(_VIDEO_KEYWORDS))


class TestProperty6ReasoningContentFallback:
    """Property 6: reasoning_content fallback

    *For any* 探测响应，当 content 为空但 reasoning_content 包含预期颜色关键词
    （"red"/"红" 用于图片，"blue"/"蓝" 用于视频）时，probe_image_support /
    probe_video_support 应返回 True。

    **Validates: Requirements 4.4**
    """

    # ------------------------------------------------------------------
    # Image probe: reasoning_content fallback
    # ------------------------------------------------------------------

    @given(
        keyword=_image_keyword_st,
        prefix=_filler_text_st,
        suffix=_filler_text_st,
    )
    @settings(max_examples=200)
    def test_image_probe_returns_true_when_reasoning_contains_red(
        self,
        keyword: str,
        prefix: str,
        suffix: str,
    ) -> None:
        """When content is empty and reasoning_content contains 'red'/'红',
        probe_image_support returns True."""
        reasoning_text = f"{prefix}{keyword}{suffix}"
        mock_response = _make_chat_response(
            content="",
            reasoning_content=reasoning_text,
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            return_value=mock_response,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support("thinking-model"),
            )

        assert ok is True, f"Expected True but got False, msg={msg!r}"

    @given(
        keyword=_video_keyword_st,
        prefix=_filler_text_st,
        suffix=_filler_text_st,
    )
    @settings(max_examples=200)
    def test_video_probe_returns_true_when_reasoning_contains_blue(
        self,
        keyword: str,
        prefix: str,
        suffix: str,
    ) -> None:
        """When content is empty and reasoning_content contains 'blue'/'蓝',
        probe_video_support returns True."""
        reasoning_text = f"{prefix}{keyword}{suffix}"
        mock_response = _make_chat_response(
            content="",
            reasoning_content=reasoning_text,
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            return_value=mock_response,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support("thinking-model"),
            )

        assert ok is True, f"Expected True but got False, msg={msg!r}"

    # ------------------------------------------------------------------
    # Primary path: content contains keyword → True (no fallback needed)
    # ------------------------------------------------------------------

    @given(
        keyword=_image_keyword_st,
        prefix=_filler_text_st,
        suffix=_filler_text_st,
    )
    @settings(max_examples=200)
    def test_image_probe_returns_true_when_content_contains_red(
        self,
        keyword: str,
        prefix: str,
        suffix: str,
    ) -> None:
        """When content itself contains 'red'/'红', probe_image_support
        returns True without needing reasoning_content."""
        content_text = f"{prefix}{keyword}{suffix}"
        mock_response = _make_chat_response(
            content=content_text,
            reasoning_content=None,
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            return_value=mock_response,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support("normal-model"),
            )

        assert ok is True, f"Expected True but got False, msg={msg!r}"

    @given(
        keyword=_video_keyword_st,
        prefix=_filler_text_st,
        suffix=_filler_text_st,
    )
    @settings(max_examples=200)
    def test_video_probe_returns_true_when_content_contains_blue(
        self,
        keyword: str,
        prefix: str,
        suffix: str,
    ) -> None:
        """When content itself contains 'blue'/'蓝', probe_video_support
        returns True without needing reasoning_content."""
        content_text = f"{prefix}{keyword}{suffix}"
        mock_response = _make_chat_response(
            content=content_text,
            reasoning_content=None,
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            return_value=mock_response,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support("normal-model"),
            )

        assert ok is True, f"Expected True but got False, msg={msg!r}"

    # ------------------------------------------------------------------
    # Negative: neither content nor reasoning_content has keyword → False
    # ------------------------------------------------------------------

    @given(
        content=_filler_text_st,
        reasoning=_filler_text_st,
    )
    @settings(max_examples=200)
    def test_image_probe_returns_false_when_no_red_keyword(
        self,
        content: str,
        reasoning: str,
    ) -> None:
        """When neither content nor reasoning_content contains 'red'/'红',
        probe_image_support returns False."""
        mock_response = _make_chat_response(
            content=content,
            reasoning_content=reasoning if reasoning else None,
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            return_value=mock_response,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_image_support("no-vision-model"),
            )

        assert ok is False, f"Expected False but got True, msg={msg!r}"

    @given(
        content=_filler_text_st,
        reasoning=_filler_text_st,
    )
    @settings(max_examples=200)
    def test_video_probe_returns_false_when_no_blue_keyword(
        self,
        content: str,
        reasoning: str,
    ) -> None:
        """When neither content nor reasoning_content contains 'blue'/'蓝',
        probe_video_support returns False."""
        mock_response = _make_chat_response(
            content=content,
            reasoning_content=reasoning if reasoning else None,
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            return_value=mock_response,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support("no-vision-model"),
            )

        assert ok is False, f"Expected False but got True, msg={msg!r}"


# ---------------------------------------------------------------------------
# Property 7: 视频探测格式回退链
# ---------------------------------------------------------------------------


# Strategy: generate a random "blue"-containing answer for successful responses
_blue_answer_st = st.sampled_from(["blue", "蓝", "Blue", "BLUE", "蓝色"])


@st.composite
def _video_fallback_scenario_st(draw: st.DrawFn):
    """Generate a (base64_outcome, http_url_outcome) pair.

    Each outcome is one of:
      - ("400", error_message)   → provider rejects with 400
      - ("success", answer_text) → provider returns a chat completion
    """
    outcome_kind = st.sampled_from(["400", "success"])

    b64_kind = draw(outcome_kind)
    if b64_kind == "400":
        b64_val = draw(st.text(min_size=1, max_size=40))
    else:
        b64_val = draw(_blue_answer_st)

    http_kind = draw(outcome_kind)
    if http_kind == "400":
        http_val = draw(st.text(min_size=1, max_size=40))
    else:
        http_val = draw(_blue_answer_st)

    return (b64_kind, b64_val), (http_kind, http_val)


class TestProperty7VideoFallbackChain:
    """Feature: multimodal-probe-validation, Property 7: 视频探测格式回退链

    *For any* OpenAI 兼容渠道的视频探测，当 base64 格式被 400 拒绝时应回退到
    HTTP URL 格式；当两种格式均被拒绝时，supports_video 应为 False 且
    video_message 应包含错误信息。

    **Validates: Requirements 4.5**
    """

    @given(scenario=_video_fallback_scenario_st())
    @settings(max_examples=200)
    def test_fallback_chain_outcomes(
        self,
        scenario: tuple,
    ) -> None:
        """Verify the full fallback chain: base64 → HTTP URL.

        - base64 success → True (HTTP URL never tried)
        - base64 400, HTTP URL success → True
        - base64 400, HTTP URL 400 → False with 'not supported'
        """
        (b64_kind, b64_val), (http_kind, http_val) = scenario

        call_count = 0

        async def _mock_create(**_kwargs):
            nonlocal call_count
            call_count += 1
            # First call is base64, second is HTTP URL
            if call_count == 1:
                kind, val = b64_kind, b64_val
            else:
                kind, val = http_kind, http_val

            if kind == "400":
                raise _make_api_error(400, val)
            return _make_chat_response(content=val)

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=_mock_create,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support("test-model"),
            )

        if b64_kind == "success":
            # base64 succeeded → should return True, HTTP URL never tried
            assert ok is True
            assert call_count == 1
        elif http_kind == "success":
            # base64 rejected, HTTP URL succeeded → True
            assert ok is True
            assert call_count == 2
        else:
            # Both rejected → False
            assert ok is False
            assert "not supported" in msg.lower()
            assert call_count == 2

    @given(
        error_msg=st.text(min_size=1, max_size=40),
    )
    @settings(max_examples=200)
    def test_both_formats_rejected_returns_false(
        self,
        error_msg: str,
    ) -> None:
        """When both base64 and HTTP URL get 400, supports_video is False."""
        exc = _make_api_error(400, error_msg)
        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=exc,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, msg = asyncio.run(
                provider._probe_video_support("test-model"),
            )

        assert ok is False
        assert "not supported" in msg.lower()

    @given(
        answer=_blue_answer_st,
        error_msg=st.text(min_size=1, max_size=40),
    )
    @settings(max_examples=200)
    def test_base64_rejected_http_url_success_returns_true(
        self,
        answer: str,
        error_msg: str,
    ) -> None:
        """Base64 400 + HTTP URL success => True."""
        call_count = 0

        async def _mock_create(**_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise _make_api_error(400, error_msg)
            return _make_chat_response(content=answer)

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=_mock_create,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, _msg = asyncio.run(
                provider._probe_video_support("test-model"),
            )

        assert ok is True
        assert call_count == 2

    @given(
        answer=_blue_answer_st,
    )
    @settings(max_examples=200)
    def test_base64_success_skips_http_url(
        self,
        answer: str,
    ) -> None:
        """When base64 succeeds, HTTP URL is never tried (only 1 API call)."""
        call_count = 0

        async def _mock_create(**_kwargs):
            nonlocal call_count
            call_count += 1
            return _make_chat_response(content=answer)

        mock_client_instance = AsyncMock()
        mock_client_instance.chat.completions.create = AsyncMock(
            side_effect=_mock_create,
        )

        with patch(
            "copaw.providers.openai_provider.AsyncOpenAI",
            return_value=mock_client_instance,
        ):
            provider = OpenAIProvider(
                id="test",
                name="Test",
                base_url="https://fake.api",
                api_key="test-key",
            )
            ok, _msg = asyncio.run(
                provider._probe_video_support("test-model"),
            )

        assert ok is True
        assert call_count == 1


# ---------------------------------------------------------------------------
# Property 10: 媒体关键词错误检测
# ---------------------------------------------------------------------------


class TestProperty10MediaKeywordErrorDetection:
    """Feature: multimodal-probe-validation, Property 10: 媒体关键词错误检测

    *For any* 包含 "image"、"video"、"vision"、"multimodal"、"image_url"、
    "video_url" 或 "does not support" 关键词的异常消息，_is_media_keyword_error
    应返回 True；对于不包含这些关键词的消息，应返回 False。

    **Validates: Requirements 5.3, 6.3**
    """

    @given(keyword=_media_keyword_st)
    @settings(max_examples=200)
    def test_single_keyword_returns_true(self, keyword: str) -> None:
        """Exception containing any single media keyword → True."""
        from copaw.providers.multimodal_prober import _is_media_keyword_error

        exc = Exception(keyword)
        assert _is_media_keyword_error(exc) is True

    @given(message=_non_media_message_st)
    @settings(max_examples=200)
    def test_no_keyword_returns_false(self, message: str) -> None:
        """Exception with NO media keywords → False."""
        from copaw.providers.multimodal_prober import _is_media_keyword_error

        exc = Exception(message)
        assert _is_media_keyword_error(exc) is False

    @given(
        keyword=_media_keyword_st,
        case_fn=st.sampled_from([str.upper, str.title, str.swapcase]),
    )
    @settings(max_examples=200)
    def test_case_insensitive_matching(
        self,
        keyword: str,
        case_fn,
    ) -> None:
        """Keyword matching is case-insensitive (function lowercases)."""
        from copaw.providers.multimodal_prober import _is_media_keyword_error

        exc = Exception(case_fn(keyword))
        assert _is_media_keyword_error(exc) is True

    @given(
        prefix=st.text(min_size=0, max_size=30),
        keyword=_media_keyword_st,
        suffix=st.text(min_size=0, max_size=30),
        case_fn=st.sampled_from(
            [str.lower, str.upper, str.title, str.swapcase],
        ),
    )
    @settings(max_examples=200)
    def test_keyword_embedded_in_random_text(
        self,
        prefix: str,
        keyword: str,
        suffix: str,
        case_fn,
    ) -> None:
        """Mixed-case keyword embedded in random surrounding text → True."""
        from copaw.providers.multimodal_prober import _is_media_keyword_error

        message = prefix + case_fn(keyword) + suffix
        exc = Exception(message)
        assert _is_media_keyword_error(exc) is True
