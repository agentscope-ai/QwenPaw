# OpenViking Memory Backend

[中文文档](README_ZH.md)

This plugin connects QwenPaw to a separately deployed
[OpenViking](https://github.com/volcengine/OpenViking) server using its REST
API. When automatic recall is enabled, it retrieves relevant long-term memory
before model calls. After each completed user/assistant turn, a background queue
appends messages not already acknowledged by OpenViking to the remote session.
With `every_turn`, the plugin requests a commit after each successfully appended
turn; with `auto`, OpenViking executes the automatic commit policy supplied by
the plugin.
Commits archive messages and trigger background memory extraction, so a
successful append or commit request does not mean extraction has finished.
The plugin also exposes a governed `memory_search` tool.

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

## Prepare an OpenViking server

The plugin requires a separately deployed OpenViking server with working
memory extraction and search. It does not deploy the server or configure its
models.

1. For a self-hosted server, follow the
   [OpenViking configuration guide](https://github.com/volcengine/OpenViking/blob/main/docs/en/guides/01-configuration.md).
   Configure the embedding model and vector dimension, plus the VLM/LLM used
   for memory extraction, on the OpenViking server. Ensure model-provider
   credentials, access permissions, and quota are available.
2. Start the server and obtain its reachable URL and an OpenViking user API
   key for the intended account/user. Enter these in the plugin's **Server
   Endpoint** and **Tenant API Key** fields.
3. Verify actual memory extraction and search. A successful `/health` response
   alone does not prove that the configured model services can be called.

The two kinds of credentials serve different purposes:

- **Model-provider API key**: configured on the OpenViking server to call its
  embedding and extraction models, when required by the provider.
- **OpenViking user API key**: entered in this plugin to authenticate requests
  to OpenViking. Do not put a model-provider key in this field.

If you connect to a server managed by someone else, its administrator handles
the model configuration; you only need the server URL and OpenViking user key.

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
  This is an OpenViking user key, not a model-provider key. It is required and
  stored as a masked secret field.
- **Request Timeout**: 1–300 seconds.
- **Automatic Recall Token Budget**: 64–32,000 estimated tokens. This bounds
  the complete synthetic recall message, including the safety notice.
- **Commit Policy**: `auto` lets OpenViking execute the plugin's preset policy;
  `every_turn` requests a commit after every successfully appended turn.
- **Auto Memory Search**: enable/disable automatic recall and choose 1–20
  result candidates.

The `auto` preset uses a message-count threshold of 20 and retains the four most
recent messages when that threshold triggers a commit. These are message counts,
not conversation turns. The preset also supplies a 300-second idle timeout and a
60-second minimum automatic commit interval; idle scheduling must be enabled on
the server. Idle-timeout commits can use different retention behavior, as noted
below for v0.5.2.1. These policy parameters are not configurable in the Console.

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

### Enable session-based query expansion

Query expansion uses recent conversation history to fill in missing context in
a search query, such as the project referred to by "its device number". The
plugin currently hardcodes `query_expansion="off"` in its requests. The Console's
`auto` commit policy controls when messages are archived; it is not a query
expansion switch. Query expansion cannot be enabled through the Console or Agent
configuration; the instructions below require editing source code. Ordinary
long-term-memory recall works with expansion disabled.

To enable query expansion, edit the request JSON in
`OpenVikingClient.search_context()` in [backend/client.py](backend/client.py):
change `"query_expansion": "off"` to `"query_expansion": "auto"`. Keep the other
request fields unchanged. Reinstall the changed plugin with `--force`
and reload the Agent. For an image-based deployment, rebuild and recreate the
QwenPaw container from the modified source; restarting an unchanged image is
not sufficient. To disable query expansion, restore `"off"` and redeploy using
the same steps.

Query expansion was validated against OpenViking v0.5.2.1 with
`commit_policy="auto"`. Follow-up queries used the session history to resolve
project names, including after a project switch. Recall also remained functional
after a message-count-triggered commit retained recent messages. A fresh session
did not use the previous session's history for expansion; the user's long-term
memory library remains shared across sessions.

Expansion requires usable session messages or an archive overview. In the tested
v0.5.2.1 behavior, message-count-triggered automatic commits retain four messages
under the plugin's policy, but idle-timeout commits clear the current messages.
The plugin's `every_turn` requests also retain no messages. Without an archive
overview, expansion falls back to the original query after those messages are
cleared. No live query-expansion validation is claimed here for other versions.
For verification, inspect the response's `stats.query_expansion` and
`stats.planned_queries`; `"used"` means analysis ran, not that extra queries were
necessarily generated.

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

These limits are fixed constants in the plugin source and are not currently
configurable through the Console or Agent configuration.

The Manager caches at most 256 recently used prepared sessions and 10,000
recently recorded completed message IDs. Evicting a session cache entry only
requires preparing that session again; it does not delete remote data.
Evicting a completed message ID ends its local duplicate suppression, so
replaying that older message may append it again. Pending-commit IDs are not
evicted by these limits and are removed after a successful commit; empty
pending entries are not retained. Pending work itself is not globally bounded
by these cache limits. All these progress records are in memory and reset
when the Manager is recreated.
