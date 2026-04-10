# -*- coding: utf-8 -*-
"""
Error Catcher - 自动错误捕获模块
"""
import functools
import traceback
import json
from typing import Callable, Any, Optional, Dict
from datetime import datetime
from dataclasses import dataclass, asdict, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """错误分类"""

    FILE_ERROR = "file_error"
    PERMISSION_ERROR = "permission_error"
    IMPORT_ERROR = "import_error"
    DATABASE_ERROR = "database_error"
    KEY_ERROR = "key_error"
    TYPE_ERROR = "type_error"
    VALUE_ERROR = "value_error"
    TIMEOUT_ERROR = "timeout_error"
    NETWORK_ERROR = "network_error"
    PARSE_ERROR = "parse_error"
    ENCODING_ERROR = "encoding_error"
    UNKNOWN = "unknown"


# 错误分类映射
ERROR_TYPE_MAP = {
    "FileNotFoundError": ErrorCategory.FILE_ERROR,
    "PermissionError": ErrorCategory.PERMISSION_ERROR,
    "ModuleNotFoundError": ErrorCategory.IMPORT_ERROR,
    "ImportError": ErrorCategory.IMPORT_ERROR,
    "OperationalError": ErrorCategory.DATABASE_ERROR,
    "KeyError": ErrorCategory.KEY_ERROR,
    "TypeError": ErrorCategory.TYPE_ERROR,
    "ValueError": ErrorCategory.VALUE_ERROR,
    "TimeoutError": ErrorCategory.TIMEOUT_ERROR,
    "ConnectionError": ErrorCategory.NETWORK_ERROR,
    "JSONDecodeError": ErrorCategory.PARSE_ERROR,
    "UnicodeDecodeError": ErrorCategory.ENCODING_ERROR,
}

# 错误建议
ERROR_SUGGESTIONS = {
    ErrorCategory.FILE_ERROR: "检查文件路径是否正确，考虑使用 os.path.exists() 预先检查",
    ErrorCategory.PERMISSION_ERROR: "检查文件/目录权限",
    ErrorCategory.IMPORT_ERROR: "检查模块是否已安装，尝试 pip install",
    ErrorCategory.DATABASE_ERROR: "检查数据库连接，数据库是否被锁定",
    ErrorCategory.KEY_ERROR: "检查字典键是否存在，使用 dict.get() 避免",
    ErrorCategory.TYPE_ERROR: "检查变量类型",
    ErrorCategory.VALUE_ERROR: "检查值是否有效",
    ErrorCategory.TIMEOUT_ERROR: "增加超时时间或检查网络",
    ErrorCategory.NETWORK_ERROR: "检查网络连接",
    ErrorCategory.PARSE_ERROR: "检查数据格式",
    ErrorCategory.ENCODING_ERROR: "检查文件编码",
}


@dataclass
class ErrorRecord:
    """错误记录"""

    error_type: str
    error_message: str
    category: str
    suggestion: str
    traceback: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)


class ErrorCatcher:
    """错误捕获器"""

    def __init__(self):
        self.errors: list[ErrorRecord] = []

    def catch(self, error: Exception, context: Optional[Dict] = None) -> ErrorRecord:
        """捕获错误并分类"""
        error_type = type(error).__name__
        category = ERROR_TYPE_MAP.get(error_type, ErrorCategory.UNKNOWN)
        suggestion = ERROR_SUGGESTIONS.get(category, "请检查错误信息")

        record = ErrorRecord(
            error_type=error_type,
            error_message=str(error),
            category=category.value if isinstance(category, ErrorCategory) else category,
            suggestion=suggestion,
            traceback=traceback.format_exc(),
            context=context or {},
        )

        self.errors.append(record)
        logger.info(f"Caught error: {error_type} - {category.value}")

        return record

    def get_errors(self) -> list[ErrorRecord]:
        """获取所有错误记录"""
        return self.errors

    def export(self) -> list[dict]:
        """导出为字典列表"""
        return [asdict(e) for e in self.errors]


def register_error(
    error: Exception,
    session_id: Optional[str] = None,
    context: Optional[Dict] = None,
) -> ErrorRecord:
    """注册错误的便捷函数"""
    catcher = ErrorCatcher()
    return catcher.catch(error, context)


def catch_errors(func: Callable) -> Callable:
    """装饰器：自动捕获函数错误"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        catcher = ErrorCatcher()
        try:
            return func(*args, **kwargs)
        except Exception as e:
            record = catcher.catch(e, {"function": func.__name__})
            logger.error(f"Error in {func.__name__}: {record.error_message}")
            raise

    return wrapper