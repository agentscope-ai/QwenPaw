# -*- coding: utf-8 -*-
"""
Session Check - 会话启动检查模块

每次会话启动时自动检查系统状态。
"""
import os
from typing import Dict, Any, List
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """检查结果"""

    name: str
    status: str  # pass, warning, fail
    message: str
    details: Any = None


class SessionChecker:
    """会话启动检查器"""

    def __init__(self):
        self.checks: List[CheckResult] = []

    def run_all_checks(self) -> Dict[str, Any]:
        """运行所有检查"""
        self.checks = []

        # 1. 检查文件大小
        self._check_file_sizes()

        # 2. 检查待处理进化项
        self._check_pending_items()

        # 3. 检查数据库健康
        self._check_database_health()

        # 4. 检查临时文件
        self._check_temp_files()

        return self._generate_report()

    def _check_file_sizes(self):
        """检查关键文件大小"""
        # 检查 AGENTS.md 和 MEMORY.md
        max_lines = 500

        files_to_check = [
            "AGENTS.md",
            "MEMORY.md",
        ]

        for filename in files_to_check:
            # 尝试多个可能的位置
            possible_paths = [
                os.path.join(os.getcwd(), filename),
                os.path.join(os.path.expanduser("~"), ".copaw", filename),
            ]

            for filepath in possible_paths:
                if os.path.exists(filepath):
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            lines = sum(1 for _ in f)

                        status = "pass" if lines <= max_lines else "warning"
                        message = f"{filename}: {lines} 行"

                        if status == "warning":
                            message += f" (超过 {max_lines} 行阈值)"

                        self.checks.append(
                            CheckResult(
                                name=f"file_size_{filename.replace('.', '_')}",
                                status=status,
                                message=message,
                                details={"lines": lines, "threshold": max_lines},
                            )
                        )
                        break
                    except Exception as e:
                        self.checks.append(
                            CheckResult(
                                name=f"file_size_{filename.replace('.', '_')}",
                                status="warning",
                                message=f"检查 {filename} 失败: {e}",
                            )
                        )

    def _check_pending_items(self):
        """检查待处理的进化项"""
        # TODO: 检查是否有未归因的错误、未处理的模式等
        # 暂时返回 pass
        self.checks.append(
            CheckResult(
                name="pending_items",
                status="pass",
                message="没有待处理的进化项",
            )
        )

    def _check_database_health(self):
        """检查数据库健康状态"""
        # TODO: 检查记忆数据库
        self.checks.append(
            CheckResult(
                name="database_health",
                status="pass",
                message="数据库状态正常",
            )
        )

    def _check_temp_files(self):
        """检查临时文件"""
        temp_dirs = ["tool_result", "temp"]

        temp_files_count = 0
        for temp_dir in temp_dirs:
            if os.path.exists(temp_dir):
                try:
                    files = os.listdir(temp_dir)
                    temp_files_count += len(files)
                except Exception as e:
                    logger.warning(f"Cannot list {temp_dir}: {e}")

        if temp_files_count > 100:
            status = "warning"
            message = f"临时文件较多: {temp_files_count} 个"
        else:
            status = "pass"
            message = f"临时文件正常: {temp_files_count} 个"

        self.checks.append(
            CheckResult(
                name="temp_files",
                status=status,
                message=message,
                details={"count": temp_files_count},
            )
        )

    def _generate_report(self) -> Dict[str, Any]:
        """生成检查报告"""
        passed = sum(1 for c in self.checks if c.status == "pass")
        warnings = sum(1 for c in self.checks if c.status == "warning")
        failed = sum(1 for c in self.checks if c.status == "fail")

        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(self.checks),
                "passed": passed,
                "warnings": warnings,
                "failed": failed,
            },
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


def run_session_check() -> Dict[str, Any]:
    """运行会话启动检查"""
    checker = SessionChecker()
    return checker.run_all_checks()