# -*- coding: utf-8 -*-
"""BI 报告生成器

将多个章节片段拼接成完整的 HTML 报告。

Usage:
    # 单主题
    python report_builder.py --sections sections_001.json --output report.html
    
    # 多主题
    python report_builder.py --sections sections_001.json sections_002.json ... \
        --output report.html \
        --report-title "XXX 产品数据分析报告" \
        --overall-summary "<p>跨主题核心结论...</p>"
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Template


def load_skeleton_template(template_path: Optional[str] = None) -> Template:
    """加载骨架模板
    
    Args:
        template_path: 模板文件路径，默认使用上级目录 resources/skeleton_template.html
        
    Returns:
        Jinja2 Template 对象
    """
    if template_path is None:
        template_path = Path(__file__).parent.parent / "resources" / "skeleton_template.html"
    
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()
    
    return Template(template_content)


def load_sections(sections_sources: List[str]) -> List[Dict[str, Any]]:
    """加载章节数据
    
    Args:
        sections_sources: JSON 文件路径列表
        
    Returns:
        章节列表，每个章节包含 title, icon, html_fragment
    """
    all_sections = []
    for source in sections_sources:
        if source.endswith('.json') and os.path.exists(source):
            with open(source, 'r', encoding='utf-8') as f:
                sections = json.load(f)
                if isinstance(sections, list):
                    all_sections.extend(sections)
                else:
                    all_sections.append(sections)
        else:
            raise ValueError(f"无效的 sections 文件: {source}")
    return all_sections


def build_report(
    sections: List[Dict[str, Any]],
    report_title: Optional[str] = None,
    overall_summary: Optional[str] = None,
    date: Optional[str] = None,
    template_path: Optional[str] = None,
) -> str:
    """构建完整报告
    
    Args:
        sections: 章节列表，每个章节包含 title, icon(可选), html_fragment
        report_title: 报告标题（可选，多主题时传递）
        overall_summary: 总体摘要 HTML（可选，多主题时显示）
        date: 生成日期（可选，默认今天）
        template_path: 骨架模板路径（可选，默认使用内置模板）
        
    Returns:
        完整的 HTML 字符串
    """
    # 加载模板
    template = load_skeleton_template(template_path)
    
    # 默认日期
    if date is None:
        date = datetime.now().strftime("%Y年%m月%d日")
    
    # 单主题场景：不传 report_title 和 overall_summary
    # 多主题场景：传递 report_title 和 overall_summary
    html = template.render(
        report_title=report_title or "",
        date=date,
        sections=sections,
        overall_summary=overall_summary or "",
    )
    
    return html


def save_report(html: str, output_path: str) -> None:
    """保存报告到文件
    
    Args:
        html: HTML 内容
        output_path: 输出文件路径
    """
    # 确保目录存在
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"报告已保存: {output_path}")


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description="BI 报告生成器")
    parser.add_argument(
        "--sections", "-s",
        nargs='+',
        required=True,
        help="章节数据 JSON 文件路径（可指定多个）"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="输出 HTML 文件路径"
    )
    parser.add_argument(
        "--report-title", "-t",
        default=None,
        help="报告标题（可选，多主题时建议传递）"
    )
    parser.add_argument(
        "--overall-summary",
        default=None,
        help="总体摘要 HTML（可选）"
    )
    parser.add_argument(
        "--date",
        default=None,
        help="生成日期（可选，默认今天）"
    )
    parser.add_argument(
        "--template",
        default=None,
        help="骨架模板路径（可选，默认使用内置模板）"
    )
    
    args = parser.parse_args()
    
    # 加载章节数据
    sections = load_sections(args.sections)
    print(f"加载了 {len(sections)} 个章节，来自 {len(args.sections)} 个文件")
    
    # 构建报告
    # 单主题场景：不传 report_title 和 overall_summary
    # 多主题场景：传递 report_title 和 overall_summary
    html = build_report(
        sections=sections,
        report_title=args.report_title,
        overall_summary=args.overall_summary,
        date=args.date,
        template_path=args.template,
    )
    
    # 保存报告
    save_report(html, args.output)
    print(f"报告总长度: {len(html)} 字符")


if __name__ == "__main__":
    main()
