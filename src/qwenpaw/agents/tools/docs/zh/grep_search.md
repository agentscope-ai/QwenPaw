---
summary: 按内容搜索文件，支持正则表达式和上下文
---

按内容搜索文件。

- `pattern`：搜索字符串或正则表达式
- `path`：搜索路径（文件或目录），默认为工作目录
- `is_regex`：是否将 pattern 视为正则表达式（默认 False）
- `case_sensitive`：是否区分大小写（默认 True）
- `context_lines`：显示匹配行前后的上下文行数（默认 0，最大 5）
- `include_pattern`：按文件名筛选，如 `*.py`
- `show_file`：是否在每行输出文件名（默认 True）；设为 False 时多文件按文件分组，每文件仅展示一次文件名，文件组之间以 `---` 分隔
