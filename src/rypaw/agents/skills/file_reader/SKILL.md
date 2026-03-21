---
name: file_reader
description: "Read and summarize text-based file types only. Prefer read_file for text formats; use execute_shell_command for type detection when needed. PDF/Office/images/archives are handled by other skills."
metadata:
  {
    "copaw":
      {
        "emoji": "📄",
        "requires": {}
      }
  }
---
# File Reader Toolbox

Use this skill when the user asks to read or summarize local text-based files. PDFs, Office documents, images, audio, and video are out of scope for this skill and should be handled by their dedicated skills/tools.

## Quick Type Check

Use a type probe before reading:

```bash
file -b --mime-type "/path/to/file"
```

If the file is large, avoid dumping the whole content; extract a small, relevant portion and summarize.

## Text-Based Files (use read_file)

Preferred for: `.txt`, `.md`, `.json`, `.yaml/.yml`, `.csv/.tsv`, `.log`, `.sql`, `ini`, `toml`, `py`, `js`, `html`, `xml` source code.

Steps:

1. Use `read_file` to fetch content.
2. Summarize key sections or show the relevant slice requested by the user.
3. For JSON/YAML, list top-level keys and important fields.
4. For CSV/TSV, show header + first few rows, then summarize columns.

## Large Logs

If the file is huge, use a tail window:

```bash
tail -n 200 "/path/to/file.log"
```

Summarize the last errors/warnings and notable patterns.

## Out of Scope

Do not handle the following in this skill (they are covered by other skills):

- PDF
- Office (docx/xlsx/pptx)
- Images
- Audio/Video

## Safety and Behavior

- Never execute untrusted files.
- Prefer reading the smallest portion necessary.
- If a tool is missing, explain the limitation and ask the user for an alternate format.
