# Unified Files Workspace — Current Implementation Handoff

> Last verified: 2026-07-28
>
> Branch: `feat/unified-files-workbench`
>
> Base: `upstream/main@b0553ff4`
>
> Current implementation head: `7f105b15`
> Draft PR: [agentscope-ai/QwenPaw#6504](https://github.com/agentscope-ai/QwenPaw/pull/6504)

This document describes the implementation that exists on the branch today.
It is intended to let the next engineer resume work without reconstructing the
full design and review history.

The current code is the source of truth for implementation details. The earlier
documents remain the source of truth for product intent, except where this
document records a later, explicitly confirmed product decision.

## 1. Read these first

1. [Final product proposal](./UNIFIED_FILES_PROPOSAL.md)
2. [Original engineering handoff](./UNIFIED_FILES_HANDOFF.md)
3. [Final interaction mock](./options/option-d-progressive-workspace.html)
4. [Unified Project Directory proposal](../../proposals/project-directory/PROJECT_DIRECTORY_PROPOSAL.md)
5. This document

The mock is a behavior reference, not a production styling reference. The
production UI follows QwenPaw's orange visual language, dark mode, existing
responsive conventions, and i18n. Do not reintroduce the mock's green accent.

## 2. Current outcome

The branch has moved the product from separate Chat, Agent Workspace, and
Coding-page file experiences to one Files domain:

- Chat remains the primary surface.
- Clicking a file in Chat opens a left Preview drawer.
- Preview occupies 30% by default; Chat retains 70%.
- Expanding Preview opens the full Workspace at 75%; Chat retains 25%.
- Chat stays mounted while Preview or Workspace is open.
- The sidebar Files entry opens the full Files workspace directly and hides
  Chat.
- The old production `/coding` page and Chat-to-Coding redirect are removed.
- The existing Monaco editor, previewer, live diff, Keep/Undo, and copy-to-Chat
  capabilities are reused inside the shared Files workspace.
- Project Directory is a general runtime concept and is no longer owned by
  Coding tools.
- Enhanced code capability is an option under ReAct Agent configuration, not a
  standalone page or tab.
- Chat Artifacts were deliberately removed from both frontend and backend.

The implementation is substantial but not identical to every detail in the
original mock. Section 10 records the remaining gaps and retained legacy code.

## 3. Product decisions that must not regress

These decisions include later review feedback and therefore override
contradictory details in the older handoff or mock.

### 3.1 Files and Chat

- There is one Files domain; do not recreate separate "My Files" and "Chat
  Artifacts" concepts.
- Files belongs under the sidebar Workspace group.
- A message attachment or tool-produced file opens Preview first; it must not
  download immediately.
- File cards do not expose a hover download action. Download belongs in Preview
  or Workspace.
- Clicking "Mention in Chat" inserts the reference but keeps Preview open.
- Files opened from a historical attachment are read-only only when the file
  cannot be resolved under the current Project Directory or Agent
  Configuration Directory.
- Multimedia-producing tool cards expand by default.
- Ordinary file tools remain compact and expose a blue Preview text action
  instead of a large extra preview block.

### 3.2 Directory model

`workspace_dir` and `project_dir` have different responsibilities:

| Directory | Responsibility |
| --- | --- |
| `workspace_dir` | Agent configuration, Profile files, Memory, sessions, skills, caches, and other QwenPaw-owned data |
| `project_dir` | User task files, relative file operations, Shell cwd, code analysis, Git operations, and project-bound runtime state |

The effective directory for a normal Chat turn is:

```text
validated fork or active-mode override
  > trusted request/session project_dir
  > Agent project_dir
  > workspace_dir fallback
```

The user-facing Files navigator has:

- source tabs: `Files`, `Profile`, and `Memory`;
- inside `Files`, one directory-root switcher between Project Directory and
  Agent Configuration Directory;
- visually different root identities;
- only Agent Configuration Directory when both paths resolve to the same
  directory.

Do not turn the two directory roots into separate top-level tabs.

### 3.3 Project Directory and enhanced code capability

- The Agent default Project Directory is configured under ReAct Agent.
- A Chat session can override it without changing the Agent default.
- The current session directory is editable directly from the Files navigator
  and from the compact Chat sender control.
- Enhanced code capability only changes the available code-oriented tools,
  prompts, Git context, and source-control UI.
- Toggling enhanced code capability must not change either the Agent or Session
  Project Directory.

### 3.4 Composer references

The composer renders file references as compact blue atomic chips while
preserving the exact raw text sent to the backend.

| User action | Visible composer form | Raw submitted form |
| --- | --- | --- |
| Mention a file from Preview | File chip | `@ <path>` |
| Copy complete Monaco lines | File + line-range chip | `<path>:<start>-<end>` |
| Copy a partial Monaco selection | Line-range chip plus expandable code chip | `<path>:<start>-<end>` followed by a fenced code block |

Atomic chips delete as a unit. They must not reveal or overlap their raw
backing text on focus. Normal cursor placement, IME composition, send-to-clear,
and Arrow Up/Down history behavior must continue to work.

## 4. Runtime architecture

```text
Agent configuration
  ├── workspace_dir
  ├── project_dir
  └── coding_mode.enabled
          │
ChatSpec.meta.runtime_context.project_dir
          │
          ▼
resolve_effective_project_dir()
          │
          ├── Console request_context.project_dir
          ├── current_project_dir ContextVar
          ├── environment/system prompt
          ├── file and search tools
          ├── Shell default cwd
          ├── AST/LSP/Git tools
          ├── governance and file guards
          ├── Mission source/run directory
          └── Files API root="project"

workspace_dir remains the base for Agent-owned internal data.
```

### 4.1 Session persistence and turn injection

The session-level path is not frontend-only state:

1. `PUT /chats/{chat_id}/project-dir` validates the directory.
2. `ChatManager.set_project_dir()` stores it under
   `ChatSpec.meta.runtime_context.project_dir`.
3. Both synchronous streaming and background Console execution resolve the
   effective path before dispatch.
4. The resolved path and source are inserted into
   `request_context["project_dir"]` and
   `request_context["project_dir_source"]`.
5. Runtime config snapshots, ContextVars, tools, guards, and the environment
   prompt consume that request value.

For a newly created frontend session that has no backend `chat_id` yet,
`SessionProjectDirectory` stores a pending selection by Agent and frontend
session. The first send includes it as `session_project_dir`; the Console route
validates and persists it before the turn starts.

Relevant files:

- `src/qwenpaw/services/project_directory.py`
- `src/qwenpaw/app/chats/api.py`
- `src/qwenpaw/app/chats/manager.py`
- `src/qwenpaw/app/routers/console.py`
- `src/qwenpaw/hooks/request_setup/contextvars_hook.py`
- `src/qwenpaw/runtime/builder.py`
- `console/src/features/project-directory/SessionProjectDirectory.tsx`
- `console/src/features/project-directory/pendingProjectDirectory.ts`

### 4.2 Prompt and tool behavior

`build_env_context()` exposes the effective Project Directory to the model. If
it differs from the Agent workspace, both are described with separate
responsibilities.

The following user-task operations prefer `current_project_dir`:

- file I/O;
- file search;
- Shell;
- AST;
- LSP;
- Git and coding helpers;
- file/rule guardians and governance.

Profile, Memory, Agent configuration, sessions, and other internal data keep
using `workspace_dir`.

### 4.3 Configuration migration

`AgentProfileConfig.project_dir` is the canonical Agent-level field.
`CodingModeConfig` retains only capability state such as `enabled`.

The migration:

1. preserves an existing top-level `project_dir`;
2. otherwise moves a valid legacy `coding_mode.project_dir` to the top level;
3. removes the legacy nested field;
4. writes migrated configuration through the existing backup/write path.

Do not add a permanent compatibility field or a second project-directory
resolver.

## 5. Frontend implementation map

### 5.1 Shared Files shell

| File | Responsibility |
| --- | --- |
| `console/src/features/files-workspace/FilesDrawer.tsx` | Preview/full-workspace shell, resizing, download, mention, expand/collapse |
| `console/src/features/files-workspace/filesDrawerState.ts` | Closed/Preview/Workspace state machine |
| `console/src/features/files-workspace/FilesWorkspace.tsx` | Navigator + editor composition, attachment resolution, save/download routing |
| `console/src/features/files-workspace/FilesNavigator.tsx` | Files/Profile/Memory sources, root switcher, paged tree, Profile toggles, upload conflicts |
| `console/src/features/files-workspace/directorySources.ts` | Cross-platform path normalization and root collapsing |
| `console/src/features/files-workspace/internalFileLinks.ts` | Safe internal file target parsing and preview URL mapping |
| `console/src/features/files-workspace/FilesWorkspace.module.less` | Orange theme, dark mode, sizing, responsive behavior |

Drawer state:

```text
closed
  ├── OPEN_PREVIEW  ──> preview
  │                       └── EXPAND_WORKSPACE ──> workspace(origin=chat)
  │                                                   └── COLLAPSE ──> preview
  ├── OPEN_WORKSPACE ─> workspace(origin=chat)
  └── OPEN_FILES ─────> workspace(origin=files)
```

`OPEN_WORKSPACE` is used for editor-origin references that should open directly
in the IDE surface. `OPEN_FILES` is the sidebar entry and does not require an
intermediate Preview.

### 5.2 Chat integration

`console/src/pages/Chat/index.tsx` owns the drawer reducer and keeps
`AgentScopeRuntimeWebUI` mounted beside it. The parent flex layout changes
available width rather than replacing the Chat route.

Current desktop defaults:

- Preview: 30%;
- full Workspace: 75%;
- minimum Files drawer width: 420 px;
- minimum Chat width: 420 px.

At widths up to 1024 px, Chat's minimum is 300 px. At mobile widths the Files
surface becomes a full overlay and Chat is hidden without being unmounted.
User-resized Preview and Workspace widths are stored separately in
`localStorage`.

The sidebar Files item routes to Chat if needed and then dispatches
`qwenpaw:open-files`. This avoids a second Files route and preserves one shared
state model.

### 5.3 Preview and IDE

The full workspace reuses:

- `console/src/pages/Coding/TabbedEditor.tsx`;
- `console/src/pages/Coding/FilePreview.tsx`;
- `console/src/stores/codingTabsStore.ts`;
- Monaco `Editor` and `DiffEditor`.

Implemented behavior includes:

- file tabs and model-per-path cursor/undo preservation;
- Markdown, image, PDF, CSV, and plain-text Preview;
- Preview/Edit switching;
- line numbers and syntax highlighting;
- editable Project, Agent Configuration, Profile, and Memory text files;
- `Cmd/Ctrl+S`;
- live filesystem change detection;
- inline diff with Keep All/Undo All;
- per-hunk Keep/Undo;
- copy file or selection to Chat;
- attachment-to-real-file resolution before enabling edit;
- read-only historical fallback when resolution is impossible.

`TabbedEditor` receives source-aware load/save callbacks from
`FilesWorkspace`; do not revert it to Coding-only `/code-files` APIs.

### 5.4 Rich Chat composer

The compact reference implementation is:

- `console/src/pages/Chat/RichFileReferenceInput.tsx`;
- `console/src/pages/Chat/fileReferenceFormatting.ts`;
- `console/src/pages/Coding/editorCopyFormatting.ts`;
- `console/src/pages/Coding/lastEditorCopy.ts`.

It uses Lexical `DecoratorNode`s for file and code chips. A hidden textarea is
only the bridge required by the current AgentScope Chat sender contract; the
visible editable surface is Lexical.

The AgentScope package does not yet expose the required custom-input behavior
directly. The integration therefore depends on:

```text
console/patches/@agentscope-ai+chat+1.1.72-beta.1783494781362.patch
```

Do not remove this patch merely because the visible editor works. First verify
that the installed SDK version natively supports the same controlled custom
input, clearing, key handling, attachment clearing, and sender actions.

### 5.5 Tool-produced files and media

The relevant components are under:

```text
console/src/components/Chat/ToolCards/
```

Current rules:

- image/video/audio/file media output expands its tool card by default;
- `send_file` expands when media metadata is present;
- batched tools expand when any media item is present;
- read/write/edit/append expand only for multimedia preview content;
- non-media file operations expose `FileAttachmentPreview`, a compact blue
  Preview action;
- file previews dispatch the same `qwenpaw:open-file-preview` event used by
  Chat attachments.

### 5.6 Agent configuration

`console/src/pages/Agent/Config/components/ReactAgentCard.tsx` contains two
separate controls:

- Default Project Directory;
- Enhanced code capability.

They intentionally call separate APIs and stores. Do not merge them into one
toggle or move the directory under the coding capability.

## 6. Files and Project Directory APIs

All Project-root Files requests include `X-Chat-Id` when a backend Chat exists,
so the backend can use the Session override rather than only the Agent default.

### 6.1 Shared Files API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/workspace/tree` | Page immediate directory children |
| `GET` | `/workspace/file-metadata` | Read size, type, modified time, and ETag before content |
| `GET` | `/workspace/file-content` | Read a bounded UTF-8-safe byte chunk |
| `PUT` | `/workspace/file-content` | Atomic text save; supports `If-Match` |
| `GET` | `/workspace/file-download` | Stream a file |
| `POST` | `/workspace/file-upload` | Stream uploads with duplicate policy |

Every endpoint accepts `root=project|workspace`. Project root resolves the
current Session/Agent effective directory; workspace root resolves the Agent
Configuration Directory.

Important constants in `src/qwenpaw/services/workspace_files.py`:

- default directory page: 200 entries;
- maximum directory page: 500 entries;
- default file chunk: 256 KiB;
- maximum file chunk: 1 MiB;
- maximum relative path bytes: 4096.

Filesystem work is guarded by a semaphore and dispatched with
`asyncio.to_thread()`. Paths are normalized as relative POSIX paths at the API
boundary, checked for traversal and Windows-reserved names, and revalidated
against symlink escape.

### 6.2 Upload conflicts

The initial upload request has no policy. If no duplicate exists, upload starts
without a modal. If a duplicate exists, the backend returns:

```json
{
  "detail": {
    "code": "upload_conflict",
    "files": ["duplicate.txt"]
  }
}
```

Only then does the frontend ask for one of:

- Rename: select the first available `name (n).ext`;
- Skip: preserve the existing file;
- Overwrite: atomically replace it.

The current Files UI uploads into the root of the selected Project or Agent
Configuration Directory. The API already accepts a subdirectory `path`, but
the current navigator does not expose "upload into selected folder."

### 6.3 Project Directory API

| Method | Endpoint | Scope |
| --- | --- | --- |
| `GET/PUT` | `/project-directory` | Agent default |
| `GET` | `/project-directory/list` | Known/imported project choices |
| `GET` | `/project-directory/browse` | Directory browser |
| `GET/PUT/DELETE` | `/chats/{chat_id}/project-dir` | Session effective value, set override, clear override |

Create, clone, ZIP import, and local-directory import remain available through
the existing Project selection modal.

## 7. Profile and Memory

Profile and Memory reuse the same Preview and editor surfaces, but retain
domain-specific APIs:

- Profile is the managed set of Agent Markdown prompt files.
- Each Profile row can be enabled or disabled in the system prompt.
- Enabled Profile files can be reordered by drag and drop; order is persisted
  in `system_prompt_files`.
- The complete Agent Configuration Directory is browsed through the Files root
  switcher, not through Profile.
- Memory lists daily memory files and supports preview/edit through the shared
  editor.

This distinction is important: Profile is not a renamed full workspace tree.
The full `workspace_dir` tree is Agent Configuration Directory under Files.

## 8. What was removed

The following old product paths must not be restored as compatibility layers:

- standalone `/coding` frontend route;
- Chat redirect to `/coding`;
- standalone Agent Workspace page;
- old Coding page shell and route-specific Chat embedding;
- standalone global Memory navigation;
- Chat Artifacts frontend and backend;
- hover download button on message file cards;
- `coding_mode.project_dir` as active configuration.

Some reused files and API names still contain "Coding" for historical reasons.
That does not mean a Coding page still exists.

## 9. Original design versus current code

| Area | Original target | Current state |
| --- | --- | --- |
| One Chat + Files domain | Required | Implemented |
| Preview then expandable workspace | Required | Implemented |
| Preview/Chat 3:7 | Required after review | Implemented as 30%/70% |
| Workspace/Chat 3:1 | Required after review | Implemented as 75%/25% |
| Chat remains mounted | Required | Implemented |
| Direct sidebar Files | Required | Implemented through Chat + event, with Chat hidden |
| Workspace/Profile/Memory | Required | Implemented |
| Chat Artifacts source | Present in an early interpretation | Deliberately removed |
| Project and Agent configuration roots | Added by later project-directory design | Implemented as one root switcher |
| Collapse identical roots | Required after review | Implemented |
| Profile prompt toggles and order | Required | Implemented |
| Preview/Edit with existing IDE | Required | Implemented with Monaco |
| Live diff and rollback | Required | Implemented, including per-hunk actions |
| Rich atomic references | Required after review | Implemented with Lexical |
| Partial editor copy with code chip | Required after review | Implemented |
| Tool media default expansion | Required after review | Implemented |
| Upload conflict only on duplicate | Required after review | Implemented |
| General `project_dir` | Project Directory proposal | Implemented for normal and coding turns |
| Session `project_dir` | Project Directory proposal | Persisted and injected into both execution paths |
| Enhanced code as Agent option | Required after review | Implemented |
| Orange QwenPaw visual language | Required after review | Implemented |
| Dark mode and i18n | Required | Implemented on new surfaces |
| Directory pagination | Required | Implemented |
| Metadata before content | Required | Implemented |
| Bounded content chunks | Required | Backend implemented; frontend currently assembles the complete text |
| Tree virtualization/search | Desired performance work | Not implemented |
| Full HTTP Range download | Desired in old handoff | Not implemented; response advertises `Accept-Ranges` but streams the full file |

## 10. Known gaps and retained legacy code

These are the highest-value places for follow-up work. They are not permission
to refactor unrelated code.

### 10.1 Git remains conditional, not deleted

`FilesWorkspace.tsx` still mounts an activity rail and `GitPanel` when enhanced
code capability is enabled. With the capability disabled, the rail is hidden.

This is the current branch behavior. PR
[agentscope-ai/QwenPaw#6269](https://github.com/agentscope-ai/QwenPaw/pull/6269)
was discussed, but Git removal was explicitly deferred. Before deleting the
rail, panel, watcher, fork, or mission Git behavior, make a new product decision
and account for #6269's final merged architecture.

### 10.2 Historical Coding names remain

The shared workspace intentionally reuses:

- `pages/Coding/TabbedEditor.tsx`;
- `pages/Coding/FilePreview.tsx`;
- `pages/Coding/GitPanel.tsx`;
- `codingTabsStore`;
- `codingModeStore`;
- `/coding-mode`;
- older `/workspace/code-files` APIs.

The production route is gone, but not every internal symbol was renamed. Avoid
a broad rename inside this feature PR unless it has a concrete maintenance
benefit and dedicated test coverage.

The new shared Files tree/editor uses the new source-aware APIs. The older
`/workspace/code-files` family remains for existing callers and is not the
contract to extend for new Files work.

### 10.3 Large-file frontend behavior is only partially progressive

The backend offers metadata-first and bounded chunk reads. The frontend
`loadFileText()` currently requests chunks in a loop and concatenates the whole
file before rendering it.

The following original performance work remains:

- render the first chunk without waiting for the full file;
- explicit large-file/truncation UX;
- cancellation between chunk requests when switching tabs;
- bounded content cache;
- virtualized very large directories;
- file search within the navigator.

### 10.4 Optimistic concurrency is not fully wired through the editor

The save endpoint supports `If-Match`, but the shared editor currently calls
`saveFileContent()` without the metadata ETag. A follow-up should carry the ETag
into tab state and provide a real 409 conflict UX before claiming end-to-end
optimistic concurrency.

### 10.5 Download Range behavior

`/workspace/file-download` sets `Accept-Ranges: bytes`, but does not parse a
request `Range` header or return `206 Partial Content`. Either implement the
complete contract or remove the misleading header in a focused follow-up.

### 10.6 Workspace activity rail

The original mock had a persistent activity rail. Later review called its
single Files icon redundant. Current code keeps the rail only when enhanced
code capability is on because it switches Files/Git. If Git is later removed,
remove the now-redundant rail at the same time.

## 11. High-risk regression checklist

Before changing the Files, editor, sender, or Project Directory code, verify:

- [ ] Clicking a message file opens Preview and does not download.
- [ ] Mention in Chat inserts a compact chip and does not close Preview.
- [ ] The backend receives the exact raw reference text.
- [ ] A reference deletes atomically.
- [ ] Clicking/focusing the composer does not reveal overlapping raw text.
- [ ] Sending clears both the visible Lexical editor and SDK textarea state.
- [ ] Arrow Up/Down still restores Chat input history.
- [ ] IME input and cursor placement still behave normally.
- [ ] Full-line Monaco copy/paste creates only a line-reference chip.
- [ ] Partial-line copy/paste creates a line-reference chip and code chip.
- [ ] The code chip expands to a readable code preview.
- [ ] Preview/Edit uses Monaco with line numbers and syntax highlighting.
- [ ] `Cmd/Ctrl+S` after Undo does not write an empty file.
- [ ] External/agent file changes produce a live diff.
- [ ] Keep All, Undo All, Keep hunk, and Undo hunk work.
- [ ] Tool cards with multimedia open expanded by default.
- [ ] Non-media file tools show only the compact blue Preview action.
- [ ] Project and Agent Configuration roots resolve independently.
- [ ] Identical roots collapse to Agent Configuration Directory only.
- [ ] Profile toggles change `system_prompt_files`.
- [ ] Upload opens a conflict dialog only after a backend 409.
- [ ] A Session Project Directory survives refresh and affects the next turn.
- [ ] The prompt reports the Session Project Directory, not just the Agent
      default.
- [ ] Relative file and Shell operations use that same Session directory.
- [ ] Chat remains usable at the 420 px desktop minimum.
- [ ] Light mode, dark mode, Chinese, and English are checked.

## 12. Tests and acceptance evidence

### 12.1 Frontend

The latest recorded validation at implementation head `7f105b15`:

```bash
cd console
npm run test:run -- \
  src/pages/Chat \
  src/pages/Coding/TabbedEditor.copy.test.ts \
  src/pages/Coding/TabbedEditor.test.tsx
npm run build
```

Result:

- 15 test files passed;
- 146 tests passed;
- production build passed;
- build emitted only existing chunk-size warnings.

Important focused tests:

- `console/src/features/files-workspace/filesDrawerState.test.ts`
- `console/src/features/files-workspace/FilesDrawer.test.tsx`
- `console/src/features/files-workspace/internalFileLinks.test.ts`
- `console/src/features/files-workspace/directorySources.test.ts`
- `console/src/pages/Chat/RichFileReferenceInput.test.tsx`
- `console/src/pages/Chat/fileReferenceFormatting.test.ts`
- `console/src/pages/Coding/TabbedEditor.copy.test.ts`
- `console/src/pages/Coding/TabbedEditor.test.tsx`
- `console/src/components/Chat/ToolCards/shared/FileAttachmentPreview.test.tsx`
- `console/src/components/Chat/ToolCards/cards/SendFileCard.test.tsx`

### 12.2 Backend

The branch contains focused coverage in:

- `tests/unit/services/test_project_directory.py`
- `tests/unit/services/test_unified_workspace_files.py`
- `tests/unit/app/routers/test_workspace_files_router.py`
- `tests/unit/routers/test_console_project_directory.py`
- `tests/unit/app/chats/test_manager.py`
- `tests/unit/runtime/test_coding_project_override.py`
- `tests/integration/test_coding_project.py`

The recorded backend validation used the `Codex-QwenPaw` conda environment and
passed 97 relevant tests. Run the current focused set again after backend
changes rather than relying only on that historical result.

Suggested command pattern:

```bash
conda run -n Codex-QwenPaw pytest -q \
  tests/unit/services/test_project_directory.py \
  tests/unit/services/test_unified_workspace_files.py \
  tests/unit/app/routers/test_workspace_files_router.py \
  tests/unit/routers/test_console_project_directory.py \
  tests/unit/app/chats/test_manager.py \
  tests/unit/runtime/test_coding_project_override.py \
  tests/integration/test_coding_project.py
```

### 12.3 Manual acceptance environment

The latest real-browser acceptance used:

```text
Environment: Codex-QwenPaw
Console: http://127.0.0.1:8088
```

Manually verified at the implementation head:

- gray aligned empty placeholder;
- sender control spacing and compact narrow layout;
- Arrow Up/Down history;
- full-line Monaco copy to `filename · line`;
- partial-line copy to line chip plus code chip;
- expandable code preview;
- send-to-clear behavior;
- Preview/Edit and shared Workspace operation.

### 12.4 Agent and Session Files scope separation

The Files workbench now has two explicit ownership scopes:

| Surface | Scope | Project Directory |
| --- | --- | --- |
| Sidebar Workspace → Files | Agent | Agent default |
| Chat Preview → expanded Workspace | Agent + Session | Session effective directory |

The two surfaces reuse the navigator, preview, editor, and Git components, but
no longer share their route, controller, or document state:

- Agent Files is the independent `/files` page and owns the `core.files`
  sidebar selection.
- Chat uses the Preview/Workspace-only `FilesDrawer`.
- Agent and Session tab snapshots persist in separate localStorage
  containers; the retired shared container is not restored;
- tabs, active tabs, diffs, and Monaco model paths use a stable ownership key;
- Session drawer state is kept independently per Session;
- temporary frontend Session state migrates when the backend UUID resolves;
- deleting a Session removes its Files workbench state;
- changing a Project Directory removes only project-root tabs after protecting
  unsaved edits and pending diffs;
- a pending new-Session directory is validated by the backend and applied to
  Files reads, writes, uploads, downloads, and filesystem watches.

The navigator directory identity was also consolidated into one compact
context card. The card combines directory type, basename, full path, source
switching, refresh, and upload actions without presenting the configuration
directory and path as unrelated controls.

Implementation checklist:

- [x] Register `core.files` as the independent `/files` route.
- [x] Remove the Agent Files event bridge and surface from Chat.
- [x] Keep Chat Preview/Workspace state per Session.
- [x] Split Agent and Session tab persistence.
- [x] Stop restoring the retired shared tab container.
- [x] Add a regression test proving a Session tab does not open an Agent tab.
- [x] Rebuild the Session navigator and file watcher after its project
  directory changes.
- [x] Broadcast Runtime project-directory changes to the open Session
  workspace.
- [x] Keep the standalone Files tree inside a bounded, scrollable flex area.
- [x] Add a Chat-header toggle for the current Session workspace.
- [x] Share the Files shell color tokens and header styles across Agent and
  Session surfaces.
- [x] Consolidate directory identity and actions into one context card.
- [x] Add the missing `common.apply` translations.
- [x] Complete manual light/dark and responsive visual QA.

## 13. Recommended next work order

Use this order to avoid reopening already-fixed interaction bugs:

1. Rebase/merge readiness
   - Re-run focused frontend/backend tests.
   - Resolve conflicts without restoring `/coding` or Chat Artifacts.
   - Recheck the AgentScope package patch after dependency updates.
2. Performance completion
   - First-chunk rendering and cancellation.
   - Large-file UX.
   - Directory virtualization and search.
3. Concurrency correctness
   - Propagate ETags into editor tabs.
   - Add a 409 resolution flow and tests.
4. Git decision after #6269
   - Keep the current conditional panel, or remove it through a separately
     approved design.
   - If removed, also remove the redundant activity rail.
5. Naming cleanup
   - Only after behavior is stable, consider moving shared editor/preview code
     out of `pages/Coding`.

## 14. Commit map

The implementation was delivered in these main commits:

```text
7176e166 feat: unify project directories and file workspace
ccc030ce fix: persist session project directory
a7545c88 fix: restore interactive file references
0df0d372 fix: render compact file references
c4733f41 fix: hide raw file reference text
a0500883 fix: preserve compact file references on focus
721060f5 fix: replace file reference overlay with rich composer
7f105b15 fix: restore rich composer interactions
```

When debugging a regression, use this sequence to identify whether it came
from the shared Files architecture, session directory persistence, or the
composer rewrite.

## 15. Handoff definition of done

A follow-up change is ready only when:

- it preserves the directory responsibility boundary;
- it does not re-couple Project Directory with enhanced code capability;
- it keeps Agent Files and Chat Session Files as distinct UI surfaces while
  reusing their file-workbench components;
- it preserves exact raw composer submission;
- it uses the shared Preview/editor path;
- it handles Windows, Linux, and macOS paths;
- it adds focused tests for changed behavior;
- it passes the relevant frontend build/tests and `Codex-QwenPaw` backend
  tests;
- it is manually checked in both light and dark mode at narrow and wide
  widths.
