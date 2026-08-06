# QwenPaw Unified Files Workspace

> Status: Final product and interaction proposal
>
> Selected mock:
> [`options/option-d-progressive-workspace.html`](options/option-d-progressive-workspace.html)
>
> Production implementation is intentionally not included in this branch.

## Final decision

QwenPaw will have one Chat page and one shared Files capability. The separate
Coding page will be removed. Coding becomes a session capability switch that
adds code-oriented tools to the shared workspace without changing routes or
mounting a second frontend.

Files has two entry paths:

1. A file link inside Chat opens a left-side Preview drawer.
2. The global Files navigation opens the same left-side drawer directly as a
   full workspace.

The Preview drawer progressively expands toward the right into a
Coding-style workspace. Chat stays mounted on the right and narrows smoothly.
The selected file, drawer header, Chat scroll position, draft input, and
conversation state are preserved through the transition.

The global left navigation keeps Files under the **Workspace** group and
removes the standalone Memory entry. Memory remains available as a source
inside Files.

## Interaction model

### Chat file link

```text
Chat
  -> Preview drawer
     -> Workspace drawer
```

- Clicking an internal file link opens Preview first.
- Preview slides in from the left.
- Chat remains visible on the right.
- `Expand workspace` widens the same drawer toward the right.
- `@ Mention in Chat` closes the drawer and inserts an inline file reference
  into the Chat composer.
- Explorer appears at the far left of the drawer.
- The existing Preview becomes the active document surface.
- No route transition or Chat remount occurs.

### Workspace drawer actions

Workspace has two separate exit actions:

| Action          | Result                                                 |
| --------------- | ------------------------------------------------------ |
| Back to Preview | Collapse Workspace to the previous Preview state       |
| Close (`X`)     | Close the drawer immediately and return to normal Chat |

Closing Workspace must never require two clicks.

### Direct Files entry

```text
Global Files
  -> Full Files workspace drawer
```

- The drawer enters from the left and expands to near full width.
- Chat is not displayed in the remaining space.
- The implementation is the same workspace component used by the Chat flow.
- Direct Files does not create a second route-specific component tree.
- Closing returns to the current Chat session.

### Drawer sizing

- Preview default width: 30% of the Chat content surface.
- Expanded Workspace default width: 75%.
- Direct Files default width: content width minus the outer drawer margins.
- The right drawer edge is draggable.
- Width changes use an eased 300-350 ms transition.
- The selected width may be stored as a device-local preference.
- Small screens use a full-surface drawer rather than preserving a narrow Chat
  column.

## Product structure

The workspace navigator combines these sources:

1. **Workspace**
   - Current effective project directory.
   - Lazy tree browsing, search, Preview, text editing, Diff, and download.
2. **Profile**
   - Existing `AGENTS.md`, `SOUL.md`, `PROFILE.md`, `HEARTBEAT.md`, and
     `BOOTSTRAP.md` management.
3. **Memory**
   - `MEMORY.md`, daily memory, and digest memory.

Profile and Memory keep their domain-specific controls, but file browsing and
editing reuse the shared Preview, Editor, Diff, and download surfaces.
Memory does not keep a separate global navigation item.

Files attached to a Chat message open directly from that message. They are not
collected into a separate navigator source.

## Inline file references

`@ Mention in Chat` is the file-level form of the existing Coding editor copy
reference behavior. It inserts a styled inline entity at the current composer
caret rather than plain text or a separate attachment row.

Example presentation:

```text
@ design-spec.md
@ FilePreview.tsx:120-138
```

The composer stores a structured reference:

```ts
type ComposerFileReference = {
  kind: "file";
  target: FileTarget;
  range?: { startLine: number; endLine: number };
};
```

Required behavior:

- render the reference as an inline Chip within the composer;
- place the caret after the inserted Chip;
- allow Backspace/Delete to remove the Chip as one entity;
- preserve references in drafts;
- serialize a stable text fallback for message history and clipboard use;
- use the same renderer for file-level mentions and editor copied line ranges;
- announce the filename and optional line range to screen readers.

## Coding tools

The ReAct Agent setting **Enhanced code capability** changes available
capabilities, not the project directory or page route. It is not a standalone
configuration tab.

| Always available                                  | Added by Coding tools                |
| ------------------------------------------------- | ------------------------------------ |
| Chat file links and Preview drawer                | Coding prompt                        |
| Workspace, Profile, and Memory browsing           | AST and LSP                          |
| Text Preview, editing, Diff, upload, and download | Git context and source-control panel |
| Guarded image, PDF, CSV, and large-file Preview   | Advanced Monaco code features        |
| Workspace drawer and resizable panels             | Code-oriented agent tool bundle      |

The default project directory is a separate ReAct Agent setting. Its data and
runtime resolution remain independent from Enhanced code capability.

File cards and tree rows never expose a download action on hover. Clicking a
file opens Preview first; download is available only in the Preview or
Workspace toolbar.

Diff is a general Files capability and remains available when Coding tools are
off.

## Navigation and file targets

The frontend uses one normalized internal target:

```ts
type FileTarget = {
  source: "workspace" | "attachment" | "profile" | "memory";
  path: string;
  line?: number;
  column?: number;
};
```

API paths always use workspace-relative POSIX separators:

```text
src/qwenpaw/app/routers/workspace.py
```

Chat supports:

```markdown
[app.py](src/qwenpaw/app.py)
[app.py:120](src/qwenpaw/app.py#L120)
```

Internal link resolution must:

- leave `http`, `https`, and `mailto` external;
- resolve relative targets against an allowed source root;
- reject traversal, absolute paths, and symlink escape;
- fetch metadata before content;
- reveal the requested line after Workspace expansion;
- preserve dirty tabs and reuse an already-open document;
- show metadata and download actions when Preview is unsupported.

## Frontend state model

The drawer has four explicit states:

```ts
type FilesDrawerState =
  | { kind: "closed" }
  | { kind: "preview"; target: FileTarget }
  | { kind: "workspace"; target: FileTarget; origin: "chat" }
  | { kind: "workspace"; target?: FileTarget; origin: "files" };
```

Required transitions:

| Current state     | Event           | Next state        |
| ----------------- | --------------- | ----------------- |
| Closed            | Chat file click | Preview           |
| Closed            | Files click     | Workspace / Files |
| Preview           | Expand          | Workspace / Chat  |
| Preview           | Close           | Closed            |
| Workspace / Chat  | Back to Preview | Preview           |
| Workspace / Chat  | Close           | Closed            |
| Workspace / Files | Close           | Closed            |

The implementation must not derive these states from unrelated route checks or
multiple booleans.

## Performance contract

### Directories

- Fetch immediate children only.
- Expand directories on demand.
- Use opaque cursor pagination.
- Default page size is 200 entries; server maximum is 500.
- Virtualize visible rows.
- Never materialize the complete project tree in the DOM.
- Coalesce watch events and update only loaded directory pages.
- Cancel stale listing and search requests.

### Files

Initial recommended limits:

| Capability             | Limit / behavior                         |
| ---------------------- | ---------------------------------------- |
| Inline text Preview    | Up to 512 KiB                            |
| Editable text          | Up to 2 MiB                              |
| Large-text chunk       | 256 KiB, cancellable                     |
| Files above 20 MiB     | Metadata and chunked read-only Preview   |
| Frontend content cache | 32 MiB byte-bounded LRU per active agent |
| Images                 | Thumbnail first, original on demand      |
| PDF                    | Range-capable viewer                     |
| CSV                    | Bounded rows/columns; worker parsing     |
| Unknown binary         | Metadata and download only               |

Monaco must load only when Edit or code Diff requires it. Preview should not
pay the Monaco bundle or model-construction cost.

### Upload and download

- The primary action is `Upload file`, not `Upload ZIP`.
- Ordinary single- or multi-file uploads target the selected directory.
- Uploads are streamed, cancellable, concurrency-limited, and show per-file
  progress.
- Conflicts require an explicit overwrite, skip, or rename decision.
- Downloads stream from disk and support cancellation.
- Workspace ZIP import is not part of the Files primary flow.

### Async filesystem I/O

No blocking filesystem operation may run on the Python event-loop thread.
Directory walking, stat calls, reads, writes, copies, hashing, compression, and
archive validation must run through `asyncio.to_thread` or a bounded dedicated
executor.

The service layer must also provide:

- request cancellation;
- per-agent and global concurrency limits;
- byte and entry limits;
- timeouts for expensive operations;
- bounded queues rather than unbounded default-executor submission.

## Cross-platform path contract

- API paths use relative POSIX separators on every platform.
- Server filesystem boundaries use `pathlib`.
- Absolute project roots remain server-side.
- Paths are joined through one safe resolver and checked against allowed roots.
- Windows drive letters and UNC roots are never accepted as client-relative
  paths.
- Case-insensitive collisions are handled explicitly on Windows and default
  macOS filesystems.
- Tests cover `\` normalization, drive letters, UNC paths, reserved names,
  trailing spaces/dots, Unicode, long paths, symlinks, and traversal.

## Responsive behavior

- Desktop: left drawer plus a visible Chat column on the right.
- Tablet: drawer uses nearly the full content surface.
- Mobile: drawer becomes full-screen; Back and Close remain separate actions.
- Touch targets are at least 40 px.
- Resizing is disabled when a reliable minimum Chat width cannot be preserved.
- Reduced-motion preferences remove sliding while retaining the same states.

## Accessibility

- Drawer uses dialog/region semantics appropriate to its modality.
- Focus enters the drawer on open and returns to the invoking link/button on
  close.
- `Escape` closes Preview; in Workspace it closes the drawer directly.
- Back to Preview has a separate accessible label.
- Resize uses keyboard alternatives and exposes the current width.
- File tree, tabs, loading, errors, and progress are screen-reader announced.

## Implementation checklist

- [x] Select progressive left-drawer interaction
- [x] Define Preview-first Chat file links
- [x] Define Workspace collapse and direct Close actions
- [x] Define direct Files behavior
- [x] Merge Workspace, Profile, and Memory
- [x] Replace Coding page with a Coding tools capability switch
- [x] Define directory pagination and virtualization
- [x] Define large-file, upload, and download protection
- [x] Define async filesystem boundaries
- [x] Define Windows, Linux, and macOS path behavior
- [x] Produce the final standalone interactive mock
- [x] Write the production handoff
- [x] Review API contracts against existing endpoints
- [ ] Split implementation into reviewable pull requests
- [x] Implement backend APIs and tests
- [x] Implement frontend workspace and tests
- [x] Remove the old Coding route after all callers migrate

## Final review artifact

Open this file directly:

[`options/option-d-progressive-workspace.html`](options/option-d-progressive-workspace.html)

This is the only retained Mock and the sole interaction reference.
