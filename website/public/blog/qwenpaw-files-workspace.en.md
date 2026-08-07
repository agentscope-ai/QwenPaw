---
title: "From File Tree to Files Workspace: Making an Agent's Working Directory Visible"
date: 2026-08-07
author: QwenPaw Team
tags: [Files, File Tree, Files Workspace, File Preview, Agent]
cover: https://img.alicdn.com/imgextra/i4/O1CN01pEZk6a8g9lK3gjEp_!!6000000001665-2-tps-1817-866.png
excerpt: "QwenPaw's latest Files workspace brings directory browsing, file preview, editing, diff review, uploads, downloads, and Chat references into one surface, keeping Agent file state visible, inspectable, and controllable."
---

# From File Tree to Files Workspace: Making an Agent's Working Directory Visible

When an Agent only answers questions, the chat transcript can feel like the whole workspace. Once the task becomes “read a set of materials, change a project, generate a report, and preserve long-term memory,” the durable state is no longer in the chat box. It is in files.

Files are the Agent's working memory and the shared language people use to inspect results, take over a task, and continue collaborating. Yet a traditional file entry point is often just a list: it shows names, but makes browsing, understanding, editing, and reviewing feel like separate jobs.

QwenPaw's latest **Files workspace** starts from that gap. It turns the file tree from a navigation control into one working surface where users can browse, preview, edit, review, and reference files without losing context.

![Files workspace overview](https://img.alicdn.com/imgextra/i4/O1CN01GjiXT3fTIrJ5Bkx9_!!6000000006529-2-tps-2556-1223.png)

## 01 Agents Really Work in Files

A typical Agent task moves through a loop like this:

1. Read code, configuration, or reference material from a project directory;
2. Analyze it in Chat and propose a change;
3. Write the result back, or create a new document or media file;
4. Let a person preview, edit, compare, and reference the result in Chat again;
5. Continue using project files, Profile, and Memory in later sessions.

When these steps are split across chat attachments, a separate coding page, downloaded files, and the operating system's file manager, users have to keep asking where a file belongs, which version they are looking at, and which directory an edit will affect. The Agent has to switch between paths and APIs too, making file context fragile.

The goal of the Files workspace is not to rebuild a full IDE. It is to give the most common file actions in Agent work a stable and explainable entry point: **find the file, understand it, edit it when needed, and bring the result back into the task.**

## 02 One Unified Files Workspace

This update brings file experiences that used to be spread across Chat, Agent Workspace, and the Coding page into one Files domain. It is composed of three connected layers:

- **File tree:** expand directories, identify file types, and load children page by page;
- **File preview:** inspect Markdown, images, PDFs, CSVs, and plain text without leaving the task;
- **Editing workspace:** open multiple files in Monaco while preserving tabs, cursors, and undo state.

Clicking an attachment in Chat opens a Preview drawer first instead of downloading immediately. When more room is needed, the drawer expands into the full Workspace. Opening Files from the sidebar goes directly to the full workspace. The two entry points reuse navigation, preview, and editing, while keeping Agent-level and Session-level tab state separate so two work scenes do not leak into each other.

![Chat file preview drawer](https://img.alicdn.com/imgextra/i3/O1CN01TTmgqymDpqH5CGAk_!!6000000002889-0-tps-2560-1226.jpg)

## 03 A File Tree Is More Than a List of Names

### Read from the root, one level at a time

The tree does not recursively load an entire directory on first render. It reads the immediate children of the current directory, then requests the next page when a folder is expanded. The backend limits page size and relative-path length, rejects traversal, and re-checks the resolved target when symbolic links are involved.

This keeps ordinary projects quick to enter and gives Project Directory changes a clear boundary. Paths cross the API boundary in a normalized relative POSIX form, while drive letters, backslashes, and reserved Windows names are handled for cross-platform behavior.

### Two directory identities, one tree

An Agent needs two kinds of directories at the same time:

| Directory                     | What it contains                                                  | When to use it                                    |
| ----------------------------- | ----------------------------------------------------------------- | ------------------------------------------------- |
| Project Directory             | User projects, code, references, Git workspaces, and task outputs | Work on the current project                       |
| Agent Configuration Directory | Profile, Memory, sessions, skills, caches, and QwenPaw-owned data | Inspect Agent configuration and long-term context |

Files keeps both identities in one navigator with a root switcher. If the two paths resolve to the same directory, the UI collapses them into one identity instead of displaying duplicates.

The workspace also exposes **Profile** and **Memory** sources. Profile files can be enabled, disabled, and reordered; Memory continues to use its daily-note and digest APIs. Both reuse the same preview and editing surface without losing their domain semantics.

## 04 From “Take a Look” to “Change One Thing”: Preview, Edit, and Diff

Text files can switch between Preview and Edit. The editor keeps a model per path, so changing tabs preserves the cursor, undo stack, and unsaved edits. Markdown, code, configuration, and CSV can live in the same workspace; images and PDFs remain read-only previews.

When an external process changes a file, the workspace detects the update and surfaces the difference between the current editor content and the disk version. Each hunk can be **Kept** or **Undone**, or all changes can be accepted or reverted at once. Saving remains an explicit user action; `Cmd/Ctrl+S` writes the confirmed text back to the original file.

This interaction addresses a common Agent collaboration moment: the Agent may have produced a result, but the person wants to inspect each part before it enters the project. Diff does not decide for the user—it puts the context needed for that decision in one place.

## 05 Uploads, Downloads, and Chat References

The workspace covers both ends of a file task:

- Upload files to the selected Project Directory or Agent Configuration Directory;
- Download files from the workspace;
- When a name already exists, choose rename, skip, or overwrite;
- Copy a file or selected code back to Chat;
- Move from Chat file cards and tool-produced files back to the same Preview / Workspace.

A reference is more than pasted text. Files preserves the path and, when relevant, line information, so the user can see exactly which file and region the Agent is being shown. If a historical attachment cannot be safely resolved under the current Project Directory or Agent Configuration Directory, it falls back to a read-only preview instead of pretending it is editable.

## 06 Project Directory: The Runtime Boundary Behind the Tree

A file tree is only useful when the Agent's tools and the user's view point to the same directory. Project Directory is therefore a runtime concept rather than a setting owned by the old Coding page:

- An Agent can define a default Project Directory;
- An individual Chat Session can override it;
- The override is persisted and affects reads, saves, uploads, downloads, and file watching;
- Shell, code analysis, Git, and related tools use the same effective directory.

After switching directories in Files, users do not need to repeat the setting elsewhere. The Agent will not write to one directory while the UI presents the result as if it came from another.

## 07 A Typical File Workflow

Suppose you ask an Agent to prepare release notes for a project:

1. Describe the goal in Chat and let the Agent read changelogs and documents from the Project Directory;
2. Click the generated Markdown file and check its structure in Preview;
3. Expand into the Workspace and adjust wording or add a section in Monaco;
4. If the Agent or another tool changes the file again, review each hunk with Keep / Undo;
5. Copy a key section or file reference back to Chat so the Agent can continue with your feedback;
6. Return to the Files workspace, confirm the final version, and download it for delivery.

In this loop, Chat carries intent, files carry state, Preview and Diff support review, and the Files workspace keeps the entire flow in one visible context.

## 08 Safety Boundaries and Current Trade-offs

Files works with local data, so the safety boundary must be more precise than “can this file open?” The backend checks sensitive paths, workspace containment, traversal, Windows reserved names, and symbolic-link escapes. Writes are atomic, and upload conflicts never silently replace an existing file.

The update also does not present unfinished optimization as IDE-grade performance. The backend already exposes paged directory and chunked content APIs, but the frontend still assembles a complete text file before rendering it. Very large directories are not virtualized yet, and file-tree search remains planned. These trade-offs keep the current experience stable and explainable for ordinary Agent work; larger repositories will benefit from progressive rendering, cancellation, bounded caches, and directory search in follow-up work.

## 09 Next: A More Progressive File Experience

The next phase is not simply more buttons. It is keeping the same sense of certainty as workspaces grow:

- Show the first chunk of a large file before loading the rest;
- Cancel unnecessary chunk requests when switching tabs;
- Add virtualization and search for large directories;
- Add a clear concurrent-edit conflict state and recovery flow around the existing ETag check;
- Continue refining full-screen file behavior on mobile and narrow windows.

The principle stays the same: make file state visible first, make Agent actions controllable next, and extend performance to larger projects without obscuring what is happening.

## Summary

A file tree may look like a small component, but it connects an Agent's project directory, configuration, memory, tool outputs, and user feedback. QwenPaw's Files update organizes that chain into one workspace, keeping directory navigation, content review, and file changes aligned around the same paths and state.

From expanding a directory to previewing, editing, diffing, uploading, downloading, and referencing files in Chat, the user is looking at one coherent work state. For the Agent, that means fewer path ambiguities. For the user, it means a clearer answer to what the Agent is reading, what it is changing, and what still needs human confirmation.

Related implementation notes:

- [QwenPaw #6504: Unified Files Workspace](https://github.com/agentscope-ai/QwenPaw/pull/6504)
