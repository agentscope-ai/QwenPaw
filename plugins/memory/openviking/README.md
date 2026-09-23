# OpenViking Memory Backend

[中文文档](README_ZH.md)

This plugin connects QwenPaw to a separately deployed
[OpenViking](https://github.com/volcengine/OpenViking) server using its REST
API. It stores completed user/assistant turns, recalls relevant history before
model calls, and exposes a governed `memory_search` tool.

## Security and trust boundary

- The Tenant API Key is configured by the deployment owner, is marked as a
  plugin secret, and is never included in client error bodies or plugin logs.
- Redirects are disabled for every OpenViking HTTP request.
- `memory_search` is registered as a network tool, so a strict governance
  policy can require approval before it sends a remote query.
- OpenViking results are historical data, not trusted instructions. Both
  automatic recall and explicit search prepend a fixed warning asking the
  model not to follow instructions embedded in retrieved material.
- QwenPaw hashes the OpenViking identity, this installation's private ID, the
  Agent ID, and the QwenPaw chat ID to form an OpenViking session ID. This
  separates conversations; it is not an authorization boundary.

## Install

Build the Console extension first:

```bash
cd plugins/memory/openviking/frontend
npm install
npm run build
cd ../../../../
```

Then install the local plugin:

```bash
qwenpaw plugin install plugins/memory/openviking
```

Use `--force` when reinstalling a changed copy. QwenPaw must have memory
backend plugin support (the host version declared in `plugin.json`).

## Configure an Agent

In the Console, select **OpenViking** from the long-term-memory backends and
complete its tab:

- **Server Endpoint**: the URL reachable from the QwenPaw process. For a
  local native process this is often `http://127.0.0.1:1933`; in Docker it is
  commonly a Compose service name such as `http://openviking:1933`.
- **Tenant API Key**: create this in OpenViking for the intended account/user.
  It is required and stored as a masked secret field.
- **Request Timeout**: 1–300 seconds.
- **Automatic Recall Token Budget**: 64–32,000 estimated tokens. This bounds
  the complete synthetic recall message, including the safety notice.
- **Commit Policy**: `auto` lets OpenViking apply its server-side policy;
  `every_turn` requests a commit after every successfully appended turn.
- **Auto Memory Search**: enable/disable automatic recall and choose 1–20
  result candidates.

Saving Agent configuration reloads its memory backend instance through
QwenPaw's normal plugin lifecycle. Configuration is stored under
`running.memory_backend_configs.openviking`, for example:

```json
{
  "running": {
    "memory_manager_backend": "openviking",
    "memory_backend_configs": {
      "openviking": {
        "base_url": "http://127.0.0.1:1933",
        "api_key": "deployment-provided-secret",
        "request_timeout": 10,
        "retrieval_token_budget": 2048,
        "commit_policy": "auto",
        "auto_memory_search_config": {
          "enabled": true,
          "max_results": 3
        }
      }
    }
  }
}
```

Do not commit a real API key. The example value is a placeholder only.

## Verify

1. Configure the backend for one Agent and send a distinctive, non-sensitive
   fact in one conversation.
2. In a later conversation for the same Agent, ask about the fact and verify
   that automatic recall adds relevant context.
3. Ask the Agent to use `memory_search`; under a strict governance policy,
   verify that the remote search is treated as a network action.

The plugin's unit tests use `httpx.MockTransport` and `AsyncMock`; no
OpenViking server or credentials are required for those tests.

## Retry behavior

The same background task retains its message batch and makes at most three
attempts for service errors, waiting 1 second and then 2 seconds between
attempts. Configuration errors are not retried. The host task remains `running`
while retrying, becomes `completed` on success, and becomes `failed` if retries
are exhausted. Shutdown cancellation propagates normally. There is no durable
queue or automatic later retry after exhaustion or a process restart.

In `every_turn` mode, a confirmed append followed by a failed commit retains
its pending message IDs in the Manager. A retry commits without appending those
messages again. If an append response is lost after the server accepted the
messages, a retry may still append them twice; this is not an exactly-once
guarantee. A successful commit request also does not prove that background
memory extraction has finished.

## Resource bounds

Explicit search clips each formatted result to 2,048 UTF-8 bytes and the
complete returned text to 8,192 UTF-8 bytes. The total includes the intact
safety notice, separators, and truncation markers. These are text-output
bounds, not HTTP response-size limits or exact token budgets.

The Manager caches at most 256 recently used prepared sessions and 10,000
recently recorded completed message IDs. Evicting a session cache entry only
requires preparing that session again; it does not delete remote data.
Evicting a completed message ID ends its local duplicate suppression, so
replaying that older message may append it again. Pending-commit IDs are not
evicted by these limits and are removed after a successful commit; empty
pending entries are not retained. Pending work itself is not globally bounded
by these cache limits. All these progress records are in memory and reset
when the Manager is recreated.
