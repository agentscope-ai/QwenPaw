# -*- coding: utf-8 -*-
"""
Evolution Dashboard - 进化仪表盘模块

可视化展示进化数据，包括错误趋势、模式分析、优化建议等。
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class EvolutionStats:
    """进化统计数据"""

    total_errors: int = 0
    error_trend: str = "stable"  # increasing, decreasing, stable
    top_patterns: List[Dict[str, Any]] = None
    recent_improvements: List[str] = None
    pending_actions: List[str] = None

    def __post_init__(self):
        if self.top_patterns is None:
            self.top_patterns = []
        if self.recent_improvements is None:
            self.recent_improvements = []
        if self.pending_actions is None:
            self.pending_actions = []


class EvolutionDashboard:
    """进化仪表盘"""

    def __init__(self):
        self.stats: Optional[EvolutionStats] = None

    def collect_stats(self) -> EvolutionStats:
        """收集统计数据"""
        # TODO: 从数据库加载真实数据
        stats = EvolutionStats(
            total_errors=42,
            error_trend="decreasing",
            top_patterns=[
                {"category": "file_error", "count": 15, "suggestion": "添加文件检查"},
                {"category": "timeout_error", "count": 10, "suggestion": "增加超时"},
            ],
            recent_improvements=[
                "添加了自动错误捕获装饰器",
                "优化了模式检测算法",
            ],
            pending_actions=[
                "更新 AGENTS.md 添加文件检查规则",
                "创建记忆数据库备份脚本",
            ],
        )

        self.stats = stats
        return stats

    def generate_report(self, format: str = "markdown") -> str:
        """
        生成进化报告

        Args:
            format: 输出格式，支持 markdown, html, json

        Returns:
            格式化的报告字符串
        """
        stats = self.stats or self.collect_stats()

        if format == "markdown":
            return self._generate_markdown(stats)
        elif format == "html":
            return self._generate_html(stats)
        elif format == "json":
            return json.dumps(self._to_dict(stats), ensure_ascii=False, indent=2)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _generate_markdown(self, stats: EvolutionStats) -> str:
        """生成 Markdown 报告"""

        report = """# Self-Evolution 进化报告

## 总体统计

"""

        # 错误趋势图标
        trend_icons = {
            "increasing": "📈",
            "decreasing": "📉",
            "stable": "➡️",
        }
        trend_icon = trend_icons.get(stats.error_trend, "➡️")

        report += f"| 指标 | 值 |\n"
        report += f"|------|-----|\n"
        report += f"| 总错误数 | {stats.total_errors} |\n"
        report += f"| 错误趋势 | {trend_icon} {stats.error_trend} |\n"

        # Top 模式
        if stats.top_patterns:
            report += "\n## Top 错误模式\n\n"
            report += "| 类别 | 次数 | 建议 |\n"
            report += "|------|------|------|\n"
            for p in stats.top_patterns[:5]:
                report += f"| {p.get('category', 'N/A')} | {p.get('count', 0)} | {p.get('suggestion', 'N/A')} |\n"

        # 最近改进
        if stats.recent_improvements:
            report += "\n## 最近改进\n\n"
            for improvement in stats.recent_improvements:
                report += f"- {improvement}\n"

        # 待处理操作
        if stats.pending_actions:
            report += "\n## 待处理操作\n\n"
            for action in stats.pending_actions:
                report += f"- [ ] {action}\n"

        report += f"\n---\n*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"

        return report

    def _generate_html(self, stats: EvolutionStats) -> str:
        """生成 HTML 报告"""

        return f"""<!DOCTYPE html>
<html>
<head>
    <title>Self-Evolution Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
    </style>
</head>
<body>
    <h1>Self-Evolution 进化报告</h1>
    <h2>总体统计</h2>
    <table>
        <tr><th>指标</th><th>值</th></tr>
        <tr><td>总错误数</td><td>{stats.total_errors}</td></tr>
        <tr><td>错误趋势</td><td>{stats.error_trend}</td></tr>
    </table>
</body>
</html>"""

    def _to_dict(self, stats: EvolutionStats) -> dict:
        """转换为字典"""
        return {
            "total_errors": stats.total_errors,
            "error_trend": stats.error_trend,
            "top_patterns": stats.top_patterns,
            "recent_improvements": stats.recent_improvements,
            "pending_actions": stats.pending_actions,
            "generated_at": datetime.now().isoformat(),
        }


def generate_report(format: str = "markdown") -> str:
    """便捷函数：生成进化报告"""
    dashboard = EvolutionDashboard()
    return dashboard.generate_report(format)