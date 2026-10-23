# Yuanbao (元宝)

This official channel plugin connects to Tencent Yuanbao with sign-token authentication and its binary protobuf WebSocket gateway. Install through QwenPaw's channel plugin installer, then configure `app_id`, `app_secret` and enable the channel in the intended workspace. `api_domain` and `ws_url` support existing custom gateways. Dependencies are declared only in `requirements.txt`.

The descriptor retains all 23 configuration fields, including display, mention and access policy settings. Access control and Agent execution run in the shared host. Group sessions keep the original group code; direct sessions keep the last eight account characters. Reply routes retain complete native account IDs. Existing `workspace/yuanbao_sessions.json` is read and merged atomically; without a workspace the legacy location is `media_dir.parent/yuanbao_sessions.json`. Invalid existing files are preserved. Authentication, sessions and downloaded media remain after disabling the plugin.

Text, images, files, audio and video sent through content parts retain the original COS upload and preparation-failure link fallback. Local uploads must belong to the workspace or configured media directory. Plain `send` has no prefix; content-part text uses the configured/metadata prefix. The original standalone `send_media` entrypoint had no effect; this plugin returns `LEGACY_MEDIA_ENTRYPOINT_UNSUPPORTED` with no effect. Use content parts for attachments.

A native `needAck` confirms receipt of a gateway frame. Host acceptance and deduplication are separate. Message delivery is acknowledged only after a matching successful business response; a successful WebSocket write alone does not establish delivery. Timeout, disconnect or partial delivery is uncertain and is never automatically replayed or replaced with a fallback. Typing preparation and completion confirm only a WebSocket write, with that scope recorded in the shared response journal.

The shared runner owns the gateway, token refresh, reconnect, receive, heartbeat, typing and media operations. Stopping cancels and awaits owned work before closing clients. Stop errors propagate so the host can retain ownership evidence.

The plugin is delivered through QwenPaw's official channel catalog. Independent tests exercise the installed ZIP/Loader/worker path, controlled gateway and COS servers, real host Agent/session execution, and isolation/lifecycle behavior. These checks do not establish live Tencent service delivery or final cumulative release/resource measurements.
