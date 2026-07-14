# Zalo Bot Channel — QwenPaw Plugin

A [Zalo Bot Platform](https://bot.zalo.me/) channel for QwenPaw 2.0. It
connects your agent to Zalo so users can chat with it directly in Zalo
private chats and groups.

> **Polling-only.** No public URL, domain, HTTPS cert, or webhook is
> required — the channel long-polls Zalo's `getUpdates` API in a
> background task. Ideal for a personal bot running on a single
> instance behind NAT.

## Install

This plugin ships with QwenPaw. It can also be installed from the
plugin market or by dropping the folder into
`~/.qwenpaw/plugins/channel/zalo/`.

It depends on `httpx` (listed in `requirements.txt`).

## Configure

Enable the channel in the QwenPaw console or in `config.json`:

```jsonc
{
  "channels": {
    "zalo": {
      "enabled": true,
      "bot_token": "<OA_ID>:<SECRET>",          // from Zalo Bot Platform
      "api_base_url": "https://bot-api.zaloplatforms.com", // default
      "poll_interval": 30,                       // seconds, min 1
      "show_typing": true,
      "max_retries": 3,
      "max_message_len": 2000                    // Zalo Bot hard limit
    }
  }
}
```

| Field | Default | Notes |
| --- | --- | --- |
| `bot_token` | — | **Required.** `<OA_ID>:<SECRET>` from Zalo Bot Platform › Settings › Bot Token. |
| `api_base_url` | `https://bot-api.zaloplatforms.com` | Override only if you use a different Zalo endpoint. |
| `secret_token` | auto-generated | Webhook verification secret; unused in polling mode. |
| `poll_interval` | `30` | Seconds between `getUpdates` polls. Minimum `1`. |
| `show_typing` | `true` | Send a typing indicator while the agent is thinking. |
| `max_retries` | `3` | Retries on 5xx / network errors. |
| `max_message_len` | `2000` | Zalo Bot Platform hard limit per message. |

### Access control (shared fields)

| Field | Default | Notes |
| --- | --- | --- |
| `share_session_in_group` | `true` | Share one conversation context across all group members. |
| `access_control_dm` | `false` | Restrict DMs to whitelisted users. |
| `access_control_group` | `false` | Restrict group chats to whitelisted users. |
| `require_mention` | `false` | Only reply in groups when explicitly @mentioned. |

## How it works

- **Inbound:** a background task calls `getUpdates` every `poll_interval`
  seconds. New messages are routed to the agent. Private chats use the
  session id `zalo:<user_id>`; group chats share one session
  `zalo:group:<chat_id>` (when `share_session_in_group` is on) so the
  whole group keeps one context. Group messages are prefixed with
  `[<sender> trong nhóm <chat_id>]:` so the agent can tell who is
  speaking.
- **Outbound:** replies are sent via the Zalo Bot send API. The channel
  also scans plain-text replies for image / sticker / voice tokens
  (`[IMAGE: url]`, `[STICKER: id]`, `[VOICE: url]`, Markdown image, or a
  bare image URL) and routes them to the correct API method, so an
  agent that only emits text can still send rich media.

## Architecture

```
plugins/channel/zalo/
├── plugin.json          # plugin manifest (id, deps, qwenpaw version)
├── plugin.py            # entry: api.register_channel(...) + i18n fields
├── requirements.txt     # httpx
├── zalo/
│   ├── __init__.py
│   ├── channel.py       # ZaloChannel — lifecycle, session, send
│   ├── client.py        # ZaloClient — Zalo Bot Platform HTTP client
│   ├── dispatch.py      # event → content items
│   ├── routing.py       # outbound smart-text routing
│   ├── thinking.py      # <think>...</think> + null-token stripping
│   └── tools/
│       └── register_webhook.py   # optional webhook-registration script
└── tests/
    ├── test_group_chat.py
    └── test_round_trip.py
```

## Group chat behavior

The session key is **chat-based**, not sender-based:

- Private chat → `zalo:<user_id>`
- Group chat → `zalo:group:<chat_id>` (one shared context)

This fixes the common custom-channel pitfall where every member of a
group gets a separate session and the agent loses the group's shared
context.

## License

Same as the QwenPaw project.
