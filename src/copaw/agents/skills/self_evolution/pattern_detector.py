# -*- coding: utf-8 -*-
"""
Pattern Detector - 模式检测模块

自动分析 recurring（重复出现）的错误模式，找出根本原因。
"""
from typing import List, Dict, Any
from collections import Counter
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """错误模式"""

    category: str
    count: int
    frequency: float
    related_errors: List[str]
    root_cause: str = ""
    suggestion: str = ""


class PatternDetector:
    """模式检测器"""

    def __init__(self):
        self.patterns: List[Pattern] = []

    def detect(self, error_records: List[Dict[str, Any]] = None) -> List[Pattern]:
        """
        检测错误模式

        Args:
            error_records: 错误记录列表，如果为 None 则从存储中读取

        Returns:
            检测到的模式列表
        """
        if not error_records:
            error_records = self._load_errors()

        if not error_records:
            logger.info("No errors to analyze")
            return []

        # 按错误类别分组
        categories = [e.get("category", "unknown") for e in error_records]
        category_counts = Counter(categories)

        # 检测重复模式
        self.patterns = []
        for category, count in category_counts.items():
            if count >= 2:  # 至少出现 2 次
                pattern = Pattern(
                    category=category,
                    count=count,
                    frequency=count / len(error_records),
                    related_errors=self._get_related_errors(error_records, category),
                    root_cause=self._infer_root_cause(category),
                    suggestion=self._get_suggestion(category),
                )
                self.patterns.append(pattern)

        # 按出现频率排序
        self.patterns.sort(key=lambda p: p.frequency, reverse=True)

        logger.info(f"Detected {len(self.patterns)} patterns")
        return self.patterns

    def _load_errors(self) -> List[Dict[str, Any]]:
        """从存储加载错误记录"""
        # TODO: 从数据库或文件加载错误记录
        return []

    def _get_related_errors(
        self, error_records: List[Dict[str, Any]], category: str
    ) -> List[str]:
        """获取同类错误的消息列表"""
        return [
            e.get("error_message", "")[:100]
            for e in error_records
            if e.get("category") == category
        ]

    def _infer_root_cause(self, category: str) -> str:
        """推断根本原因"""
        root_causes = {
            "file_error": "文件路径管理不规范，缺少存在性检查",
            "permission_error": "权限配置不当或操作超出权限范围",
            "import_error": "依赖管理不规范，缺少依赖检查",
            "database_error": "数据库操作缺乏事务管理和连接池",
            "key_error": "数据结构使用不当，缺少防御性编程",
            "type_error": "类型检查不足，参数校验不严",
            "value_error": "业务逻辑校验不足",
            "timeout_error": "网络不稳定或超时配置不合理",
            "network_error": "网络连接管理不当",
            "parse_error": "数据格式校验不严格",
            "encoding_error": "字符编码处理不规范",
        }
        return root_causes.get(category, "需要进一步分析")

    def _get_suggestion(self, category: str) -> str:
        """获取改进建议"""
        suggestions = {
            "file_error": "添加文件存在性检查，使用 os.path.exists()",
            "permission_error": "使用 try-except 包装权限相关操作",
            "import_error": "在 AGENTS.md 中添加依赖检查规则",
            "database_error": "添加连接重试机制，使用事务管理",
            "key_error": "使用 dict.get() 或 setdefault() 方法",
            "type_error": "添加类型注解和运行时类型检查",
            "value_error": "在函数入口添加参数校验",
            "timeout_error": "增加超时时间，添加重试机制",
            "network_error": "添加网络状态检查和重连逻辑",
            "parse_error": "使用 try-except 包裹解析代码",
            "encoding_error": "明确指定文件编码，使用 utf-8",
        }
        return suggestions.get(category, "建议添加防御性编程")


def detect_patterns(error_records: List[Dict[str, Any]] = None) -> List[Pattern]:
    """便捷函数：检测错误模式"""
    detector = PatternDetector()
    return detector.detect(error_records)