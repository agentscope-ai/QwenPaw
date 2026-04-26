# -*- coding: utf-8 -*-
"""Capability baseline — expected multimodal capabilities and discrepancy
reporting for all built-in providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProbeSource(str, Enum):
    """Source of probe result."""

    DOCUMENTATION = "documentation"  # Default annotation from official docs
    PROBED = "probed"  # Result from actual API probing
    UNKNOWN = "unknown"  # Unknown / not yet probed


@dataclass
class ExpectedCapability:
    """Expected multimodal capability of a model based on official docs."""

    provider_id: str
    model_id: str
    expected_image: bool | None  # None = not specified in docs
    expected_video: bool | None
    doc_url: str = ""
    note: str = ""


@dataclass
class DiscrepancyLog:
    """Record of a mismatch between probe result and expected capability."""

    provider_id: str
    model_id: str
    field: str  # "image" or "video"
    expected: bool | None
    actual: bool
    discrepancy_type: str  # "false_negative" or "false_positive"


@dataclass
class ComparisonSummary:
    """Summary report of probe vs. expected comparison."""

    total_models: int
    passed: int
    discrepancies: int
    failures: int
    details: list[DiscrepancyLog] = field(default_factory=list)


class ExpectedCapabilityRegistry:
    """Registry of expected multimodal capabilities
    for all built-in provider models.

    Internally stores
    ``{(provider_id, model_id): ExpectedCapability}`` dict.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], ExpectedCapability] = {}
        self._load_baseline()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_expected(
        self,
        provider_id: str,
        model_id: str,
    ) -> ExpectedCapability | None:
        """Look up expected capability for a model.

        Returns None if not found.
        """
        return self._data.get((provider_id, model_id))

    def get_all_for_provider(
        self,
        provider_id: str,
    ) -> list[ExpectedCapability]:
        """Get all expected capabilities for a given provider."""
        return [
            cap for (pid, _), cap in self._data.items() if pid == provider_id
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register(self, cap: ExpectedCapability) -> None:
        """Register a single baseline entry."""
        self._data[(cap.provider_id, cap.model_id)] = cap

    def _load_baseline(self) -> None:  # pylint: disable=too-many-statements
        """Load baseline data for built-in providers."""

        # ---------------------------------------------------------------
        # 1. ModelScope
        #    https://modelscope.cn/docs/model-service/API-Inference/intro
        # ---------------------------------------------------------------
        _ms_doc = (
            "https://modelscope.cn/docs/model-service/API-Inference/intro"
        )
        self._register(
            ExpectedCapability(
                provider_id="modelscope",
                model_id="Qwen/Qwen3.5-122B-A10B",
                expected_image=True,
                expected_video=True,
                doc_url=_ms_doc,
                note="Qwen3.5 is natively multimodal (image+video)",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="modelscope",
                model_id="ZhipuAI/GLM-5",
                expected_image=False,
                expected_video=False,
                doc_url=_ms_doc,
                note="GLM-5 is text/code model, no vision input",
            ),
        )

        # ---------------------------------------------------------------
        # 2. DashScope
        #    https://help.aliyun.com/zh/model-studio/getting-started/models
        # ---------------------------------------------------------------
        _ds_doc = (
            "https://help.aliyun.com/zh/model-studio/getting-started/models"
        )
        self._register(
            ExpectedCapability(
                provider_id="dashscope",
                model_id="qwen3-max",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_doc,
                note="Qwen3 series is text-only",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="dashscope",
                model_id="qwen3-235b-a22b-thinking-2507",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_doc,
                note="Qwen3 series is text-only",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="dashscope",
                model_id="deepseek-v3.2",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_doc,
                note="DeepSeek V3 series is text-only",
            ),
        )

        # ---------------------------------------------------------------
        # 3. Aliyun Coding Plan
        # ---------------------------------------------------------------
        _acp_doc = (
            "https://help.aliyun.com/zh/model-studio/developer-reference/"
            "compatibility-of-openai-with-dashscope"
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="qwen3.6-plus",
                expected_image=True,
                expected_video=True,
                doc_url=_acp_doc,
                note="Qwen3.6-Plus is natively multimodal (image+video)",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="qwen3.5-plus",
                expected_image=True,
                expected_video=True,
                doc_url=_acp_doc,
                note="Qwen3.5-Plus is natively multimodal (image+video)",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="glm-5",
                expected_image=False,
                expected_video=False,
                doc_url=_acp_doc,
                note="GLM-5 is text/code model, no vision input",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="glm-4.7",
                expected_image=False,
                expected_video=False,
                doc_url=_acp_doc,
                note="GLM-4.7 is text/code model, no vision input",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="MiniMax-M2.5",
                expected_image=False,
                expected_video=False,
                doc_url=_acp_doc,
                note="MiniMax models are text-only",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="kimi-k2.5",
                expected_image=True,
                expected_video=True,
                doc_url=_acp_doc,
                note="Kimi K2.5 supports image and video input",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="qwen3-max-2026-01-23",
                expected_image=False,
                expected_video=False,
                doc_url=_acp_doc,
                note="Qwen3 series is text-only",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="qwen3-coder-next",
                expected_image=False,
                expected_video=False,
                doc_url=_acp_doc,
                note="Qwen3 Coder series is code-only text model",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="aliyun-codingplan",
                model_id="qwen3-coder-plus",
                expected_image=False,
                expected_video=False,
                doc_url=_acp_doc,
                note="Qwen3 Coder series is code-only text model",
            ),
        )

        # ---------------------------------------------------------------
        # Zhipu (BigModel)
        # ---------------------------------------------------------------
        _zhipu_cn_doc = "https://docs.bigmodel.cn/"
        for mid in ("glm-5", "glm-5.1", "glm-5-turbo"):
            self._register(
                ExpectedCapability(
                    provider_id="zhipu-cn",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_zhipu_cn_doc,
                    note="GLM text/code models are text-only",
                ),
            )
        self._register(
            ExpectedCapability(
                provider_id="zhipu-cn",
                model_id="glm-5v-turbo",
                expected_image=True,
                expected_video=False,
                doc_url=_zhipu_cn_doc,
                note="GLM vision model supports image input",
            ),
        )

        # ---------------------------------------------------------------
        # Zhipu Coding Plan (BigModel)
        # ---------------------------------------------------------------
        _zhipu_cn_cp_doc = "https://docs.bigmodel.cn/cn/coding-plan"
        for mid in ("glm-5", "glm-5.1", "glm-5-turbo"):
            self._register(
                ExpectedCapability(
                    provider_id="zhipu-cn-codingplan",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_zhipu_cn_cp_doc,
                    note="GLM text/code models are text-only",
                ),
            )
        self._register(
            ExpectedCapability(
                provider_id="zhipu-cn-codingplan",
                model_id="glm-5v-turbo",
                expected_image=True,
                expected_video=False,
                doc_url=_zhipu_cn_cp_doc,
                note="GLM vision model supports image input",
            ),
        )

        # ---------------------------------------------------------------
        # Zhipu (Z.AI)
        # ---------------------------------------------------------------
        _zhipu_intl_doc = "https://docs.z.ai/"
        for mid in ("glm-5", "glm-5.1", "glm-5-turbo"):
            self._register(
                ExpectedCapability(
                    provider_id="zhipu-intl",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_zhipu_intl_doc,
                    note="GLM text/code models are text-only",
                ),
            )
        self._register(
            ExpectedCapability(
                provider_id="zhipu-intl",
                model_id="glm-5v-turbo",
                expected_image=True,
                expected_video=False,
                doc_url=_zhipu_intl_doc,
                note="GLM vision model supports image input",
            ),
        )

        # ---------------------------------------------------------------
        # Zhipu Coding Plan (Z.AI)
        # ---------------------------------------------------------------
        _zhipu_intl_cp_doc = "https://docs.z.ai/coding-plan"
        for mid in ("glm-5", "glm-5.1", "glm-5-turbo"):
            self._register(
                ExpectedCapability(
                    provider_id="zhipu-intl-codingplan",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_zhipu_intl_cp_doc,
                    note="GLM text/code models are text-only",
                ),
            )
        self._register(
            ExpectedCapability(
                provider_id="zhipu-intl-codingplan",
                model_id="glm-5v-turbo",
                expected_image=True,
                expected_video=False,
                doc_url=_zhipu_intl_cp_doc,
                note="GLM vision model supports image input",
            ),
        )

        # ---------------------------------------------------------------
        # 4. OpenAI
        #    https://platform.openai.com/docs/models
        # ---------------------------------------------------------------
        _oai_doc = "https://platform.openai.com/docs/models"
        for mid in (
            "gpt-5.2",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "o4-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="openai",
                    model_id=mid,
                    expected_image=True,
                    expected_video=True,
                    doc_url=_oai_doc,
                ),
            )
        self._register(
            ExpectedCapability(
                provider_id="openai",
                model_id="o3",
                expected_image=True,
                expected_video=False,
                doc_url=_oai_doc,
                note="o3 supports image but not video",
            ),
        )

        # ---------------------------------------------------------------
        # 5. Azure OpenAI
        # ---------------------------------------------------------------
        _az_doc = (
            "https://learn.microsoft.com/en-us/azure/ai-services/"
            "openai/concepts/models"
        )
        for mid in (
            "gpt-5-chat",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="azure-openai",
                    model_id=mid,
                    expected_image=True,
                    expected_video=True,
                    doc_url=_az_doc,
                ),
            )

        # ---------------------------------------------------------------
        # 6. Kimi (China)
        #    https://platform.moonshot.cn/docs/intro
        # ---------------------------------------------------------------
        _kimi_doc = "https://platform.moonshot.cn/docs/intro"
        self._register(
            ExpectedCapability(
                provider_id="kimi-cn",
                model_id="kimi-k2.5",
                expected_image=True,
                expected_video=True,
                doc_url=_kimi_doc,
                note="Kimi K2.5 supports image and video input",
            ),
        )
        for mid in (
            "kimi-k2-0905-preview",
            "kimi-k2-0711-preview",
            "kimi-k2-turbo-preview",
            "kimi-k2-thinking",
            "kimi-k2-thinking-turbo",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="kimi-cn",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_kimi_doc,
                    note="K2 series (non-K2.5) is text-only",
                ),
            )

        # ---------------------------------------------------------------
        # 7. Kimi (International)
        #    https://platform.moonshot.ai/docs/intro
        # ---------------------------------------------------------------
        _kimi_intl_doc = "https://platform.moonshot.ai/docs/intro"
        self._register(
            ExpectedCapability(
                provider_id="kimi-intl",
                model_id="kimi-k2.5",
                expected_image=True,
                expected_video=True,
                doc_url=_kimi_intl_doc,
                note="Kimi K2.5 supports image and video input",
            ),
        )
        for mid in (
            "kimi-k2-0905-preview",
            "kimi-k2-0711-preview",
            "kimi-k2-turbo-preview",
            "kimi-k2-thinking",
            "kimi-k2-thinking-turbo",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="kimi-intl",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_kimi_intl_doc,
                    note="K2 series (non-K2.5) is text-only",
                ),
            )

        # ---------------------------------------------------------------
        # 8. DeepSeek
        #    https://api-docs.deepseek.com/
        # ---------------------------------------------------------------
        _ds_api_doc = "https://api-docs.deepseek.com/"
        self._register(
            ExpectedCapability(
                provider_id="deepseek",
                model_id="deepseek-chat",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_api_doc,
                note="DeepSeek-V3 is text-only",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="deepseek",
                model_id="deepseek-reasoner",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_api_doc,
                note="DeepSeek-R1 reasoning model: no multimodal",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="deepseek",
                model_id="deepseek-v4-flash",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_api_doc,
                note="DeepSeek-V4 Flash: text-only",
            ),
        )
        self._register(
            ExpectedCapability(
                provider_id="deepseek",
                model_id="deepseek-v4-pro",
                expected_image=False,
                expected_video=False,
                doc_url=_ds_api_doc,
                note="DeepSeek-V4 Pro reasoning model: no multimodal",
            ),
        )

        # ---------------------------------------------------------------
        # 9. Anthropic
        #    No predefined models (ANTHROPIC_MODELS is empty)
        # ---------------------------------------------------------------

        # ---------------------------------------------------------------
        # 10. Gemini
        #     https://ai.google.dev/gemini-api/docs/models
        # ---------------------------------------------------------------
        _gem_doc = "https://ai.google.dev/gemini-api/docs/models"
        for mid in (
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="gemini",
                    model_id=mid,
                    expected_image=True,
                    expected_video=True,
                    doc_url=_gem_doc,
                ),
            )

        # ---------------------------------------------------------------
        # 11. MiniMax (International)
        # ---------------------------------------------------------------
        _mm_doc = "https://www.minimax.io/platform/document/announcement"
        for mid in (
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="minimax",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_mm_doc,
                    note="MiniMax models are text-only",
                ),
            )

        # ---------------------------------------------------------------
        # 12. MiniMax (China)
        # ---------------------------------------------------------------
        _mm_cn_doc = "https://platform.minimaxi.com/document/announcement"
        for mid in (
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="minimax-cn",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_mm_cn_doc,
                    note="MiniMax models are text-only",
                ),
            )
        # ---------------------------------------------------------------
        # 13. OpenCode (OpenCode Zen)
        #     https://opencode.ai/docs/zen
        # ---------------------------------------------------------------
        _oc_doc = "https://opencode.ai/docs/zen"
        for mid in (
            "big-pickle",
            "nemotron-3-super-free",
        ):
            self._register(
                ExpectedCapability(
                    provider_id="opencode",
                    model_id=mid,
                    expected_image=False,
                    expected_video=False,
                    doc_url=_oc_doc,
                    note=(
                        "OpenCode Zen aggregates heterogeneous providers; "
                        "capability varies by model, probe to determine."
                    ),
                ),
            )
        # ---------------------------------------------------------------
        # 14. Ollama — no predefined models (dynamic discovery)
        # ---------------------------------------------------------------

        # ---------------------------------------------------------------
        # 15. LM Studio — no predefined models (dynamic discovery)
        # ---------------------------------------------------------------


def compare_probe_result(
    expected: ExpectedCapability,
    actual_image: bool,
    actual_video: bool,
) -> list[DiscrepancyLog]:
    """Compare a single model's probe result against expected capability.

    Skips comparison when expected_image/expected_video is None.
    When expected != actual, generates a DiscrepancyLog with type:
      - false_negative: expected=True, actual=False (missed detection)
      - false_positive: expected=False, actual=True (wrong detection)
    """
    logs: list[DiscrepancyLog] = []

    for field_name, expected_val, actual_val in [
        ("image", expected.expected_image, actual_image),
        ("video", expected.expected_video, actual_video),
    ]:
        if expected_val is None:
            continue
        if expected_val == actual_val:
            continue
        discrepancy_type = (
            "false_negative" if expected_val is True else "false_positive"
        )
        logs.append(
            DiscrepancyLog(
                provider_id=expected.provider_id,
                model_id=expected.model_id,
                field=field_name,
                expected=expected_val,
                actual=actual_val,
                discrepancy_type=discrepancy_type,
            ),
        )

    return logs


def generate_summary(
    results: list[tuple[ExpectedCapability, bool, bool, str]],
) -> ComparisonSummary:
    """Generate a comparison summary report.

    Each element in results is
    (expected_cap, actual_image, actual_video, status),
    where status is "ok", "discrepancy", or "failure".

    The returned ComparisonSummary guarantees
    total_models == passed + discrepancies + failures,
    and details only contains DiscrepancyLog entries from "discrepancy" items.
    """
    passed = 0
    discrepancies = 0
    failures = 0
    details: list[DiscrepancyLog] = []

    for expected_cap, actual_image, actual_video, status in results:
        if status == "ok":
            passed += 1
        elif status == "discrepancy":
            discrepancies += 1
            details.extend(
                compare_probe_result(expected_cap, actual_image, actual_video),
            )
        elif status == "failure":
            failures += 1

    return ComparisonSummary(
        total_models=len(results),
        passed=passed,
        discrepancies=discrepancies,
        failures=failures,
        details=details,
    )
