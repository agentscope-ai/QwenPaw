---
summary: Read file contents, supports line range reading
---

Read file contents.

- Specify `start_line` and `end_line` to read specific line ranges
- Large files are automatically truncated (default 50KB), with instructions to use `start_line` to continue
- Truncation shows total line count and next starting line number
