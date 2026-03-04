"""
Telegram 格式转换工具
将 Markdown 格式转换为 Telegram HTML 兼容格式
"""
import re


def convert_markdown_to_telegram_html(text: str) -> str:
    """
    将 Markdown 格式转换为 Telegram HTML 格式
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not text:
        return text
    
    original_text = text[:200]  # 只记录前 200 字符
    logger.info(f"[FORMAT] Original: {original_text}...")
    
    lines = text.split('\n')
    converted_lines = []
    in_code_block = False
    code_block_content = []
    
    for line in lines:
        # 处理代码块
        if line.strip().startswith('```'):
            if in_code_block:
                # 结束代码块
                code_text = '\n'.join(code_block_content)
                code_text = escape_html(code_text)
                converted_lines.append(f'<pre>{code_text}</pre>')
                code_block_content = []
                in_code_block = False
            else:
                # 开始代码块
                in_code_block = True
                lang_match = re.match(r'```(\w*)', line.strip())
                if lang_match and lang_match.group(1):
                    code_block_content.append(f'{lang_match.group(1)}\n')
            continue
        
        if in_code_block:
            code_block_content.append(line)
            continue
        
        original_line = line
        
        # 1. 处理标题 (# ## ### #### ##### ######)
        if line.startswith('###### '):
            title = line[7:].strip()
            converted_lines.append(f'<b>▸ {title}</b>')
            continue
        elif line.startswith('##### '):
            title = line[6:].strip()
            converted_lines.append(f'<b>▸ {title}</b>')
            continue
        elif line.startswith('#### '):
            title = line[5:].strip()
            converted_lines.append(f'<b>▸ {title}</b>')
            continue
        elif line.startswith('### '):
            title = line[4:].strip()
            converted_lines.append(f'<b>▸ {title}</b>')
            continue
        elif line.startswith('## '):
            title = line[3:].strip()
            converted_lines.append(f'<b>📌 {title}</b>')
            continue
        elif line.startswith('# '):
            title = line[2:].strip()
            converted_lines.append(f'<b>📌 {title}</b>')
            continue
        
        # 2. 处理水平分割线 (--- 或 *** 或 ___)
        if re.match(r'^(-{3,}|\*{3,}|_{3,})$', line.strip()):
            converted_lines.append('──────────')
            continue
        
        # 3. 处理引用 (> )
        if line.startswith('> '):
            quote = line[2:].strip()
            converted_lines.append(f'<blockquote>{quote}</blockquote>')
            continue
        
        # 3. 处理列表 (- 或 * 或 +) - 只替换前缀，不跳过行内样式处理
        if re.match(r'^[-*+]\s+', line):
            line = re.sub(r'^[-*+]\s+', '• ', line)
        
        # 4. 处理有序列表 (1. 2. 3.) - 保持原样，继续处理行内样式
        
        # 5. 处理删除线 (~~text~~)
        if '~~' in line:
            line = re.sub(r'~~(.+?)~~', r'<s>\1</s>', line)
        
        # 6. 处理粗体 (**text** 或 __text__)
        if '**' in line:
            line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
        if '__' in line:
            line = re.sub(r'__(.+?)__', r'<b>\1</b>', line)
        
        # 7. 处理斜体 (*text* 或 _text_) - 在粗体之后处理
        # 使用更精确的正则，避免匹配粗体的一部分
        line = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', line)
        line = re.sub(r'(?<![a-zA-Z0-9_])_(.+?)_(?![a-zA-Z0-9_])', r'<i>\1</i>', line)
        
        # 8. 处理行内代码 (`code`)
        if '`' in line:
            line = re.sub(r'`(.+?)`', r'<code>\1</code>', line)
        
        # 9. 处理链接 ([text](url))
        if re.search(r'\[.+?\]\(.+?\)', line):
            line = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', line)
        
        converted_lines.append(line)
    
    if in_code_block and code_block_content:
        code_text = '\n'.join(code_block_content)
        code_text = escape_html(code_text)
        converted_lines.append(f'<pre>{code_text}</pre>')
    
    result = '\n'.join(converted_lines)
    logger.info(f"[FORMAT] Converted: {result[:200]}...")
    return result


def escape_html(text: str) -> str:
    """转义 HTML 特殊字符"""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


# 测试
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

```python
def hello():
    print("Hello")
```

[链接文本](https://example.com)

~~删除线~~
"""
    
    result = convert_markdown_to_telegram_html(test_text)
    print("转换结果:")
    print(result)
    print("\n\n验证:")
    print("粗体:", '<b>' in result)
    print("斜体:", '<i>' in result)
    print("标题:", '<b>📌' in result)
    print("列表:", '• ' in result)
    print("引用:", '<blockquote>' in result)
