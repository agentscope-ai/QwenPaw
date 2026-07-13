# Zalo Bot Channel for QwenPaw

Integrates QwenPaw with the [Zalo Bot Platform](https://bot.zalo.me/) via **polling mode**.
No public URL, HTTPS endpoint, or domain is required — only a bot token.

## Quick Start

### Step 1: Create a Zalo Bot

1. Go to <https://bot.zalo.me/> and sign in.
2. Create a new Official Account (OA) + Bot.
3. Save the **Bot Token** (format: `<bot_id>:<secret>`).

### Step 2: Configure the channel

Via the Web UI (`http://<host>:8088` → **Control → Channels → Zalo**) or by editing
`~/.qwenpaw/config.json`:

```json
{
  "channels": {
    "zalo": {
      "enabled": true,
      "bot_token": "<bot_id>:<secret>",
      "poll_interval": 30
    }
  }
}
```

### Step 3: Restart

```bash
systemctl restart qwenpaw
journalctl _PID=$(pgrep -f "qwenpaw app" | head -1) -f | grep zalo
```

Expected logs:

```
[zalo] bot connected: id=<bot_id> name=<display_name>
[zalo] polling started (interval=30s)
```

## Configuration

| Field | Default | Description |
|---|---|---|
| `enabled` | `false` | Enable/disable the channel |
| `bot_token` | `""` | Bot token from the Zalo Bot Platform |
| `poll_interval` | `30` | Seconds between `getUpdates` long-poll calls |
| `max_retries` | `3` | Retry attempts on API error |
| `max_message_len` | `2000` | Character limit per outbound message |
| `bot_prefix` | `""` | Bot only handles messages starting with this prefix |
| `filter_tool_messages` | `true` | Hide tool output from the user |
| `filter_thinking` | `true` | Hide thinking/reasoning output |
| `api_base_url` | *(official)* | Override the Zalo Bot API endpoint (testing/private deployments) |
| `secret_token` | `""` | Optional `X-Api-Key` header value for outbound API calls |
| `allow_from` | `[]` | Whitelist of chat IDs (empty = open) |
| `dm_policy` / `group_policy` | `open` | Access control policy |

## Slash Commands

The bot recognizes and forwards these commands directly to the agent:

- `/help` — Show help
- `/start` — Bot introduction
- `/qwenpaw <query>` — Query the agent (e.g. `/qwenpaw summarize the news`)

## Magic Tokens (image / voice / sticker / file)

Since the Zalo Bot API has no native file upload from the agent side, the agent can
embed magic tokens in its text reply. Tokens are stripped before sending, and the
channel extracts and calls the appropriate API:

| Token | Meaning |
|---|---|
| `[IMAGE: https://...]` | Send an image by URL |
| `[STICKER: sticker_id]` | Send a Zalo sticker |
| `[VOICE: https://...]` | Send a voice message (.ogg/.mp3) |
| `[LOCAL_FILE: /path/to/file]` | Send a local file (PNG/JPG sent directly; PDF/ZIP/XLSX sent as a link) |

Example:

```
Here's the Q4 chart:
[IMAGE: https://example.com/chart.png]
```

When a user sends a photo/sticker/voice message, the bot receives a text marker and
forwards it to the agent for processing.

## Architecture

```
Zalo Bot Platform
       |
       | GET /bot<token>/getUpdates  (long-poll, 30s)
       v
   ZaloChannel._poll_loop  (asyncio task)
       |
       v
   ZaloChannel._dispatch_native_event
       |
       v
   QwenPaw Agent  (manager queue)
       |
       v
   ZaloChannel.send  (text + magic tokens)
       |
       | POST /bot<token>/sendMessage
       | POST /bot<token>/sendPhoto
       | POST /bot<token>/sendSticker
       | POST /bot<token>/sendVoice
       v
   Zalo Bot Platform -> User
```

## Features

- Two-way text + image + sticker + voice
- Typing indicator (auto, while the agent is processing)
- Slash commands (`/help`, `/start`, `/qwenpaw`)
- Smart text routing (extract URLs and magic tokens from plain text)
- Offset tracking (long-poll is idempotent, no duplicate events)
- Deduplication (seen `message_ids`)
- Null/empty filtering (skips LLM "null" / "None" leaks)

## Limitations

- Polling only (no webhook) — suitable for a personal single-instance bot
- 30s long-poll latency (acceptable for chat)
- No native file upload via the Zalo API — must use a public URL or `LOCAL_FILE`
- Polling holds one keep-alive HTTP connection to the Zalo API

## Troubleshooting

**Bot does not respond:**

1. Verify the token: `curl https://bot-api.zaloplatforms.com/bot<TOKEN>/getMe`
2. Check the journal: `journalctl _PID=$(pgrep -f "qwenpaw app" | head -1) -f | grep zalo`
3. Test sending manually:
   ```bash
   curl -X POST https://bot-api.zaloplatforms.com/bot<TOKEN>/sendMessage \
        -H "Content-Type: application/json" \
        -d '{"recipient":{"id":"<chat_id>"},"message":{"text":"test"}}'
   ```

**User sends a message but no log appears:**

- The message may be filtered by `allow_from` or `bot_prefix`
- Check the `bot_prefix` config value
