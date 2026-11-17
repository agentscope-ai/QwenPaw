# MQTT official channel

This schema v2 plugin uses the selected shared interpreter. Only its worker imports platform SDKs; the host owns Agent execution, ACL and queue admission. Install or repair dependencies explicitly through the plugin manager. Configuration remains under `channels.mqtt`; installing and disabling the plugin never removes user configuration or business files.

MQTT supports TCP/WebSocket, TLS CA/client certificates, username/password, clean sessions, reconnect subscription, JSON `text`/`redirect_client_id` and plain text. Sessions remain `mqtt:{sender}` and publication expands `{client_id}`. QoS0 waits for client send completion; QoS1/2 wait for broker confirmation. A lost confirmation is unknown and is never automatically replayed. MQTT MID is not a stable business ID; identical messages are independent events. Image/video/file replies retain URL placeholders; audio retains `[Audio]`. Historical environment variables, including transport default `mqtt` normalized to paho TCP, remain supported.

Stop fences callbacks, awaits owned work and closes platform resources. A graceful close failure is reported with its resource evidence. The shared supervisor may reclaim the worker by confirmed process-tree termination and records `forced/exited`; an unconfirmed residual retains ownership and fences replacement startup until a successful retry. Private bundled source ZIPs still occupy the host package; dependency removal does not imply source downloads disappear.

Reconnect retains the worker-owned random client ID, `clean_session`, TLS/auth and subscriptions. It replaces the paho object and carries its packet-ID cursor so paho cannot silently replay an unconfirmed outgoing publish or immediately alias its MID. Broker-side durable sessions may redeliver inbound packets; without an application message ID these remain independent events. Packet confirmation waits up to 3 seconds, below the shared outbound RPC deadline; expiration yields unknown.


## Public SDK migration (0.2.0)

The plugin now implements `ChannelDriver` using `ChannelMessage`, `ReplyTarget`,
`ChannelSendResult` and owned callback tasks. The host continues to own queue
admission, response routes and retry decisions. No private channel protocol
imports are needed in the plugin. Existing `channels.mqtt` settings and
`mqtt:{sender}` sessions are preserved.

The host's official MQTT compatibility adapter keeps the
`mqtt.shared.responses` journal and its receipt namespace. It reads old
`client_id` routes and keeps unknown publish receipts as replay fences; it does
not copy or discard them into a new SDK journal. Pending local cleanup is
resumed at startup. MQTT's historical direct/content-part prefix rules stay in
that host adapter, including the explicit metadata-prefix distinction. This is
a host-owned compatibility path for the official MQTT channel, not a new public
formatting API for arbitrary plugins.

The existing MQTT regression suite now exercises the SDK adapter and includes
legacy live/archived receipt upgrades. Run it in CI; static checks alone do not
prove broker reconnection, shutdown or upgrade behavior.
