# -*- coding: utf-8 -*-
"""
Telegram 格式转换器 V2
将标准 Markdown 格式转换为 Telegram HTML 格式

转换规则：
- 标题 (# ## ### ####) → <b>标题</b>
- 粗体 **text** → <b>text</b>
- 斜体 *text* → <i>text</i>
- 删除线 ~~text~~ → <s>text</s>
- 行内代码 `code` → <code>code</code>
- 代码块 ```code``` → <pre>code</pre>
- 引用 > text → <blockquote>text</blockquote>（多行合并）
- 表格 |col1|col2| → col1\tcol2（表头加粗）
- 列表 - item → • item
- 分隔线 --- → ──────────
- 链接 [text](url) → <a href="url">text</a>
"""

import re
import logging

logger = logging.getLogger(__name__)


def convert_markdown_to_telegram_html(text: str) -> str:
    """
    将 Markdown 格式转换为 Telegram HTML 格式

    Args:
        text: Markdown 格式的文本

    Returns:
        Telegram HTML 格式的文本
    """
    if not text:
        return text

    logger.debug(f"[FORMAT] Input: {mask_text(text, 100)}")

    lines = text.split("\n")
    converted_lines = []

    # 状态跟踪
    in_code_block = False
    code_block_content = []
    in_blockquote = False
    blockquote_lines = []
    table_header_pending = False

    def flush_blockquote():
        """刷新引用块"""
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote and blockquote_lines:
            joined = "\n".join(blockquote_lines)
            converted_lines.append(f"<blockquote>{joined}</blockquote>")
            blockquote_lines = []
            in_blockquote = False

    def flush_code_block():
        """刷新代码块"""
        nonlocal in_code_block, code_block_content
        if code_block_content:
            code_text = "\n".join(code_block_content)
            code_text = escape_html(code_text)
            converted_lines.append(f"<pre>{code_text}</pre>")
        # Always reset state, even for empty blocks
        code_block_content = []
        in_code_block = False

    def process_table_header():
        """处理待处理的表头（加粗）"""
        nonlocal table_header_pending
        if table_header_pending and converted_lines:
            prev = converted_lines[-1]
            if not prev.startswith("<"):
                # 支持单列表格（无制表符）
                if "\t" in prev:
                    cells = prev.split("\t")
                    converted_lines[-1] = "\t".join(
                        f"<b>{cell}</b>" for cell in cells
                    )
                else:
                    # 单列情况
                    converted_lines[-1] = f"<b>{prev}</b>"
        table_header_pending = False

    for line in lines:
        # 1. 代码块检测（检测行中任意位置的 ```）
        if "```" in line:
            if in_code_block:
                # 在代码块内，遇到 ``` 表示结束
                code_line = line.split("```")[0]
                if code_line:
                    code_block_content.append(code_line)
                flush_code_block()
                # 处理 ``` 之后的内容（如果有）
                parts = line.split("```", 1)
                if len(parts) > 1 and parts[1].strip():
                    # 同一行有结束后的内容，继续处理但不重新进入代码块
                    line = parts[1]
                    # Fall through to process the remaining content
                else:
                    continue
            else:
                # 不在代码块内，遇到 ``` 表示开始
                flush_blockquote()
                process_table_header()
                # ``` 之前的内容正常处理（添加为已处理行）
                before = line.split("```")[0]
                if before.strip():
                    # 处理 ``` 之前的内容中的行内样式
                    processed_before = before
                    # 删除线
                    if "~~" in processed_before:
                        processed_before = re.sub(
                            r"~~(.+?)~~",
                            r"<s>\1</s>",
                            processed_before,
                        )
                    # 粗体
                    if "**" in processed_before:
                        processed_before = re.sub(
                            r"\*\*(.+?)\*\*",
                            r"<b>\1</b>",
                            processed_before,
                        )
                    # 斜体
                    processed_before = re.sub(
                        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
                        r"<i>\1</i>",
                        processed_before,
                    )
                    # 行内代码
                    if "`" in processed_before:
                        processed_before = re.sub(
                            r"`(.+?)`",
                            r"<code>\1</code>",
                            processed_before,
                        )

                    # 链接
                    def _replace_link_v1(match):
                        text = escape_html(match.group(1))
                        href = escape_html(match.group(2), quote=True)
                        return f'<a href="{href}">{text}</a>'

                    if re.search(r"\[.+?\]\(.+?\)", processed_before):
                        processed_before = re.sub(
                            r"\[(.+?)\]\((.+?)\)",
                            _replace_link_v1,
                            processed_before,
                        )
                    converted_lines.append(processed_before)

                # 检查是否有 ``` 之后的内容（同一行，单行代码块）
                after_parts = line.split("```")[1:]
                if len(after_parts) >= 2 and after_parts[0].strip():
                    # 单行有开始和结束（```code``` 格式）
                    code_content = after_parts[0]
                    if code_content.strip():
                        # 直接处理单行代码块，不设置状态
                        code_text = escape_html(code_content)
                        converted_lines.append(f"<pre>{code_text}</pre>")
                    # 处理最后一个 ``` 之后的内容
                    if len(after_parts) > 2 and after_parts[2].strip():
                        line = after_parts[2]
                    else:
                        continue
                else:
                    # 标准的代码块开始
                    in_code_block = True
                    continue

        if in_code_block:
            code_block_content.append(line)
            continue

        # 2. 标题处理（支持行中任意位置，如 "[TG_bot]  ## 标题"）
        title_match = re.search(r"(######?|#####|####|###|##|#)\s+(.+)", line)
        if title_match:
            flush_blockquote()
            process_table_header()
            prefix = line[: title_match.start()].strip()
            title = title_match.group(2).strip()
            if prefix:
                converted_lines.append(f"{prefix} <b>{title}</b>")
            else:
                converted_lines.append(f"<b>{title}</b>")
            continue

        # 3. 水平分割线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line.strip()):
            flush_blockquote()
            process_table_header()
            converted_lines.append("──────────")
            continue

        # 4. 表格检测
        if re.match(r"^\|.*\|$", line.strip()):
            flush_blockquote()
            # 检测是否是分隔行（|---|---|）
            if re.match(r"^\|[\s\-:|]+\|$", line.strip()):
                table_header_pending = True
                continue

            # 数据行
            cells = [cell.strip() for cell in line.split("|")[1:-1]]
            if cells:
                process_table_header()
                # 对每个单元格处理行内样式
                processed_cells = []
                for cell in cells:
                    cell_line = cell
                    # 删除线
                    if "~~" in cell_line:
                        cell_line = re.sub(
                            r"~~(.+?)~~",
                            r"<s>\1</s>",
                            cell_line,
                        )
                    # 粗体
                    if "**" in cell_line:
                        cell_line = re.sub(
                            r"\*\*(.+?)\*\*",
                            r"<b>\1</b>",
                            cell_line,
                        )
                    if "__" in cell_line:
                        cell_line = re.sub(
                            r"__(.+?)__",
                            r"<b>\1</b>",
                            cell_line,
                        )
                    # 斜体
                    cell_line = re.sub(
                        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
                        r"<i>\1</i>",
                        cell_line,
                    )
                    cell_line = re.sub(
                        r"(?<![a-zA-Z0-9_])_(.+?)_(?![a-zA-Z0-9_])",
                        r"<i>\1</i>",
                        cell_line,
                    )
                    # 行内代码
                    if "`" in cell_line:
                        cell_line = re.sub(
                            r"`(.+?)`",
                            r"<code>\1</code>",
                            cell_line,
                        )

                    # 链接
                    def _replace_link_v2(match):
                        text = escape_html(match.group(1))
                        href = escape_html(match.group(2), quote=True)
                        return f'<a href="{href}">{text}</a>'

                    if re.search(r"\[.+?\]\(.+?\)", cell_line):
                        cell_line = re.sub(
                            r"\[(.+?)\]\((.+?)\)",
                            _replace_link_v2,
                            cell_line,
                        )
                    processed_cells.append(cell_line)
                converted_lines.append("\t".join(processed_cells))
            continue

        # 5. 引用处理（支持多行合并）
        if line.startswith("> "):
            if not in_blockquote:
                in_blockquote = True
                blockquote_lines = [line[2:].strip()]
            else:
                blockquote_lines.append(line[2:].strip())
            continue
        else:
            flush_blockquote()

        # 6. 列表前缀替换
        if re.match(r"^[-*+]\s+", line):
            line = re.sub(r"^[-*+]\s+", "• ", line)

        # 7. 行内样式处理（顺序很重要！）
        # 7.1 删除线
        if "~~" in line:
            line = re.sub(r"~~(.+?)~~", r"<s>\1</s>", line)

        # 7.2 粗体
        if "**" in line:
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        if "__" in line:
            line = re.sub(r"__(.+?)__", r"<b>\1</b>", line)

        # 7.3 斜体（在粗体之后，避免冲突）
        line = re.sub(
            r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
            r"<i>\1</i>",
            line,
        )
        line = re.sub(
            r"(?<![a-zA-Z0-9_])_(.+?)_(?![a-zA-Z0-9_])",
            r"<i>\1</i>",
            line,
        )

        # 7.4 行内代码
        if "`" in line:
            line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)

        # 7.5 链接
        def _replace_link_v3(match):
            text = escape_html(match.group(1))
            href = escape_html(match.group(2), quote=True)
            return f'<a href="{href}">{text}</a>'

        if re.search(r"\[.+?\]\(.+?\)", line):
            line = re.sub(r"\[(.+?)\]\((.+?)\)", _replace_link_v3, line)

        converted_lines.append(line)

    # 刷新剩余内容
    flush_blockquote()
    flush_code_block()
    process_table_header()

    result = "\n".join(converted_lines)
    logger.debug(f"[FORMAT] Output: {mask_text(result, 100)}")
    return result


def escape_html(text: str, quote: bool = False) -> str:
    """
    HTML 转义

    Args:
        text: 原始文本
        quote: 是否转义引号（用于属性值）

    Returns:
        转义后的文本
    """
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    if quote:
        text = text.replace('"', "&quot;")
        text = text.replace("'", "&#x27;")
    return text


def mask_text(text: str, max_length: int = 50) -> str:
    """
    脱敏文本，用于日志记录

    Args:
        text: 原始文本
        max_length: 最大显示长度

    Returns:
        脱敏后的文本
    """
    if not text:
        return "<empty>"
    length = len(text)
    snippet = text[:max_length].replace("\n", "\\n").replace("\r", "\\r")
    if length > max_length:
        return f"<{length} chars: {snippet}...>"
    return f"<{length} chars: {snippet}>"


if __name__ == "__main__":
    test_text = """# 大标题

## 中标题

### 小标题

这是 **粗体** 和 *斜体* 的测试

- 列表项一
- 列表项二
- 列表项三

1. 有序列表一
2. 有序列表二

> 这是引用内容
> 第二行引用
> 第三行引用

```python
def hello():
    print("Hello")
```

| 列 1 | 列 2 |
|------|------|
| 值 1 | 值 2 |
| 值 3 | 值 4 |

[链接文本](https://example.com)

~~删除线~~

---

普通文本
"""

    result = convert_markdown_to_telegram_html(test_text)
    print("转换结果:")
    print("=" * 60)
    print(result)
    print("=" * 60)
    print("\n验证:")
    print("✓ 粗体:", "<b>" in result)
    print("✓ 斜体:", "<i>" in result)
    print("✓ 标题:", "<b>大标题</b>" in result)
    print("✓ 列表:", "• " in result)
    print("✓ 引用：", "<blockquote>" in result and "\n" in result)
    print("✓ 表格制表符:", "\t" in result)
    print("✓ 表格表头加粗:", "<b>列 1</b>" in result)
    print("✓ 代码块:", "<pre>" in result)
    print("✓ 链接:", "<a href=" in result)
    print("✓ 删除线:", "<s>" in result)
    print("✓ 分隔线:", "──────────" in result)
