# iMessage channel

This official channel plugin uses the shared QwenPaw runner and interpreter.
Its descriptor is passive metadata; browsing configuration does not open
Messages or execute `imsg`.

The worker requires macOS, an already available `imsg` executable on PATH, and
read access to the configured Messages SQLite database. It reports explicit
platform, executable and database errors. It never installs Homebrew packages
or changes macOS permissions. `imsg` is an operating-system resource rather
than a Python package. HTTP downloads use the declared shared `httpx` library;
SQLite and subprocess handling use Python's standard library.

The retained configuration fields/defaults are in `channel.json`, including
`db_path`, `poll_sec`, `media_dir` and `max_decoded_size`. Host configuration,
environment compatibility, ACL and Agent execution remain host responsibilities.
An explicit media directory is an allowed media root; the physical workspace
is another allowed root. Local files outside these roots and escaping symlinks
are rejected. Local attachments are copied from checked file descriptors before
`imsg` opens them. Remote and strictly validated Base64 data attachments retain
legacy sanitized filenames and extensions in the configured media directory.
Uninstall must preserve this directory and user channel/session configuration.

On startup, a read-only SQLite connection captures MAX(ROWID), so old messages
are not replayed. The watcher admits new text messages only; it does not claim
inbound attachment or group-session support. Sessions remain
`imessage:<sender>`, and incoming metadata retains integer `rowid` and string
`chat_rowid`. Self messages, empty text, missing senders and messages beginning
with a nonempty bot prefix are filtered. Unlike the old empty-prefix bug,
an empty prefix admits ordinary text. The cursor advances after host admission
or explicit permanent rejection; unresolved admission retains the row/event.

Direct text preserves its bytes. Content-part text is joined with newlines,
prefixed by the caller's response metadata prefix without an extra separator,
and stripped after combination. Media is sent separately after text. Missing
or invalid media keeps the legacy no-effect behavior. A determinate media
preparation failure may produce the legacy `[File: ...]` placeholder in a parts
send; direct media does not add a placeholder. A command error after execution
may have sent the message and therefore returns unknown, without fallback or
replay. Responses use the existing shared durable journal.

Each command uses an argument list, captures bounded output, and has a trusted
30 second deadline. Cancellation/timeout attempts bounded termination and waits for the command
and pipe readers; an unconfirmed exit retains their references. Commands inherit the worker's session/process group. Stop
closes admission, settles active operations, closes the watcher/SQLite/client,
and retains unresolved resources on failure. The existing host supervisor
independently proves the whole worker group exited and reaps descendants even
when the platform's own resources closed successfully. No private process
manager or detached command session is introduced.

Independent tests cover native SQLite, a controlled `imsg` executable, the
official ZIP/Loader/worker path, real host Agent/session execution, isolation
and lifecycle behavior. They use temporary databases and a controlled
executable, never the user's Messages database or contacts. Live Messages
delivery and final cumulative release/resource measurements remain separate
acceptance boundaries.
