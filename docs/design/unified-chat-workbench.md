# Unified Chat Workbench

## Status

Approved for incremental implementation. The work starts from `main` and is
split into independently reviewable pull requests.

## Product boundary

The Workbench is a session-scoped surface attached to Chat. It is not owned by
Coding Mode. Coding Mode may change which capabilities are enabled or promoted,
but opening the Workbench must not mutate a project, initialise Git, or grant a
model terminal access.

The first-level navigation contains four stable capabilities:

1. Files
2. Changes
3. Terminal
4. Tools

Subagent and background-tool runs are two views of Tools rather than duplicate
top-level destinations.

## Interaction model

- Chat remains the primary surface.
- A lightweight file preview can be opened from a message.
- Expanding the preview opens the right Workbench directly on Files.
- The Workbench is a resizable right drawer and does not scale chat content.
- Its width, active capability, and open resources are isolated by session.
- Closing the Workbench preserves recoverable session state but releases view
  subscriptions and heavy client modules.
- On small screens it overlays Chat instead of forcing Chat below its minimum
  readable width.

## Architecture

```text
ChatPage
  WorkbenchSurfaceState (session scoped)
    PreviewSurface
    WorkbenchShell
      capability registry
        Files
        Changes
        Terminal
        Tools
```

`WorkbenchShell` owns navigation, resizing, focus, lifecycle, and lazy module
boundaries. Capability modules own their data and commands. The shell must not
contain Git, filesystem, terminal, or task business logic.

### Workspace context

All capabilities will consume one server-authoritative context:

```text
WorkspaceContext
  agent_id
  chat_id
  session_id
  primary_root
  roots
  repository
  permissions
  revision
```

Responses that can race across a session or directory change must carry the
context identity and revision. Clients discard stale responses.

### Resource identity

Resources are not assumed to belong to an agent workspace. Workspace files,
attachments, host files, and memory files share a resource reference carrying
origin, URI, display name, mutability, and an optional workspace context. An
external resource may be previewed without being inserted into the project
tree.

### Changes

Changes has three scopes: current turn, current chat, and repository. Repository
discovery reuses the nearest ancestor repository. Read-only status calls never
run `git init`. Non-Git directories use a turn journal to provide review and
safe undo without pretending to be a repository.

### Terminal

The user terminal and model-facing terminal tools have separate capability
gates. PTY sessions have an exact owner and workspace context. Cleanup signals
and waits for the child process before closing the PTY master, keeps the reader
alive while the process drains, and moves blocking system calls off the event
loop.

## Performance budgets

- Closed Workbench loads no editor, diff, terminal, or task-history bundle.
- Opening or resizing the drawer never applies `scale` to Chat.
- Persisted geometry is available before the first painted open frame.
- Directory pages are bounded to 200 entries and loaded on demand.
- Text and diff payloads are chunked; large lists and logs are virtualised.
- Terminal replay and task history have explicit server and client bounds.
- Switching context aborts obsolete requests and rejects stale responses.
- Multi-megabyte parsing and formatting do not run synchronously in render.

## Delivery plan

1. Workbench shell, stable right split, four capability slots, lazy boundaries.
2. Resource model, preview classification, bounded file loading.
3. Turn/chat/repository Changes and removal of implicit Git initialisation.
4. Terminal lifecycle, permissions, bounded replay, and reconnect state.
5. Tool and subagent history, results, logs, and cancellation.

Each phase receives targeted component or API tests and its own commit and pull
request. Full builds and full test suites are intentionally outside the default
verification path.
