---
name: guidance
description: "Answer user questions about QwenPaw installation and configuration: first locate and read local documentation, then distill the answer; if local information is insufficient, fall back to the official website documentation."
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🧭"
    requires: {}
---

# QwenPaw Installation and Configuration Q&A Guide

Use this skill when the user asks about **QwenPaw installation, initialization, environment configuration, dependency requirements, or common configuration options**.

Core principles:

- Check local documentation first, then answer
- Base answers on what has actually been read, do not speculate
- Answer in the same language the user used to ask

## Standard Flow

### Step 1: Locate the Documentation Directory

**Check for documentation directory in memory**

First, check whether there is a documentation directory in memory. If found, use it directly; otherwise, proceed to the next step.

```bash
# Get the documentation directory from memory
DOC_DIR=$(find ~/.qwenpaw/memory/ -type d -name "docs")
```

If there is no documentation directory in memory, continue with the following logic.

**Check the documentation directory in the project source code**

Run the following script logic to obtain the variable $QWENPAW_ROOT:

```bash
# Get the absolute path of the binary
COP_PATH=$(which qwenpaw 2>/dev/null || whereis qwenpaw | awk '{print $2}')

# Logical deduction: if the path contains .qwenpaw/bin/qwenpaw, the root is three levels up
# Example: /path/to/QwenPaw/.qwenpaw/bin/qwenpaw -> /path/to/QwenPaw
if [[ "$COP_PATH" == *".qwenpaw/bin/qwenpaw" ]]; then
    QWENPAW_ROOT=$(echo "$COP_PATH" | sed 's/\/\.qwenpaw\/bin\/qwenpaw//')
else
    # Fallback: try to get the parent of the parent directory
    QWENPAW_ROOT=$(dirname $(dirname "$COP_PATH") 2>/dev/null || echo ".")
fi

echo "Detected QwenPaw Root: $QWENPAW_ROOT"
```

Verify and list the documentation directory:
Use the derived $QWENPAW_ROOT to locate the documentation:

```bash
# Construct the standard documentation path
DOC_DIR="$QWENPAW_ROOT/website/public/docs/"

# Check if the path exists and list files
if [ -d "$DOC_DIR" ]; then
    find "$DOC_DIR" -type f -name "*.md" | head -n 100
else
    # If the derived path is incorrect, perform a global fuzzy search
    find "$QWENPAW_ROOT" -type d -name "docs" | grep "website/public/docs"
fi
```

**If project documentation does not exist, search the working directory**

If documentation is still not found, search for available documentation content under the qwenpaw installation path:

```bash
# Look for characteristic files such as faq.en.md or config.zh.md
FILE_PATH=$(find . -type f -name "faq.en.md" -o -name "config.zh.md" | head -n 1)
if [ -n "$FILE_PATH" ]; then
    # Use dirname to get the directory containing the file
    DOC_DIR=$(dirname "$FILE_PATH")
fi
```

If a documentation directory is found, save it in memory in this format:

```markdown
# Documentation Directory
$DOC_DIR = <doc_path>
```

### Step 2: Documentation Search and Matching

Documentation files follow the naming format `<topic>.<lang>.md` (e.g., `config.zh.md`, `config.en.md`, `quickstart.zh.md`).

Use the find command to list all matching documents in the target directory, and identify the target as <doc_path> based on filename keywords (e.g., install, env, setup).

```bash
# List all matching documents
find $DOC_DIR -type f -name "*.md"
```

If no suitable document is found, read all documentation contents in the next step.

### Step 3: Read the Documentation Content

After finding candidate documents, read and identify the paragraphs relevant to the question. You can use:

- `cat <doc_path>`
- `file_reader` skill (recommended for longer documents or paginated reading)

If the documentation is long, prioritize reading the sections most relevant to the question (installation steps, configuration options, example commands, notes, version requirements).

### Step 4: Extract Information and Respond

Extract key information from the documentation and organize it into an actionable answer:

- Give the direct conclusion first
- Then provide steps / commands / configuration examples
- Include necessary prerequisites and common pitfalls

Language requirement: the answer language must match the language of the user's question (answer in Chinese if asked in Chinese, answer in English if asked in English).

### Step 5 (Optional): Official Website Lookup

If the previous steps cannot be completed (no local documentation, missing documentation, or insufficient information), use the official website as a fallback:

- http://qwenpaw.agentscope.io/

Answer based on the content available from the official website, and clearly state in the answer that the conclusion comes from the official website documentation.

## Output Quality Requirements

- Do not fabricate non-existent configuration options or commands
- When there are version differences, clearly note "please refer to the current documentation version"
- For paths, commands, and configuration keys, provide copy-pasteable original snippets whenever possible
- If information is still insufficient, clearly state the gaps and tell the user what additional information is needed (e.g., operating system, installation method, error logs)
