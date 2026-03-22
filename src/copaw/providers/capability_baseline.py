# -*- coding: utf-8 -*-
"""Capability baseline — expected multimodal capabilities and discrepancy
reporting for all built-in providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProbeSource(str, Enum):
    """探测结果来源"""

    DOCUMENTATION = "documentation"  # 基于官方文档的默认标注
    PROBED = "probed"  # 基于实际 API 探测的结果
    UNKNOWN = "unknown"  # 未知/未探测


@dataclass
class ExpectedCapability:
    """基于官方文档的模型预期多模态能力"""

    provider_id: str
    model_id: str
    expected_image: bool | None  # None = 文档未明确说明
    expected_video: bool | None
    doc_url: str = ""
    note: str = ""


@dataclass
class DiscrepancyLog:
    """探测结果与预期不一致的差异记录"""

    provider_id: str
    model_id: str
    field: str  # "image" 或 "video"
    expected: bool | None
    actual: bool
    discrepancy_type: str  # "false_negative" 或 "false_positive"


@dataclass
class ComparisonSummary:
    """对比汇总报告"""

    total_models: int
    passed: int
    discrepancies: int
    failures: int
    details: list[DiscrepancyLog] = field(default_factory=list)


class ExpectedCapabilityRegistry:
    """管理所有渠道模型的预期多模态能力基线数据。

    内部使用 ``{(provider_id, model_id): ExpectedCapability}`` 字典存储。
    基线数据将在后续任务中填充。
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], ExpectedCapability] = {}
        self._load_baseline()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_expected(
        self, provider_id: str, model_id: str
    ) -> ExpectedCapability | None:
        """查询某个模型的预期能力，未找到时返回 None。"""
        return self._data.get((provider_id, model_id))

    def get_all_for_provider(self, provider_id: str) -> list[ExpectedCapability]:
        """获取某个渠道下所有模型的预期能力列表。"""
        return [
            cap for (pid, _), cap in self._data.items() if pid == provider_id
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register(self, cap: ExpectedCapability) -> None:
        """注册一条基线记录。"""
        self._data[(cap.provider_id, cap.model_id)] = cap

    def _load_baseline(self) -> None:
        """加载全部 16 个内置渠道的预定义模型基线数据。"""

        # ---------------------------------------------------------------
        # 1. ModelScope
        #    https://modelscope.cn/docs/model-service/API-Inference/intro
        # ---------------------------------------------------------------
        _ms_doc = (
            "https://modelscope.cn/docs/model-service/API-Inference/intro"
        )
        self._register(ExpectedCapability(
            provider_id="modelscope",
            model_id="Qwen/Qwen3.5-122B-A10B",
            expected_image=None,
            expected_video=None,
            doc_url=_ms_doc,
            note="ModelScope API Inference 文档未明确说明该模型的多模态能力",
        ))
        self._register(ExpectedCapability(
            provider_id="modelscope",
            model_id="ZhipuAI/GLM-5",
            expected_image=None,
            expected_video=None,
            doc_url=_ms_doc,
            note="ModelScope API Inference 文档未明确说明该模型的多模态能力",
        ))

        # ---------------------------------------------------------------
        # 2. DashScope
        #    https://help.aliyun.com/zh/model-studio/getting-started/models
        # ---------------------------------------------------------------
        _ds_doc = (
            "https://help.aliyun.com/zh/model-studio/getting-started/models"
        )
        self._register(ExpectedCapability(
            provider_id="dashscope",
            model_id="qwen3-max",
            expected_image=False,
            expected_video=False,
            doc_url=_ds_doc,
            note="Qwen3 系列为纯文本模型",
        ))
        self._register(ExpectedCapability(
            provider_id="dashscope",
            model_id="qwen3-235b-a22b-thinking-2507",
            expected_image=False,
            expected_video=False,
            doc_url=_ds_doc,
            note="Qwen3 系列为纯文本模型",
        ))
        self._register(ExpectedCapability(
            provider_id="dashscope",
            model_id="deepseek-v3.2",
            expected_image=False,
            expected_video=False,
            doc_url=_ds_doc,
            note="DeepSeek V3 系列为纯文本模型",
        ))

        # ---------------------------------------------------------------
        # 3. Aliyun Coding Plan
        #    https://help.aliyun.com/zh/model-studio/developer-reference/compatibility-of-openai-with-dashscope
        # ---------------------------------------------------------------
        _acp_doc = (
            "https://help.aliyun.com/zh/model-studio/developer-reference/"
            "compatibility-of-openai-with-dashscope"
        )
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="qwen3.5-plus",
            expected_image=None,
            expected_video=None,
            doc_url=_acp_doc,
            note="Aliyun Coding Plan 文档未明确说明该模型的多模态能力",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="glm-5",
            expected_image=None,
            expected_video=None,
            doc_url=_acp_doc,
            note="Aliyun Coding Plan 文档未明确说明该模型的多模态能力",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="glm-4.7",
            expected_image=None,
            expected_video=None,
            doc_url=_acp_doc,
            note="Aliyun Coding Plan 文档未明确说明该模型的多模态能力",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="MiniMax-M2.5",
            expected_image=None,
            expected_video=None,
            doc_url=_acp_doc,
            note="Aliyun Coding Plan 文档未明确说明该模型的多模态能力",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="kimi-k2.5",
            expected_image=None,
            expected_video=None,
            doc_url=_acp_doc,
            note="Aliyun Coding Plan 文档未明确说明该模型的多模态能力",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="qwen3-max-2026-01-23",
            expected_image=False,
            expected_video=False,
            doc_url=_acp_doc,
            note="Qwen3 系列为纯文本模型",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="qwen3-coder-next",
            expected_image=False,
            expected_video=False,
            doc_url=_acp_doc,
            note="Qwen3 Coder 系列为代码专用纯文本模型",
        ))
        self._register(ExpectedCapability(
            provider_id="aliyun-codingplan",
            model_id="qwen3-coder-plus",
            expected_image=False,
            expected_video=False,
            doc_url=_acp_doc,
            note="Qwen3 Coder 系列为代码专用纯文本模型",
        ))

        # ---------------------------------------------------------------
        # 4. OpenAI
        #    https://platform.openai.com/docs/models
        # ---------------------------------------------------------------
        _oai_doc = "https://platform.openai.com/docs/models"
        for mid in (
            "gpt-5.2", "gpt-5", "gpt-5-mini", "gpt-5-nano",
            "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
            "o3", "o4-mini",
            "gpt-4o", "gpt-4o-mini",
        ):
            self._register(ExpectedCapability(
                provider_id="openai",
                model_id=mid,
                expected_image=True,
                expected_video=False,
                doc_url=_oai_doc,
            ))

        # ---------------------------------------------------------------
        # 5. Azure OpenAI
        #    https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models
        # ---------------------------------------------------------------
        _az_doc = (
            "https://learn.microsoft.com/en-us/azure/ai-services/"
            "openai/concepts/models"
        )
        for mid in (
            "gpt-5-chat", "gpt-5-mini", "gpt-5-nano",
            "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
            "gpt-4o", "gpt-4o-mini",
        ):
            self._register(ExpectedCapability(
                provider_id="azure-openai",
                model_id=mid,
                expected_image=True,
                expected_video=False,
                doc_url=_az_doc,
            ))

        # ---------------------------------------------------------------
        # 6. Kimi (China)
        #    https://platform.moonshot.cn/docs/intro
        # ---------------------------------------------------------------
        _kimi_doc = "https://platform.moonshot.cn/docs/intro"
        for mid in (
            "kimi-k2.5",
            "kimi-k2-0905-preview",
            "kimi-k2-0711-preview",
            "kimi-k2-turbo-preview",
            "kimi-k2-thinking",
            "kimi-k2-thinking-turbo",
        ):
            self._register(ExpectedCapability(
                provider_id="kimi-cn",
                model_id=mid,
                expected_image=True,
                expected_video=False,
                doc_url=_kimi_doc,
            ))

        # ---------------------------------------------------------------
        # 7. Kimi (International)
        #    https://platform.moonshot.ai/docs/intro
        # ---------------------------------------------------------------
        _kimi_intl_doc = "https://platform.moonshot.ai/docs/intro"
        for mid in (
            "kimi-k2.5",
            "kimi-k2-0905-preview",
            "kimi-k2-0711-preview",
            "kimi-k2-turbo-preview",
            "kimi-k2-thinking",
            "kimi-k2-thinking-turbo",
        ):
            self._register(ExpectedCapability(
                provider_id="kimi-intl",
                model_id=mid,
                expected_image=True,
                expected_video=False,
                doc_url=_kimi_intl_doc,
            ))

        # ---------------------------------------------------------------
        # 8. DeepSeek
        #    https://api-docs.deepseek.com/
        # ---------------------------------------------------------------
        _ds_api_doc = "https://api-docs.deepseek.com/"
        self._register(ExpectedCapability(
            provider_id="deepseek",
            model_id="deepseek-chat",
            expected_image=True,
            expected_video=False,
            doc_url=_ds_api_doc,
            note="DeepSeek-V3 支持图片输入",
        ))
        self._register(ExpectedCapability(
            provider_id="deepseek",
            model_id="deepseek-reasoner",
            expected_image=False,
            expected_video=False,
            doc_url=_ds_api_doc,
            note="DeepSeek-R1 推理模型不支持多模态输入",
        ))

        # ---------------------------------------------------------------
        # 9. Anthropic
        #    https://docs.anthropic.com/en/docs/build-with-claude/vision
        #    注意：ANTHROPIC_MODELS 为空列表，无预定义模型
        # ---------------------------------------------------------------
        # Anthropic 渠道无预定义模型，无需注册基线数据

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
            self._register(ExpectedCapability(
                provider_id="gemini",
                model_id=mid,
                expected_image=True,
                expected_video=True,
                doc_url=_gem_doc,
            ))

        # ---------------------------------------------------------------
        # 11. MiniMax (International)
        #     https://www.minimax.io/platform/document/announcement
        # ---------------------------------------------------------------
        _mm_doc = (
            "https://www.minimax.io/platform/document/announcement"
        )
        for mid in (
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
        ):
            self._register(ExpectedCapability(
                provider_id="minimax",
                model_id=mid,
                expected_image=True,
                expected_video=False,
                doc_url=_mm_doc,
            ))

        # ---------------------------------------------------------------
        # 12. MiniMax (China)
        #     https://platform.minimaxi.com/document/announcement
        # ---------------------------------------------------------------
        _mm_cn_doc = (
            "https://platform.minimaxi.com/document/announcement"
        )
        for mid in (
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
        ):
            self._register(ExpectedCapability(
                provider_id="minimax-cn",
                model_id=mid,
                expected_image=True,
                expected_video=False,
                doc_url=_mm_cn_doc,
            ))

        # ---------------------------------------------------------------
        # 13. Ollama
        #     https://github.com/ollama/ollama/blob/main/docs/api.md
        #     Ollama 无预定义模型（动态发现），无需注册基线数据
        # ---------------------------------------------------------------

        # ---------------------------------------------------------------
        # 14. LM Studio
        #     https://lmstudio.ai/docs
        #     LM Studio 无预定义模型（动态发现），无需注册基线数据
        # ---------------------------------------------------------------

        # ---------------------------------------------------------------
        # 15. llama.cpp (Local)
        #     https://github.com/ggml-org/llama.cpp/blob/master/docs/server.md
        #     llamacpp 模型列表由本地扫描动态生成，无预定义模型
        # ---------------------------------------------------------------

        # ---------------------------------------------------------------
        # 16. MLX (Local, Apple Silicon)
        #     https://github.com/ml-explore/mlx-lm
        #     mlx 模型列表由本地扫描动态生成，无预定义模型
        # ---------------------------------------------------------------


def compare_probe_result(
    expected: ExpectedCapability,
    actual_image: bool,
    actual_video: bool,
) -> list[DiscrepancyLog]:
    """对比单个模型的探测结果与预期，返回差异列表。

    当 expected 的 expected_image / expected_video 为 None 时跳过该字段对比。
    当 expected != actual 时生成 DiscrepancyLog，区分:
      - false_negative: expected=True, actual=False（漏检）
      - false_positive: expected=False, actual=True（误检）
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
            )
        )

    return logs


def generate_summary(
    results: list[tuple[ExpectedCapability, bool, bool, str]],
) -> ComparisonSummary:
    """生成对比汇总报告。

    results 中每个元素为 (expected_cap, actual_image, actual_video, status)，
    其中 status 为 "ok"、"discrepancy" 或 "failure"。

    返回的 ComparisonSummary 保证 total_models == passed + discrepancies + failures，
    且 details 仅包含 status=="discrepancy" 条目产生的 DiscrepancyLog。
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
                compare_probe_result(expected_cap, actual_image, actual_video)
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
