# XiaoYi channel plugin

Private Huawei XiaoYi A2A transport for the standard QwenPaw shared runner.
The entry point is `qwenpaw_channel_xiaoyi.driver.XiaoYiDriver`; runtime
dependencies are declared only in `requirements.txt` (`aiohttp>=3.9.0`).

Configure `enabled`, `ak`, `sk`, and `agent_id`. An empty `ws_url` connects
concurrently to the official domain and IP backup. A custom URL uses a single
connection. The IP backup uses `ssl=False`. Each connection reconnects
independently, and either healthy connection keeps the channel available.
Disconnect logs include the connection name, close code, and reason when
available. `task_timeout_ms` is retained for configuration compatibility only.

Agent execution, authorization, queue admission, display settings and durable
response lifecycle remain in the host. The plugin owns authentication,
heartbeats, reconnection, bounded native session routing and media transport.
Every response retains its original task, request/message and source server.
Stable native message/request IDs deduplicate dual-WS pushes, while shared IPC
admission retries retain the same event ID. Messages without a native ID do not
claim cross-push deduplication. Session maps remain in memory and do not promise
proactive routing after a restart.

Enable **Streaming Output** under **Channels → XiaoYi → Message presentation**
in the console, or set `channels.xiaoyi.streaming_enabled` to `true` in the
agent configuration. Streaming is off by default. When enabled, visible tool
calls, tool results, and answer previews replace the reply body as they arrive.
The final answer replaces the last update. If thinking display is enabled,
each completed thinking segment replaces the previous one. With streaming
off, completed segments append in their respective display areas.

The plugin attempts to show `Working...` before the agent runs. It sends the
task outcome (`Done` on success) before the empty final artifact. Each finish
frame has a durable receipt. An unavailable source can fall back to the other
connection before a write. Writes with unknown outcomes are kept in the
delivery records to prevent automatic replay.

`clearContext` acknowledges `cleared` before removing the task mapping.
`tasks/cancel` only acknowledges `canceled`, preserving the old mapping and
running host Agent behavior. Neither control message claims host cancellation.
Stop closes this instance's entry points, awaits reconnect/receive/heartbeat and
in-flight HTTP/send tasks, and closes both WS sessions and the media session.
Failed cleanup retains the remaining resource references and fails stop.

Media storage uses the supplied execution `media_dir`, then
`workspace_dir/media`, then `DEFAULT_MEDIA_DIR/xiaoyi`. Downloads run in the
background and preserve message order within each session. Attachments are
saved directly in the media directory, replacing files with the same sanitized
name. The plugin infers missing extensions from the MIME type and reports
failed downloads. Local outbound media must belong to the configured media or
workspace roots.

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
