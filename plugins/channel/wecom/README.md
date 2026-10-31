# WeCom AI Bot

This private official plugin runs `qwenpaw_channel_wecom.driver.WeComDriver` with the shared schema-v2 channel runner and shared dependency environment. Install `requirements.txt` through the normal plugin dependency repair flow, then configure `bot_id` and `secret`. The native SDK is pinned to `wecom-aibot-python-sdk==1.0.2`.

All 25 `WecomConfig` fields and their defaults are described in `channel.json`. Existing `wecom:<userid>` and `wecom:group:<chatid>` sessions remain valid; group sessions share `user_id=group` by default while host authorization receives the actual sender. `streaming_enabled` defaults to false and `max_reconnect_attempts` defaults to -1. `ws_url` retains the native gateway override. The common host owns configuration, ACL, Agent execution and environment-variable compatibility.

Text, image, voice ASR text, file, video, mixed messages, quoted/decrypted media, welcome messages, markdown tables, image compression and proactive sends are supported. Uploads use native init/chunk/finish acknowledgements and 512 KiB chunks. Local uploads are restricted to the configured media/workspace directories; data URLs use temporary files that remain alive until their file workers have completed.

The SDK, WebSocket loop/thread, native callback frames, upload waiters and bounded card bindings belong to the worker instance. IPC carries opaque response references and JSON content only. Processing streams refresh every 20 seconds and finalize after 180 seconds; the first answer reuses a live processing stream. Connection changes expire native reply frames. Uncertain and partial deliveries remain unknown in the shared journal and are never replayed automatically. Stop waits for actual tasks, file work and thread exit, retaining references on failure.

Approval buttons carry an opaque worker-local binding. The actual clicker is authorized by the host; a card is shown as approved/denied only after a matching typed host outcome. The static G3 `manage` hook preserves WeCom's HTML `window.settings`, state/timestamp, scode polling and botid/secret algorithms.

Host QR API/CLI, the static catalog, environment reader and official ownership now use this plugin. The old Core runtime has been retired. Independent C1–C7 simulated checks exercised the installed official ZIP through the real Loader, shared worker, local native gateway, queue/ACL and Agent. The legacy map covers 220 responsibilities: 190 preserved checks and 30 explicit contract changes; these are mapped duties, not 220 new test runs.

The [official channel pluginization plan](../../../docs/superpowers/plans/2026-10-14-official-channel-pluginization.md) contains the acceptance index. Actual WeCom service-account acceptance, desktop/Docker distribution and the unified C8 release gate remain pending; no real-robot acceptance is claimed here.
