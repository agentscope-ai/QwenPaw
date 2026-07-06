# Zalo Bot Channel for QwenPaw

Tich hop Zalo Bot (qua Zalo Bot Platform) voi QwenPaw thong qua **polling mode**.
Khong can public URL, HTTPS, hay domain - chi can bot token.

## Setup nhanh

### Buoc 1: Tao Zalo Bot
1. Vao https://bot.zalo.me/
2. Tao OA + Bot moi
3. Luu **Bot Token** (dang: `<bot_id>:<secret>`)

### Buoc 2: Cau hinh channel

Qua Web UI (`http://<host>:8088`) hoac sua `~/.qwenpaw/config.json`:

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

### Buoc 3: Restart

```bash
systemctl restart qwenpaw
journalctl _PID=$(pgrep -f "qwenpaw app" | head -1) -f | grep zalo
```

Logs mong doi:

```
[zalo] bot connected: id=<bot_id> name=<display_name>
[zalo] polling started (interval=30s)
```

## Cau hinh

| Field | Default | Mo ta |
|---|---|---|
| `enabled` | false | Bat/tat channel |
| `bot_token` | `` | Bot token tu Zalo Bot Platform |
| `poll_interval` | 30 | Giay giua cac getUpdates long-poll |
| `max_retries` | 3 | So lan retry khi API loi |
| `max_message_len` | 2000 | Gioi han ky tu moi message |
| `bot_prefix` | `` | Bot chi xu ly message bat dau bang prefix |
| `filter_tool_messages` | true | An tool output khi user khong muon thay |
| `filter_thinking` | true | An thinking/reasoning output |
| `api_base_url` | https://bot-api.zaloplatforms.com | Zalo Bot API endpoint |
| `allow_from` | [] | Whitelist chat_id (empty = open) |
| `dm_policy` / `group_policy` | open | Quyen truy cap |

## Slash commands

Bot nhan dien va xu ly cac lenh sau (gui truc tiep den agent):

- `/help` - Hien thi tro giup
- `/start` - Gioi thieu bot
- `/qwenpaw <query>` - Truy van agent (vd: `/qwenpaw tom tat tin tuc`)

## Magic tokens (file/voice/image)

Khi agent muon gui file qua Zalo (khong co native upload API), chen magic token
trong text reply. Token bi strip khi gui, channel se trich xuat va goi API phu hop:

| Token | Y nghia |
|---|---|
| `[IMAGE: https://...]` | Gui anh kem |
| `[STICKER: sticker_id]` | Gui sticker Zalo |
| `[VOICE: https://...]` | Gui voice message (.ogg/.mp3) |
| `[LOCAL_FILE: /path/to/file]` | Gui file local (anh PNG/JPG gui truc tiep, PDF/ZIP/XLSX gui link) |

Vi du:

```
Em vua ve chart Q4 cho anh nhe
[IMAGE: https://example.com/chart.png]
```

Khi user gui anh/sticker/voice, bot nhan text marker va forward cho agent xu ly.

## Kien truc

```
Zalo Bot Platform
       |
       | GET /bot<token>/getUpdates  (long-poll 30s)
       v
   ZaloChannel._poll_loop (asyncio task)
       |
       v
   ZaloChannel._dispatch_native_event
       |
       v
   QwenPaw Agent (manager queue)
       |
       v
   ZaloChannel.send (text + magic tokens)
       |
       | POST /bot<token>/sendMessage
       | POST /bot<token>/sendPhoto
       | POST /bot<token>/sendSticker
       | POST /bot<token>/sendVoice
       v
   Zalo Bot Platform -> User
```

## Tinh nang chinh

- 2-way text + image + sticker + voice
- Typing indicator (auto, trong khi agent xu ly)
- Slash commands (`/help`, `/start`, `/qwenpaw`)
- Smart text routing (trich URL va magic tokens tu plain text)
- Offset tracking (long-poll idempotent, khong trung event)
- Dedup (seen message_ids)
- Null/empty filter (skip LLM "null" / "None" leaks)

## Gioi han

- Chi polling (khong webhook) - phu hop personal bot, single instance
- Long-poll 30s latency (acceptable cho chat)
- Khong co native file upload qua Zalo API - phai dung URL public hoac LOCAL_FILE
- Polling giu 1 connection HTTP keepalive toi Zalo API

## Troubleshooting

**Bot khong phan hoi:**

1. Check token: `curl https://bot-api.zaloplatforms.com/bot<TOKEN>/getMe`
2. Check journal: `journalctl _PID=$(pgrep -f "qwenpaw app" | head -1) -f | grep zalo`
3. Test send bang tay:
   ```
   curl -X POST https://bot-api.zaloplatforms.com/bot<TOKEN>/sendMessage \
        -H "Content-Type: application/json" \
        -d '{"recipient":{"id":"<chat_id>"},"message":{"text":"test"}}'
   ```

**User gui tin nhan nhung khong thay log:**

- Co the message bi filter boi `allow_from` hoac `bot_prefix`
- Kiem tra `bot_prefix` config

## Phat trien

```bash
cd ~/.qwenpaw/custom_channels/zalo
/root/.qwenpaw/venv/bin/python3 -c "from custom_channels.zalo import ZaloChannel; print(ZaloChannel)"
```
