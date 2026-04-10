# -*- coding: utf-8 -*-
"""
AI Attributor - AI 归因分析模块

使用 5-Why 分析法，AI 自动归因错误的根本原因。
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class AttributionResult:
    """归因结果"""

    error_type: str
    error_message: str
    root_cause: str
    why_1: str = ""
    why_2: str = ""
    why_3: str = ""
    why_4: str = ""
    why_5: str = ""
    confidence: float = 0.0
    related_rule: str = ""
    suggestion: str = ""


class AIAttributor:
    """AI 归因分析器"""

    def __init__(self):
        self.results: list[AttributionResult] = []

    def attribute(
        self,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None,
    ) -> AttributionResult:
        """
        对错误进行归因分析

        使用 5-Why 分析法，找出根本原因

        Args:
            error_type: 错误类型
            error_message: 错误消息
            traceback: 调用栈（可选）

        Returns:
            归因结果
        """
        # 使用规则匹配 + 简单推理
        result = self._rule_based_attribution(error_type, error_message, traceback)

        self.results.append(result)
        logger.info(f"Attributed error: {error_type} -> {result.root_cause}")

        return result

    def _rule_based_attribution(
        self,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None,
    ) -> AttributionResult:
        """基于规则的归因"""

        # 5-Why 分析模板
        templates = {
            "FileNotFoundError": AttributionResult(
                error_type=error_type,
                error_message=error_message,
                root_cause="文件路径管理不规范",
                why_1="文件不存在",
                why_2="路径错误或文件被删除",
                why_3="缺少路径验证逻辑",
                why_4="没有使用 os.path.exists() 检查",
                why_5="开发时未考虑文件缺失场景",
                confidence=0.85,
                related_rule="读取文件前必须检查存在性",
                suggestion="在读取文件前使用 os.path.exists() 检查",
            ),
            "PermissionError": AttributionResult(
                error_type=error_type,
                error_message=error_message,
                root_cause="权限管理不当",
                why_1="没有操作权限",
                why_2="文件/目录权限不足",
                why_3="未处理权限异常",
                why_4="缺少权限检查逻辑",
                why_5="开发环境与运行环境权限不一致",
                confidence=0.80,
                related_rule="敏感操作需要权限检查",
                suggestion="使用 try-except 包裹权限相关操作",
            ),
            "KeyError": AttributionResult(
                error_type=error_type,
                error_message=error_message,
                root_cause="字典键访问不规范",
                why_1="访问不存在的键",
                why_2="数据结构不符合预期",
                why_3="缺少键存在性检查",
                why_4="未使用 dict.get() 方法",
                why_5="未考虑数据边界情况",
                confidence=0.90,
                related_rule="访问字典前检查键存在性",
                suggestion="使用 dict.get() 或 in 操作符",
            ),
            "TimeoutError": AttributionResult(
                error_type=error_type,
                error_message=error_message,
                root_cause="超时配置不当",
                why_1="操作超时",
                why_2="网络延迟或服务响应慢",
                why_3="超时时间设置过短",
                why_4="缺少超时保护",
                why_5="未考虑网络不稳定场景",
                confidence=0.75,
                related_rule="网络操作需要超时保护",
                suggestion="增加超时时间，添加重试机制",
            ),
        }

        # 返回匹配模板或默认模板
        if error_type in templates:
            result = templates[error_type]
            result.error_message = error_message
            return result

        # 默认归因
        return AttributionResult(
            error_type=error_type,
            error_message=error_message,
            root_cause="未知原因，需要进一步分析",
            why_1="发生错误",
            why_2="具体原因不明",
            why_3="缺少上下文信息",
            why_4="需要查看更多日志",
            why_5="建议添加更多错误追踪",
            confidence=0.50,
            related_rule="",
            suggestion="查看完整调用栈和日志",
        )

    def get_results(self) -> list[AttributionResult]:
        """获取所有归因结果"""
        return self.results


def attribute_error(
    error_type: str,
    error_message: str,
    traceback: Optional[str] = None,
) -> AttributionResult:
    """便捷函数：对错误进行归因"""
    attributor = AIAttributor()
    return attributor.attribute(error_type, error_message, traceback)