"""
Telegram 智能格式后处理器
在 Agent 输出后自动添加 Markdown 格式，优化 Telegram 显示效果
"""
import re


def enhance_text_for_telegram(text: str) -> str:
    """
    智能增强文本格式，使其在 Telegram 上显示更好
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not text:
        return text
    
    original_preview = text[:200]
    logger.info(f"[ENHANCE] Original: {original_preview}...")
    
    lines = text.split('\n')
    enhanced_lines = []
    in_code_block = False
    code_block_content = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # 检测是否已经在代码块中
        if stripped.startswith('```'):
            if in_code_block:
                # 结束代码块
                code_block_content.append(stripped)
                enhanced_lines.extend(code_block_content)
                code_block_content = []
                in_code_block = False
            else:
                # 开始代码块
                in_code_block = True
                code_block_content.append(stripped)
            continue
        
        if in_code_block:
            code_block_content.append(line)
            continue
        
        # 1. 检测类似标题的行（短行，无标点结尾，包含 emoji 或特殊符号）
        # 跳过已有 Markdown 标记的行
        if not stripped.startswith(('#', '-', '*', '>', '```', '`')):
            if _is_like_title(stripped):
                enhanced_lines.append(f"### {stripped}")
                continue
        
        # 2. 检测类似列表的行（以符号开头但不是 Markdown 列表）
        if not stripped.startswith(('-', '*', '+')):
            if _is_like_list_item(stripped):
                enhanced_lines.append(f"- {stripped}")
                continue
        
        # 3. 检测代码行（缩进或多行代码特征）
        if _is_like_code_line(stripped, lines, i):
            if not any('```' in l for l in enhanced_lines[-3:]):
                enhanced_lines.append("```")
            enhanced_lines.append(line)
            continue
        
        # 4. 检测引用（以 > 开头或包含"引用"等词）
        if stripped.startswith('>'):
            enhanced_lines.append(stripped)
            continue
        
        # 默认保持原样
        enhanced_lines.append(line)
    
    # 关闭未结束的代码块
    if in_code_block and code_block_content:
        code_block_content.append("```")
        enhanced_lines.extend(code_block_content)
    
    result = '\n'.join(enhanced_lines)
    logger.info(f"[ENHANCE] Enhanced: {result[:200]}...")
    return result


def _is_like_title(text: str) -> bool:
    """检测是否像标题"""
    if not text:
        return False
    
    # 标题特征：
    # 1. 较短（< 50 字符）
    # 2. 无句号结尾
    # 3. 可能包含 emoji
    # 4. 可能是总结性词语
    
    if len(text) > 50:
        return False
    
    if text.endswith(('。', '.', '！', '!', '？', '?')):
        return False
    
    # 常见标题关键词
    title_keywords = [
        '总结', '总结：', '以下是', '检查', '检查：',
        '状态', '状态：', '结果', '结果：',
        '完成', '完成：', '测试', '测试：',
        '✅', '❌', '⚠️', '📌', '📊', '🧪',
        '##', '###',  # 已有 markdown 标记
    ]
    
    for keyword in title_keywords:
        if keyword in text:
            return True
    
    # 全大写字母（英文标题）
    if text.isupper() and len(text) < 30:
        return True
    
    return False


def _is_like_list_item(text: str) -> bool:
    """检测是否像列表项"""
    if not text:
        return False
    
    # 列表特征：
    # 1. 以符号开头（•, ·, →, -, *, +）
    # 2. 短行
    # 3. 多个相似行
    
    list_symbols = ['•', '·', '→', '▸', '▹', '▪', '▫']
    
    for symbol in list_symbols:
        if text.startswith(symbol):
            return True
    
    return False


def _is_like_code_line(text: str, all_lines: list, current_index: int) -> bool:
    """检测是否像代码行"""
    if not text:
        return False
    
    # 代码特征：
    # 1. 以多个空格或 tab 开头（缩进）
    # 2. 包含代码关键字（def, class, import, return, if, for, while 等）
    # 3. 包含编程符号（{}, (), [], =, :, ;等）
    
    code_keywords = [
        'def ', 'class ', 'import ', 'from ', 'return ',
        'if ', 'else:', 'elif ', 'for ', 'while ', 'try:',
        'except', 'finally:', 'with ', 'as ', 'lambda ',
        'function ', 'const ', 'let ', 'var ', 'public ', 'private ',
    ]
    
    # 检查缩进
    if text.startswith(('    ', '\t')):
        return True
    
    # 检查代码关键字
    for keyword in code_keywords:
        if keyword in text:
            return True
    
    # 检查代码符号模式
    if re.search(r'\w+\s*\([^)]*\)\s*:', text):  # 函数定义
        return True
    
    if re.search(r'\w+\s*=\s*[^=]', text) and not text.endswith(('。', '.')):  # 赋值语句
        return True
    
    return False


# 测试
if __name__ == "__main__":
    test_text = """总结

项目一
项目二
项目三

状态：正常

def hello():
    print("Hello")
    return True

检查完成"""
    
    result = enhance_text_for_telegram(test_text)
    print("原始:")
    print(test_text)
    print("\n增强后:")
    print(result)
