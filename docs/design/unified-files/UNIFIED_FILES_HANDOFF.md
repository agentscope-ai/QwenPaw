# Unified Files Workspace — Engineering Handoff

> Product source of truth:
> [`UNIFIED_FILES_PROPOSAL.md`](UNIFIED_FILES_PROPOSAL.md)
>
> Interaction reference:
> [`options/option-d-progressive-workspace.html`](options/option-d-progressive-workspace.html)
>
> This document describes the production implementation. The HTML mock is not
> production code and should not be copied into React.

## 1. Outcome

Replace the separate Chat and Coding frontend surfaces with one Chat workspace:

- Chat remains the primary page and is mounted once.
- Chat file links open a left Preview drawer.
- Preview expands in place into a left Files workspace drawer.
- Chat stays on the right during the Chat-origin workspace flow.
- Global Files opens the same drawer near full width without Chat.
- Coding mode becomes a session capability switch.
- Existing Profile and Memory files reuse the shared file surfaces.
- The standalone global Memory navigation item is removed; Memory is a Files
  source.
- The old `/coding` route and route-switching behavior are removed after all
  callers migrate.

## 2. Non-goals

- Do not redesign agent runtime coding behavior in this frontend change.
- Do not build a second Files component for the direct Files entry.
- Do not add a compatibility component for the old `/coding` frontend.
- Do not make ZIP the primary Files upload action.
- Do not recursively load the whole project tree.
- Do not move blocking filesystem work onto the event loop.
- Do not copy the mock's inline CSS or JavaScript into production.

## 3. Current implementation inventory

### Frontend

The current Coding surface is concentrated in:

- `console/src/pages/Coding/index.tsx`
  - Owns the VS Code-like activity bar.
  - Mounts resizable Explorer, Editor, and Chat columns.
- `console/src/pages/Coding/FileTree.tsx`
  - Builds the project file tree.
- `console/src/pages/Coding/TabbedEditor.tsx`
  - Owns Monaco models, tabs, editing, and Diff.
- `console/src/pages/Coding/FilePreview.tsx`
  - Handles non-editor previews.
- `console/src/pages/Coding/GitPanel.tsx`
  - Owns source-control UI.
- `console/src/pages/Chat/index.tsx`
  - Redirects to `/coding` when coding mode is enabled.
  - Already contains special handling for Chat embedded under `/coding`.
- `console/src/components/CodingModeToggle/index.tsx`
  - Changes backend state and navigates between Chat and Coding routes.
- `console/src/stores/codingModeStore.ts`
  - Stores per-agent coding mode and project directory.
- `console/src/stores/codingTabsStore.ts`
  - Stores persisted tabs per agent.
- `console/src/stores/codeFileCacheStore.ts`
  - Stores file content in memory.
- `console/src/layouts/registry/builtinRoutes.tsx`
  - Registers `/coding/*` and redirects `/` according to coding mode.
- `console/src/utils/sessionRoute.ts`
  - Models route mode as `"chat" | "coding"`.

Reuse the proven FileTree, TabbedEditor, FilePreview, GitPanel, tab state, and
copy/paste behavior. Move ownership; do not rewrite these capabilities unless
the new performance contract requires a focused change.

### Backend

Current code-file APIs are in:

- `src/qwenpaw/app/routers/workspace.py`
  - `GET /code-files` recursively enumerates the full project.
  - `GET /code-files/{file_path}` reads text up to 5 MiB.
  - `PUT /code-files/{file_path}` writes text through `asyncio.to_thread`.
  - `GET /binary-files/{file_path}` streams supported binary previews.
  - `GET /watch` emits workspace changes through SSE.
- `src/qwenpaw/app/routers/coding_mode.py`
  - Stores the coding capability state.
- `src/qwenpaw/services/workspace_manager/`
  - Owns workspace roots and isolation.

The current recursive list endpoint uses the default executor and returns every
file. It must not back the new global tree.

## 4. Target frontend architecture

Recommended ownership:

```text
ChatPage
├── ChatConversation
├── ChatComposer
│   └── InlineFileReference
└── FilesDrawerController
    └── FilesDrawer
        ├── FilesDrawerHeader
        ├── FilePreviewSurface
        └── FilesWorkspace
            ├── WorkspaceActivityBar
            ├── FilesNavigator
            ├── DocumentTabs
            ├── DocumentSurface
            └── GitPanel (Coding tools only)
```

Suggested new module:

```text
console/src/features/files-workspace/
├── FilesDrawer.tsx
├── FilesDrawer.module.less
├── FilesDrawerController.ts
├── FilesNavigator.tsx
├── FilesWorkspace.tsx
├── FileTarget.ts
├── internalFileLinks.ts
├── useFilesDrawerState.ts
└── __tests__/
```

Existing Coding components may move into this feature as they are adopted.
Avoid duplicating them under both `pages/Coding` and the new feature.

## 5. Drawer state machine

Use a discriminated union:

```ts
type FileSource = "workspace" | "attachment" | "profile" | "memory";

type FileTarget = {
  source: FileSource;
  path: string;
  line?: number;
  column?: number;
};

type FilesDrawerState =
  | { kind: "closed" }
  | { kind: "preview"; target: FileTarget; trigger: HTMLElement | null }
  | {
      kind: "workspace";
      origin: "chat";
      target: FileTarget;
      trigger: HTMLElement | null;
    }
  | {
      kind: "workspace";
      origin: "files";
      target?: FileTarget;
      trigger: HTMLElement | null;
    };
```

Do not model Preview, Workspace, direct Files, and visibility as unrelated
booleans.

### Required events

```ts
type FilesDrawerEvent =
  | { type: "OPEN_PREVIEW"; target: FileTarget; trigger: HTMLElement }
  | { type: "OPEN_FILES"; target?: FileTarget; trigger: HTMLElement }
  | { type: "EXPAND_WORKSPACE" }
  | { type: "COLLAPSE_TO_PREVIEW" }
  | { type: "CLOSE" };
```

### Exit behavior

This distinction is mandatory:

- `COLLAPSE_TO_PREVIEW`
  - Available only for Chat-origin Workspace.
  - Returns to Preview.
- `CLOSE`
  - Available in Preview and both Workspace origins.
  - Closes the drawer immediately.
  - Never requires a second click.

`Escape` maps to `CLOSE`, including from expanded Workspace.

## 6. Layout and motion

### Desktop

- Drawer is anchored to the left content edge.
- Preview begins near 54% width.
- Chat shifts into a narrower right lane.
- Expand changes drawer width to approximately 78%.
- Explorer appears on the drawer's left.
- The current Preview becomes the document surface to its right.
- The drawer's right edge is resizable.

### Direct Files

- Use the same drawer and workspace subtree.
- Expand to the content width minus outer margins.
- Hide the Chat lane.
- Do not navigate to another component.

### Motion

- Use the frontend's existing motion package.
- Drawer entry: 220-260 ms.
- Preview-to-Workspace width transition: 300-350 ms.
- Explorer reveal begins from the left edge.
- Preserve the drawer header and active document during expansion.
- Respect `prefers-reduced-motion`.
- Animate transform, opacity, and bounded layout properties only.
- Do not animate Monaco content or rebuild Monaco models during drawer sizing.

### Resize behavior

- Minimum Preview width: 420 px on desktop.
- Minimum Chat width: 300 px.
- Minimum Editor width: 360 px.
- Stop expanding when any minimum would be violated.
- Persist width locally per device, not in agent state.
- Throttle resize updates with `requestAnimationFrame`.
- Call Monaco `layout()` after the animation and during throttled dragging.

## 7. Chat integration

### Internal file-link resolver

Intercept only allowed internal relative paths:

```markdown
[app.py](src/qwenpaw/app.py)
[app.py:120](src/qwenpaw/app.py#L120)
```

Leave these external:

- `http:`
- `https:`
- `mailto:`
- unsupported custom schemes

Resolution order:

1. Parse source, relative path, optional line, and optional column.
2. Reject absolute and traversal targets on the client.
3. Open drawer loading state without navigating.
4. Fetch metadata.
5. Fetch only the Preview representation permitted by metadata.
6. On expansion, load or reuse the document tab.
7. Reveal the requested line after the editor is ready.

The server remains authoritative for path security.

### State preservation

Opening and expanding Files must preserve:

- Chat component identity;
- conversation scroll position;
- streaming response state;
- draft composer content;
- attachments;
- selected session;
- dirty tabs and editor undo history.

### Inline `@file` references

The Preview action currently described as Ask about file must insert a
structured file reference at the composer caret.

```ts
type ComposerFileReference = {
  kind: "file";
  target: FileTarget;
  range?: {
    startLine: number;
    endLine: number;
  };
};
```

Render it inline:

```text
@ design-spec.md
@ FilePreview.tsx:120-138
```

Implementation requirements:

- Prefer the Chat input library's inline entity/mention API when available.
- Otherwise use a controlled rich-text input with non-editable inline Chips.
- Do not fake an inline reference by positioning a separate attachment above a
  textarea.
- Insert at the current selection and restore the caret after the Chip.
- Treat Arrow keys, Backspace, Delete, copy, paste, undo, IME, and draft
  restoration explicitly.
- Reuse the entity renderer for the existing editor-copy line reference.
- Keep a plain-text fallback for clipboard and persisted message rendering.
- Send structured references separately from human-authored message text when
  the Chat payload supports it.

## 8. Files source adapters

Expose one frontend interface:

```ts
type FilesSourceAdapter = {
  list(input: ListDirectoryInput): Promise<ListDirectoryResult>;
  metadata(target: FileTarget): Promise<FileMetadata>;
  preview(target: FileTarget, range?: ByteRange): Promise<FilePreview>;
  save?(
    target: FileTarget,
    content: string,
    etag?: string,
  ): Promise<SaveResult>;
  download(target: FileTarget): Promise<void>;
};
```

Implement adapters for:

- Workspace;
- Profile;
- Memory.

Message attachments open directly from their message card and do not appear as
a navigator source.

Profile and Memory adapters may expose extra domain actions, but must reuse
shared loading, error, Preview, Diff, and save components.

## 9. API contract

Review existing endpoints before adding new paths. The required semantics are:

### List one directory

```http
GET /api/workspace/tree?path=src/qwenpaw&cursor=opaque&limit=200
```

```json
{
  "directory": "src/qwenpaw",
  "entries": [
    {
      "name": "app.py",
      "path": "src/qwenpaw/app.py",
      "kind": "file",
      "size": 18241,
      "modified_at": "2026-07-27T10:00:00Z",
      "preview_kind": "text"
    }
  ],
  "next_cursor": "opaque-value",
  "has_more": true
}
```

Requirements:

- Immediate children only.
- Stable deterministic ordering.
- Opaque cursor.
- Default 200; maximum 500.
- Cancellation-safe.
- Skipped-directory policy shared with search and watch.

### Metadata

```http
GET /api/workspace/file-metadata?path=src/qwenpaw/app.py
```

Metadata must be available without reading file content.

### Chunked text

```http
GET /api/workspace/file-content?path=...&offset=0&limit=262144
```

Return:

- byte range;
- decoded content;
- next offset;
- EOF;
- ETag/version;
- truncation and encoding information.

Do not use character offsets for filesystem range reads.

### Save

Use optimistic concurrency:

```http
PUT /api/workspace/file-content?path=...
If-Match: <etag>
```

Return conflict when the file changed on disk.

### Upload

- Accept ordinary files.
- Stream multipart bodies.
- Limit concurrent writes.
- Require an explicit conflict policy.
- Return per-file results.

### Download

- Stream from disk.
- Set safe filename headers.
- Support cancellation and Range where useful.

## 10. Backend performance and event-loop safety

### Replace recursive tree enumeration

Do not call the current `_list_all_files` for the new navigator. Add a
single-directory listing primitive using `os.scandir`, because it exposes entry
metadata efficiently and avoids a separate stat for common cases.

### Dedicated executor

Use a bounded filesystem executor or a service-level semaphore. Do not submit
an unbounded number of operations to the default executor.

Operations requiring offload include:

- `os.scandir`, walking, and stat;
- text and binary reads;
- writes and atomic replacement;
- hashing and ETag work beyond cheap metadata;
- copy, upload merge, and download preparation;
- compression and extraction.

### Cancellation

- Check request disconnection between chunks/pages.
- Close file handles on cancellation.
- Cancel stale frontend requests with `AbortController`.
- Avoid continuing a recursive search after the user changes query.

### Caching

- Key metadata by source, path, and version.
- Bound file cache by total bytes.
- Invalidate loaded entries from coalesced watch events.
- Do not invalidate the entire tree for one file event.

## 11. Path and security requirements

One server helper must:

1. Accept a relative POSIX API path.
2. Reject empty segments where invalid, `..`, absolute forms, drive prefixes,
   and UNC forms.
3. Join through `pathlib`.
4. Resolve or otherwise validate symlinks according to workspace policy.
5. Confirm the target remains under an allowed source root.

Never concatenate browser paths with native separators.

Tests must cover:

- `C:\...` and `C:/...`;
- `\\server\share`;
- mixed separators;
- `..` traversal;
- symlink escape;
- case-only conflicts;
- reserved Windows names;
- trailing dot and space;
- Unicode normalization;
- long paths;
- filenames containing shell metacharacters.

## 12. Coding-mode migration

### Preserve

- Backend coding capability state.
- Project selection.
- Coding prompt and tool bundle.
- Git/AST/LSP behavior.
- Monaco tabs, dirty state, Diff, and editor copy integration.

### Change

- Rename frontend concepts from mode/page to tools/capability where practical.
- `CodingModeToggle` stops navigating.
- Chat stops redirecting to `/coding`.
- Root routing always resolves sessions under `/chat`.
- New sessions no longer choose a route mode.
- Coding components mount inside Files Workspace.

### Remove after migration

- `/coding/*` route registration.
- `CodingPage` layout wrapper.
- `"chat" | "coding"` route mode.
- Chat conditionals that exist only because Chat is embedded under `/coding`.
- Sidebar behavior that changes Chat destination based on coding mode.

Do this atomically within the migration series. Do not add a new frontend
compatibility layer for `/coding`.

## 13. Suggested implementation sequence

### PR 1 — Backend directory and metadata contract

- Add paginated one-directory listing.
- Add metadata-first and chunked content support.
- Add executor/semaphore limits.
- Add Windows and security tests.
- Keep existing endpoints operational until frontend migration completes.

### PR 2 — Shared Files domain

- Add `FileTarget`, source adapters, query keys, and bounded cache.
- Reuse existing Preview and Editor behavior.
- Add unit tests for link parsing and state transitions.

### PR 3 — Left drawer in Chat

- Add drawer state machine.
- Add Preview-first Chat links.
- Add inline `@file` references and migrate editor copied line ranges to the
  shared reference renderer.
- Add Expand, Back to Preview, and direct Close.
- Preserve Chat state and implement responsive behavior.
- Add resize and reduced-motion behavior.

### PR 4 — Workspace integration

- Move/adapt FileTree, TabbedEditor, FilePreview, and GitPanel.
- Add direct Files entry.
- Integrate Profile and Memory.
- Remove the standalone global Memory navigation entry.
- Change Coding toggle to capability-only behavior.

### PR 5 — Remove old Coding frontend

- Remove `/coding` route and redirects.
- Remove route-mode utilities and obsolete layout code.
- Remove files orphaned by the migration.
- Update localization and end-to-end tests.

Keep each PR buildable and testable. Do not leave both old and new UI mounted
in production.

## 14. Test plan

### Frontend unit tests

- Internal versus external link parsing.
- Closed → Preview.
- Preview → Workspace.
- Workspace → Preview.
- Preview → Closed.
- Workspace → Closed in one action.
- Direct Files → Workspace.
- Agent/session switch resets or restores the correct drawer state.
- Dirty tab reuse and line reveal.
- Coding tools do not change routes.

### Frontend integration tests

- Chat does not remount through drawer transitions.
- Draft and scroll position remain unchanged.
- Inline file mentions insert at the caret, survive drafts, and delete as one
  entity.
- Editor copied line ranges use the same inline reference renderer.
- Drawer resize obeys minimum widths.
- Monaco layouts correctly after animation.
- Large files never create a full Monaco model.
- Directory virtualization keeps DOM rows bounded.
- Upload progress, cancellation, and conflict handling.

### Backend tests

- Cursor pagination and deterministic ordering.
- Cancellation and concurrency limits.
- Chunk boundary correctness for UTF-8.
- ETag conflict on save.
- Streamed download and upload.
- Binary Preview allowlist and limits.
- Windows, UNC, traversal, symlink, and Unicode cases.
- Agent root isolation.
- Event loop remains responsive during large directory and file operations.

### Manual acceptance

- Click a Chat file: Preview enters from the left.
- Expand: the same drawer grows right; Chat remains on the right.
- Back to Preview: Workspace collapses one level.
- Expand again, then click `X`: drawer closes immediately.
- Click global Files: near-full left drawer opens without Chat.
- Resize using mouse and keyboard.
- Repeat at desktop, tablet, and mobile widths.
- Repeat with Coding tools on and off.

Product copy must not expose implementation notes such as state preservation,
loading strategy, or design rationale. Those statements belong in this
handoff, not in the rendered footer.

## 15. Definition of done

- One Chat component and one Files Workspace component tree.
- No production `/coding` page or Chat-to-Coding redirect.
- Preview-first Chat file links.
- Left-side progressive drawer with separate Back and Close actions.
- Close works from Workspace in one click.
- Global Files reuses the same workspace without Chat.
- Profile and Memory use shared file surfaces.
- Cursor-paginated and virtualized directories.
- Guarded chunked large-file handling.
- No blocking filesystem I/O on the event loop.
- Windows, Linux, and macOS tests pass.
- Frontend unit, integration, build, and lint checks pass.
- Python unit and integration tests pass at 100% for changed modules.
