---
summary: Search by content, supports regex and context
---

Search by content.

- `pattern`: Search string or regex pattern
- `path`: Search path (file or directory), defaults to working directory
- `is_regex`: Treat pattern as regex (default False)
- `case_sensitive`: Case-sensitive matching (default True)
- `context_lines`: Context lines before/after match (default 0, max 5)
- `include_pattern`: Filter by filename, e.g. `*.py`
- `show_file`: Include file path on every output line (default True). When False, multi-file results group by file with the path shown once per file and `---` between file groups
