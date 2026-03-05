# -*- coding: utf-8 -*-
"""
Markdown 解析器模块
将 Markdown 转换为飞书 Block 格式
"""

import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


class MarkdownParser:
    """Markdown 解析器，转换为飞书 Block 格式"""

    # 图片占位符标记
    IMAGE_PLACEHOLDER = "__IMAGE_PLACEHOLDER__"
    # 表格占位符标记
    TABLE_PLACEHOLDER = "__TABLE_PLACEHOLDER__"

    def __init__(self, md_file_path: str):
        self.md_dir = Path(md_file_path).parent
        # pending_images 格式: [(block_index, image_path, is_url), ...]
        self.pending_images: List[Tuple[int, str, bool]] = []
        self.pending_tables: List[Tuple[int, List[List[str]]]] = []  # [(block_index, table_data), ...]

    def parse(self, content: str) -> List[Dict[str, Any]]:
        """
        解析 Markdown 内容为飞书 Block 列表
        图片和表格会生成占位符，需要后续处理

        Returns:
            blocks 列表
        """
        lines = content.split("\n")
        blocks = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # 标题块（所有 # 开头的都作为内容）
            if line.startswith("#"):
                level = len(re.match(r"^#+", line).group())
                text = line[level:].strip()
                blocks.append(self._create_heading_block(text, min(level, 9)))
                i += 1
                continue

            # 代码块
            if line.startswith("```"):
                language = line[3:].strip() or "plain_text"
                code_lines = []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # 跳过结束的 ```
                blocks.append(self._create_code_block("\n".join(code_lines), language))
                continue

            # 表格检测（以 | 开头的行）
            if line.strip().startswith("|") and "|" in line[1:]:
                table_data, consumed = self._parse_table(lines, i)
                if table_data:
                    block = self._create_table_block(table_data, len(blocks))
                    blocks.append(block)
                    i += consumed
                    continue

            # 图片
            img_match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
            if img_match:
                alt_text = img_match.group(1)
                img_path = img_match.group(2)
                block = self._create_image_block(img_path, alt_text, len(blocks))
                if block:
                    blocks.append(block)
                i += 1
                continue

            # 引用块
            if line.startswith(">"):
                quote_lines = []
                while i < len(lines) and lines[i].startswith(">"):
                    quote_lines.append(lines[i][1:].strip())
                    i += 1
                blocks.append(self._create_quote_block("\n".join(quote_lines)))
                continue

            # 无序列表
            if re.match(r"^[\-\*\+]\s", line):
                list_items = []
                while i < len(lines) and re.match(r"^[\-\*\+]\s", lines[i]):
                    list_items.append(re.sub(r"^[\-\*\+]\s", "", lines[i]))
                    i += 1
                for item in list_items:
                    blocks.append(self._create_bullet_block(item))
                continue

            # 有序列表
            if re.match(r"^\d+\.\s", line):
                list_items = []
                while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                    list_items.append(re.sub(r"^\d+\.\s", "", lines[i]))
                    i += 1
                for item in list_items:
                    blocks.append(self._create_ordered_block(item))
                continue

            # 分割线
            if re.match(r"^[\-\*\_]{3,}$", line.strip()):
                blocks.append(self._create_divider_block())
                i += 1
                continue

            # 普通段落
            if line.strip():
                blocks.append(self._create_text_block(line))

            i += 1

        return blocks

    def _parse_table(self, lines: List[str], start_idx: int) -> Tuple[List[List[str]], int]:
        """
        解析 Markdown 表格

        Args:
            lines: 所有行
            start_idx: 表格起始行索引

        Returns:
            (table_data, consumed_lines) - 表格数据和消耗的行数
        """
        table_rows = []
        i = start_idx

        while i < len(lines):
            line = lines[i].strip()
            # 检查是否是表格行
            if not line.startswith("|"):
                break

            # 解析单元格
            cells = self._parse_table_row(line)
            if not cells:
                break

            # 跳过分隔行（如 |---|---|---|）
            if all(re.match(r"^[\-:]+$", cell.strip()) for cell in cells):
                i += 1
                continue

            table_rows.append(cells)
            i += 1

        consumed = i - start_idx
        return table_rows, consumed

    def _parse_table_row(self, line: str) -> List[str]:
        """解析表格行，返回单元格列表"""
        # 去掉首尾的 |
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]

        # 按 | 分割
        cells = [cell.strip() for cell in line.split("|")]
        return cells

    def _create_table_block(self, table_data: List[List[str]], block_index: int) -> Dict:
        """创建表格块占位符"""
        # 记录待处理的表格
        self.pending_tables.append((block_index, table_data))

        rows = len(table_data)
        cols = max(len(row) for row in table_data) if table_data else 0

        return {
            "block_type": self.TABLE_PLACEHOLDER,
            "table_data": table_data,
            "rows": rows,
            "cols": cols
        }

    def _create_text_elements(self, text: str) -> List[Dict]:
        """创建文本元素，处理内联格式"""
        elements = []

        # 简化处理：将整段作为一个文本元素
        # 处理加粗、斜体、行内代码等
        parts = self._parse_inline_formats(text)

        for part in parts:
            elements.append(part)

        return elements if elements else [{"text_run": {"content": text}}]

    def _parse_inline_formats(self, text: str) -> List[Dict]:
        """解析内联格式"""
        elements = []

        # 正则匹配各种格式
        pattern = r"(\*\*(.+?)\*\*|__(.+?)__|`(.+?)`|\*(.+?)\*|_(.+?)_|\[(.+?)\]\((.+?)\))"

        last_end = 0
        for match in re.finditer(pattern, text):
            # 添加匹配前的普通文本
            if match.start() > last_end:
                plain_text = text[last_end:match.start()]
                if plain_text:
                    elements.append({"text_run": {"content": plain_text}})

            # 加粗
            if match.group(2) or match.group(3):
                content = match.group(2) or match.group(3)
                elements.append({
                    "text_run": {
                        "content": content,
                        "text_element_style": {"bold": True}
                    }
                })
            # 行内代码
            elif match.group(4):
                elements.append({
                    "text_run": {
                        "content": match.group(4),
                        "text_element_style": {"inline_code": True}
                    }
                })
            # 斜体
            elif match.group(5) or match.group(6):
                content = match.group(5) or match.group(6)
                elements.append({
                    "text_run": {
                        "content": content,
                        "text_element_style": {"italic": True}
                    }
                })
            # 链接
            elif match.group(7) and match.group(8):
                elements.append({
                    "text_run": {
                        "content": match.group(7),
                        "text_element_style": {
                            "link": {"url": match.group(8)}
                        }
                    }
                })

            last_end = match.end()

        # 添加剩余文本
        if last_end < len(text):
            remaining = text[last_end:]
            if remaining:
                elements.append({"text_run": {"content": remaining}})

        return elements if elements else [{"text_run": {"content": text}}]

    def _create_heading_block(self, text: str, level: int) -> Dict:
        """创建标题块"""
        # block_type: heading1=3, heading2=4, ..., heading9=11
        block_type_num = 2 + level
        return {
            "block_type": block_type_num,
            f"heading{level}": {
                "elements": self._create_text_elements(text)
            }
        }

    def _create_text_block(self, text: str) -> Dict:
        """创建文本块"""
        return {
            "block_type": 2,
            "text": {
                "elements": self._create_text_elements(text)
            }
        }

    def _create_code_block(self, code: str, language: str) -> Dict:
        """创建代码块"""
        # 飞书支持的语言映射
        language_map = {
            "python": 49,
            "javascript": 22,
            "js": 22,
            "typescript": 67,
            "ts": 67,
            "java": 21,
            "go": 18,
            "c": 7,
            "cpp": 9,
            "c++": 9,
            "csharp": 10,
            "c#": 10,
            "ruby": 54,
            "php": 46,
            "swift": 64,
            "kotlin": 27,
            "rust": 55,
            "sql": 61,
            "shell": 58,
            "bash": 58,
            "json": 23,
            "xml": 73,
            "html": 20,
            "css": 11,
            "yaml": 74,
            "markdown": 35,
            "plain_text": 47,
        }

        lang_code = language_map.get(language.lower(), 47)  # 默认 plain_text

        return {
            "block_type": 14,
            "code": {
                "elements": [{"text_run": {"content": code}}],
                "language": lang_code
            }
        }

    def _create_image_block(self, img_path: str, alt_text: str, block_index: int) -> Optional[Dict]:
        """
        创建图片块占位符，记录待上传的图片
        支持本地路径和网络 URL
        """
        # 判断是网络图片还是本地图片
        is_url = img_path.startswith(("http://", "https://"))

        # 记录待上传的图片（保持原始路径，uploader 会自动处理）
        self.pending_images.append((block_index, img_path, is_url))

        # 返回占位符标记
        return {
            "block_type": self.IMAGE_PLACEHOLDER,
            "image_path": img_path,
            "is_url": is_url
        }

    def _create_quote_block(self, text: str) -> Dict:
        """创建引用块"""
        return {
            "block_type": 15,
            "quote": {
                "elements": self._create_text_elements(text)
            }
        }

    def _create_bullet_block(self, text: str) -> Dict:
        """创建无序列表块"""
        return {
            "block_type": 12,
            "bullet": {
                "elements": self._create_text_elements(text)
            }
        }

    def _create_ordered_block(self, text: str) -> Dict:
        """创建有序列表块"""
        return {
            "block_type": 13,
            "ordered": {
                "elements": self._create_text_elements(text)
            }
        }

    def _create_divider_block(self) -> Dict:
        """创建分割线块"""
        return {
            "block_type": 22,
            "divider": {}
        }
