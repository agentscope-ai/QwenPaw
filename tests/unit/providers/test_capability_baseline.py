# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ExpectedCapabilityRegistry."""

from copaw.providers.capability_baseline import (
    ExpectedCapability,
    ExpectedCapabilityRegistry,
    compare_probe_result,
    generate_summary,
)


class TestExpectedCapabilityRegistry:
    """Tests for the ExpectedCapabilityRegistry class."""

    def _make_registry_with_data(self) -> ExpectedCapabilityRegistry:
        """Create a registry and manually register some test data."""
        registry = ExpectedCapabilityRegistry()
        registry._register(
            ExpectedCapability(
                provider_id="openai",
                model_id="gpt-4o",
                expected_image=True,
                expected_video=False,
                doc_url="https://platform.openai.com/docs",
            ),
        )
        registry._register(
            ExpectedCapability(
                provider_id="openai",
                model_id="gpt-4o-mini",
                expected_image=True,
                expected_video=False,
                doc_url="https://platform.openai.com/docs",
            ),
        )
        registry._register(
            ExpectedCapability(
                provider_id="gemini",
                model_id="gemini-2.0-flash",
                expected_image=True,
                expected_video=True,
                doc_url="https://ai.google.dev/docs",
            ),
        )
        return registry

    def test_get_expected_returns_matching_capability(self) -> None:
        registry = self._make_registry_with_data()
        result = registry.get_expected("openai", "gpt-4o")
        assert result is not None
        assert result.provider_id == "openai"
        assert result.model_id == "gpt-4o"
        assert result.expected_image is True
        assert result.expected_video is False

    def test_get_expected_returns_none_for_unknown_model(self) -> None:
        registry = self._make_registry_with_data()
        result = registry.get_expected("openai", "nonexistent-model")
        assert result is None

    def test_get_expected_returns_none_for_unknown_provider(self) -> None:
        registry = self._make_registry_with_data()
        result = registry.get_expected("unknown-provider", "gpt-4o")
        assert result is None

    def test_get_all_for_provider_returns_all_models(self) -> None:
        registry = self._make_registry_with_data()
        results = registry.get_all_for_provider("openai")
        model_ids = {r.model_id for r in results}
        # Baseline already includes openai models; our manual registrations
        # should be present (possibly overwriting baseline entries).
        assert "gpt-4o" in model_ids
        assert "gpt-4o-mini" in model_ids

    def test_get_all_for_provider_returns_empty_for_unknown(self) -> None:
        registry = self._make_registry_with_data()
        results = registry.get_all_for_provider("unknown-provider")
        assert results == []

    def test_registry_returns_none_for_unregistered_model(self) -> None:
        registry = ExpectedCapabilityRegistry()
        assert (
            registry.get_expected("openai", "totally-fake-model-xyz") is None
        )

    def test_registry_returns_empty_for_unregistered_provider(self) -> None:
        registry = ExpectedCapabilityRegistry()
        assert registry.get_all_for_provider("nonexistent-provider-xyz") == []

    def test_register_overwrites_existing_entry(self) -> None:
        registry = ExpectedCapabilityRegistry()
        cap1 = ExpectedCapability(
            provider_id="openai",
            model_id="gpt-4o",
            expected_image=True,
            expected_video=False,
        )
        cap2 = ExpectedCapability(
            provider_id="openai",
            model_id="gpt-4o",
            expected_image=True,
            expected_video=True,
            note="updated",
        )
        registry._register(cap1)
        registry._register(cap2)
        result = registry.get_expected("openai", "gpt-4o")
        assert result is not None
        assert result.expected_video is True
        assert result.note == "updated"


class TestCompareProbeResult:
    """Tests for compare_probe_result function."""

    def _cap(
        self,
        expected_image: bool | None = None,
        expected_video: bool | None = None,
    ) -> ExpectedCapability:
        return ExpectedCapability(
            provider_id="test",
            model_id="model-1",
            expected_image=expected_image,
            expected_video=expected_video,
        )

    def test_no_discrepancy_when_all_match(self) -> None:
        logs = compare_probe_result(self._cap(True, False), True, False)
        assert not logs

    def test_skip_none_expected_image(self) -> None:
        logs = compare_probe_result(self._cap(None, False), True, False)
        assert not logs

    def test_skip_none_expected_video(self) -> None:
        logs = compare_probe_result(self._cap(True, None), True, True)
        assert not logs

    def test_skip_both_none(self) -> None:
        logs = compare_probe_result(self._cap(None, None), True, True)
        assert not logs

    def test_false_negative_image(self) -> None:
        logs = compare_probe_result(self._cap(True, False), False, False)
        assert len(logs) == 1
        assert logs[0].field == "image"
        assert logs[0].discrepancy_type == "false_negative"
        assert logs[0].expected is True
        assert logs[0].actual is False

    def test_false_positive_image(self) -> None:
        logs = compare_probe_result(self._cap(False, False), True, False)
        assert len(logs) == 1
        assert logs[0].field == "image"
        assert logs[0].discrepancy_type == "false_positive"
        assert logs[0].expected is False
        assert logs[0].actual is True

    def test_false_negative_video(self) -> None:
        logs = compare_probe_result(self._cap(True, True), True, False)
        assert len(logs) == 1
        assert logs[0].field == "video"
        assert logs[0].discrepancy_type == "false_negative"

    def test_false_positive_video(self) -> None:
        logs = compare_probe_result(self._cap(True, False), True, True)
        assert len(logs) == 1
        assert logs[0].field == "video"
        assert logs[0].discrepancy_type == "false_positive"

    def test_both_fields_discrepant(self) -> None:
        logs = compare_probe_result(self._cap(True, True), False, False)
        assert len(logs) == 2
        fields = {log.field for log in logs}
        assert fields == {"image", "video"}

    def test_discrepancy_carries_provider_and_model(self) -> None:
        cap = ExpectedCapability(
            provider_id="openai",
            model_id="gpt-4o",
            expected_image=True,
            expected_video=False,
        )
        logs = compare_probe_result(cap, False, False)
        assert logs[0].provider_id == "openai"
        assert logs[0].model_id == "gpt-4o"


class TestGenerateSummary:
    """Tests for generate_summary function."""

    def _cap(self, pid: str = "p", mid: str = "m") -> ExpectedCapability:
        return ExpectedCapability(
            provider_id=pid,
            model_id=mid,
            expected_image=True,
            expected_video=False,
        )

    def test_empty_results(self) -> None:
        summary = generate_summary([])
        assert summary.total_models == 0
        assert summary.passed == 0
        assert summary.discrepancies == 0
        assert summary.failures == 0
        assert not summary.details

    def test_all_ok(self) -> None:
        results = [
            (self._cap("a", "1"), True, False, "ok"),
            (self._cap("b", "2"), True, False, "ok"),
        ]
        summary = generate_summary(results)
        assert summary.total_models == 2
        assert summary.passed == 2
        assert summary.discrepancies == 0
        assert summary.failures == 0

    def test_all_failures(self) -> None:
        results = [
            (self._cap(), True, False, "failure"),
            (self._cap(), True, False, "failure"),
        ]
        summary = generate_summary(results)
        assert summary.total_models == 2
        assert summary.failures == 2
        assert summary.passed == 0

    def test_mixed_statuses(self) -> None:
        results = [
            (self._cap("a", "1"), True, False, "ok"),
            (self._cap("b", "2"), False, False, "discrepancy"),
            (self._cap("c", "3"), True, False, "failure"),
        ]
        summary = generate_summary(results)
        assert summary.total_models == 3
        assert summary.passed == 1
        assert summary.discrepancies == 1
        assert summary.failures == 1

    def test_total_equals_sum(self) -> None:
        results = [
            (self._cap("a", "1"), True, False, "ok"),
            (self._cap("b", "2"), False, True, "discrepancy"),
            (self._cap("c", "3"), True, False, "failure"),
            (self._cap("d", "4"), True, False, "ok"),
        ]
        summary = generate_summary(results)
        assert (
            summary.total_models
            == summary.passed + summary.discrepancies + summary.failures
        )

    def test_details_populated_for_discrepancies(self) -> None:
        cap = ExpectedCapability(
            provider_id="openai",
            model_id="gpt-4o",
            expected_image=True,
            expected_video=True,
        )
        results = [(cap, False, False, "discrepancy")]
        summary = generate_summary(results)
        assert summary.discrepancies == 1
        assert len(summary.details) == 2  # both image and video mismatch

    def test_details_empty_for_ok_and_failure(self) -> None:
        results = [
            (self._cap(), True, False, "ok"),
            (self._cap(), True, False, "failure"),
        ]
        summary = generate_summary(results)
        assert not summary.details
