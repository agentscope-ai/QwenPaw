# Unified Chat Workbench

## Status

Approved for incremental implementation on `feat/unified-chat-workbench`.
Each independently usable capability is committed and verified separately.

## Product boundary

The Workbench is a session-scoped resource surface attached to Chat. It is not
owned by Coding Mode. Coding Mode may enable Changes, but opening Workbench must
not initialise Git, mutate a project, or grant terminal access to the model.

The Workbench has one top-level tab strip. A file, review, terminal, tool run,
browser page, or future side chat is a resource tab. Files is not a permanent
content tab: the file tree is an on-demand navigation drawer that opens files
into the shared resource strip.

Chat Workbench exposes only the current workspace and directories bound to the
session. Agent profile, daily memory, digest, and knowledge graph remain in the
global Files product and are neither displayed nor fetched by Chat Workbench.

## Interaction model

- Chat remains the primary surface.
- Message attachments may first open in a lightweight preview.
- Expanding a preview opens that resource as a Workbench file tab.
- The Workbench starts lightweight and adds resources on demand.
- The top strip contains both file tabs and non-file capability tabs; nested
  file tab strips are forbidden.
- The file-tree button opens a right-side drawer. The drawer is closed by
  default and does not occupy preview width while closed.
- Selecting a file opens or activates its resource tab and keeps the drawer
  available for subsequent navigation.
- File breadcrumbs provide local navigation; the tree provides global project
  navigation. Both use the same bounded directory API and resource opener.
- Closing the Workbench preserves session tabs and geometry while releasing
  view subscriptions and heavy client modules.
- On small screens the Workbench and its file tree overlay instead of reducing
  Chat below its readable width.

## Resource model

```text
WorkbenchResource
  id                 stable, typed identity
  kind               file | changes | terminal | tools | browser | side-chat
  label
  icon
  closeable
  placement          right | bottom
  lifecycle          lazy module + owner
```

File resources retain the existing `EditorTab` state as their source of truth:

```text
FileResource
  path               internal identity, includes source/root when required
  displayPath         user-facing path
  source              workspace | attachment | profile | memory
  workspaceRoot
  artifactUrl
  previewKind
  readOnly
  dirty
  etag
```

Workbench does not duplicate file buffers. It adapts `codingTabsStore` into the
top-level resource strip, while `TabbedEditor` supplies a single-document mode.
This preserves undo models, pending diffs, dirty state, ETag conflict handling,
preview mode, copy, download, and save behavior.

An external or public file may be opened read-only without mounting its parent
directory or inserting it into the project tree.

## Component architecture

```text
ChatPage
  FilesDrawer                      resizable outer right drawer
    WorkbenchShell
      UnifiedResourceTabs
        FileResourceTab[]          adapter over codingTabsStore
        CapabilityTab[]            Changes / Terminal / Tools / ...
      ActiveResourcePane
        FilesWorkspace
          TabbedEditor             single-document mode in Chat
          FilesNavigator           right drawer, created only while open
        GitReviewPane
        TerminalPane
        ToolRunsPane
      ResourceLauncher
      FileTreeToggle
```

The global Files route continues to compose `FilesNavigator` on the left and
`TabbedEditor` with its own local tab strip. Chat-specific layout is selected by
explicit props; `embedded` alone does not change data scope.

## State and persistence

- `codingTabsStore` remains authoritative for file order, active file, buffers,
  dirty state, and pending diffs.
- Workbench layout persists opened capability tabs, the active typed resource,
  file-tree visibility, and drawer width per session.
- Existing capability-only preferences are read as version-zero data. Invalid
  or unavailable capabilities are discarded without affecting file tabs.
- Temporary-session preferences migrate once to the resolved chat id.
- A project-directory revision clears only project-backed file tabs; external
  read-only resources survive.

## Files navigation

- The tree is lazy and paginated at 200 entries per request.
- The tree is not mounted while closed, preventing directory request waterfalls.
- Breadcrumb menus load only the selected directory level and reuse cached
  pages where available.
- No operation infers ownership from a host path. Workspace membership is
  established through the server APIs and bound-directory roots.
- Binary files render an explicit unsupported-preview state with download/open
  actions rather than a blank surface.

## Capability rules

### Changes

Changes is available only when Coding Mode and a valid session context allow
it. Repository discovery reuses the nearest ancestor repository. Read-only
status calls never run `git init`; non-Git directories use recorded file
changes rather than pretending to be repositories.

### Terminal

Terminal prefers a bottom placement but may be opened as a right resource tab.
User terminal and model terminal access have separate gates. PTY shutdown must
terminate and wait for the child process before closing the master descriptor,
and blocking system calls must not run on the event-loop thread.

### Tools

Background tool and subagent runs share one capability with filtered views.
Opening a run shows its execution history and result without duplicating input
queue state.

## Performance budgets

- Closed Workbench loads no editor, diff, terminal, or task-history bundle.
- Closed file tree mounts no navigator and sends no directory requests.
- Resource modules load only when activated.
- Opening or resizing never applies transforms to Chat content.
- Persisted geometry is available before the first painted open frame.
- Directory pages and terminal replay are bounded.
- Multi-megabyte parsing or formatting does not run synchronously in render.
- Context changes abort obsolete requests and reject stale responses.

## Delivery checklist

1. [x] Resizable Workbench shell and lazy capability boundaries.
2. [x] User-configurable capability tabs and per-session restoration.
3. [x] Chat Files restricted to project and bound directories.
4. [x] Unified file and capability resource tabs.
5. [x] Right-side on-demand file-tree drawer.
6. [ ] Lazy breadcrumb directory navigation.
7. [ ] Changes resource and non-Git turn review.
8. [ ] Bottom-capable terminal resource with explicit permissions.
9. [ ] Tool and subagent history, results, logs, and cancellation.

Each completed item receives targeted component and state tests. Full builds and
full test suites remain outside the default verification path.
