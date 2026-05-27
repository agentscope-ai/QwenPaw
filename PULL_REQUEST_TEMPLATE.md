# Feishu Channel: Topic/Thread Reply Support

## Description

Add support for topic/thread reply in Feishu channel. When a user sends a message in a Feishu topic (thread), QwenPaw now replies within the same thread using the Feishu Reply API, instead of sending a new top-level message.

### Detailed Usage Scenarios

| # | Scenario | Expected Behavior | Mechanism |
|---|----------|-------------------|-----------|
| 1 | **话题群新话题 @agent** | Bot 在该话题下回复 | `thread_id` 提取到 meta，`user_id` 改写为 `thread:{short_id}`，通过 `_reply_in_thread` 发送 post 消息 |
| 2 | **普通群 @agent（无话题）** | 普通消息回复，不触发话题模式 | 无 `thread_id`，走正常 `_send_text`/`_send_image` 流程 |
| 3 | **话题下（话题群&普通群）@agent** | 继续在该话题下回复，可看到引用内容 | `thread_id` 生效，`_reply_in_thread` 回复，`parent_id` 引用内容一并处理 |
| 4 | **话题下不 @agent** | 不回复 | `_check_group_mention` 因 `require_mention=True` 返回 False，消息丢弃 |
| 5 | **话题下不 @agent，编辑消息补上 @** | 不回复 | Feishu 编辑事件带相同 `message_id`，`_processed_message_ids` 去重丢弃 |

**Key design decisions:**
- Thread replies use `post` format (not interactive card), because Feishu topics do not support streaming card updates
- Messages in the same thread share a single session context (`user_id` mapped to `thread:{thread_id}`)
- Streaming output is automatically disabled for thread messages

## Type of Change

- [x] Feature

## Component(s) Affected

- [x] Channels (Feishu)
- [x] Tests

## Changes Made

### `src/qwenpaw/app/channels/feishu/channel.py`
- Added `ReplyMessageRequest` and `ReplyMessageRequestBody` to lark-oapi imports
- Added `_reply_in_thread()` method — uses `ReplyMessageRequest` with `reply_in_thread=True` to reply within a topic thread
- Modified `_on_message()` — extracts `thread_id` from incoming message events and stores it in `channel_meta`; overrides `user_id` to `thread:{short_id}` for session isolation
- Modified `send_content_parts()` — when `meta` contains `feishu_thread_id`, sends text/image/file via `_reply_in_thread` instead of `_send_text`/`_send_image`/`_send_file`
- Modified `on_streaming_start()` — skips streaming card creation when `feishu_thread_id` is present (threads don't support streaming)
- Modified `_before_consume_process()` — skips streaming card pre-creation for thread messages

### `tests/unit/channels/test_feishu.py`
- Added `TestFeishuChannelThreadReply` class with 17 tests covering:
  - Thread ID extraction from message events
  - No thread ID when not present
  - User ID override to `thread:{short_id}`
  - Thread override wins over shared mode
  - `_reply_in_thread` method: success, no client, empty message_id, SDK failure, exception
  - `send_content_parts` thread reply: text, image, file, audio
  - Normal path unaffected when no thread
  - Streaming skipped for thread messages
  - Card pre-creation skipped for thread messages

## Testing

```bash
# Run thread reply tests
pytest tests/unit/channels/test_feishu.py -v -k "ThreadReply"

# Run all feishu channel tests
pytest tests/unit/channels/test_feishu.py -v
```

### Manual testing checklist
1. Deploy to a Feishu-connected environment
2. Create a topic in a Feishu group where the bot is present
3. Send a message to the bot within the topic
4. Verify:
   - Bot replies within the same thread (not as a new top-level message)
   - Reply is in post format (plain text/markdown, not interactive card)
   - Multiple users in the same thread share conversation context
   - Non-thread messages still work normally (streaming + card)

## Checklist

- [x] Code compiles without errors
- [x] All 137 feishu channel tests pass (17 new + 120 existing)
- [x] Inline code comments added for new logic
- [x] PR description updated with usage scenarios
