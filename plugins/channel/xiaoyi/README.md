# XiaoYi channel plugin

Private Huawei XiaoYi A2A transport for the standard QwenPaw shared runner.
The entry point is `qwenpaw_channel_xiaoyi.driver.XiaoYiDriver`; runtime
dependencies are declared only in `requirements.txt` (`aiohttp>=3.9.0`).

The descriptor retains all 22 `XiaoYiConfig` fields and defaults. Configure
`enabled`, `ak`, `sk`, and `agent_id`. An empty `ws_url` connects concurrently
to the official domain and IP backup; a custom URL uses a single connection.
The legacy IP connection continues to use `ssl=False`. Either connection is
sufficient for a healthy platform state. `task_timeout_ms` is retained as
configuration; the legacy implementation did not enforce a task timer.

Agent execution, authorization, queue admission, display settings and durable
response lifecycle remain in the host. The plugin owns authentication,
heartbeats, reconnection, bounded native session routing and media transport.
Every response retains its original task, request/message and source server.
Stable native message/request IDs deduplicate dual-WS pushes, while shared IPC
admission retries retain the same event ID. Messages without a native ID do not
claim cross-push deduplication. Session maps remain in memory and do not promise
proactive routing after a restart.

Completed messages become text/reasoning artifacts split at 4000 characters,
preferring newlines. Native stream closure writes a completed status first and
an empty final artifact second. Each write has an independent durable receipt;
unknown writes are retained and never automatically replayed. A disconnected
source can fall back to the other connection before a write; an uncertain write
does not trigger another write on the other connection.

`clearContext` acknowledges `cleared` before removing the task mapping.
`tasks/cancel` only acknowledges `canceled`, preserving the old mapping and
running host Agent behavior. Neither control message claims host cancellation.
Stop closes this instance's entry points, awaits reconnect/receive/heartbeat and
in-flight HTTP/send tasks, and closes both WS sessions and the media session.
Failed cleanup retains the remaining resource references and fails stop.

Media storage keeps the legacy precedence: an explicitly supplied execution
`media_dir`, then `workspace_dir/media`, then `DEFAULT_MEDIA_DIR/xiaoyi`.
These execution context values do not add a 23rd configuration schema field.
Local outbound media must belong to the configured media/workspace roots.
Downloads retain safe filenames, MIME-derived extensions and failure text.

The plugin declares `send.semantic_parts.v1`: completed-event text and media
arrive with host-owned presentation roles via `content_source=event`. The
plugin converts these roles into native A2A kinds and separators; it contains
no Agent renderer. Explicit direct/content-parts/media sends retain their own
formatting and attachment behavior. The associated public semantic-parts
support is integrated and covered by independent simulated acceptance cases.

XiaoYi is registered as an official descriptor-based plugin with the public
environment reader, doctor and bundled distribution ZIP. Independent cases
exercised the installed official artifact through the real PluginLoader,
shared worker, host queue and Agent, with local platform endpoints. Legacy
unit/contract entries now target the current owners, and the five old Core
source files have been removed.

The retained oracle map covers all 66 direct and 19 inherited responsibilities.
Three direct cases explicitly tighten lifecycle behavior: disabled text,
disconnected text and disconnected media now fail instead of silently returning,
with no native effects or false success. The other 63 direct cases are mapped
to preserved behavior. The `tasks/cancel` boundary described above is unchanged.

Repository acceptance index: [official channel pluginization plan](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md).
The historical 125.63-second failure-path teardown observation remains
unresolved; these results do not identify its cause or claim it was fixed.
Actual platform-account service acceptance and C8 are not claimed.
