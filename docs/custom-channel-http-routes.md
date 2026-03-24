# Custom Channel HTTP Route Registration

## Overview

CoPaw allows custom channels to register their own HTTP routes at startup. This is useful for channels that need webhook callbacks (e.g., WeChat, Slack, LINE) without modifying CoPaw's core source code.

## How It Works

At startup, CoPaw scans the `custom_channels/` directory in your workspace for modules that export a `register_app_routes` callable. If found, CoPaw calls it with the FastAPI `app` instance, allowing the channel to register any routes it needs.

## Quick Start: Minimal Echo Channel

### 1. Create the channel module

```
<workspace>/
└── custom_channels/
    └── my_echo/
        └── __init__.py
```

```python
# custom_channels/my_echo/__init__.py
from copaw.app.channels.base import BaseChannel

class MyEchoChannel(BaseChannel):
    """A minimal channel that echoes messages back."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def _listen(self):
        pass  # Inbound messages are handled via HTTP callback

    async def _send(self, target, content, **kwargs):
        # For this example, we just log it
        self.logger.info(f"Would send to {target}: {content}")


def register_app_routes(app):
    """Register HTTP routes for this channel."""

    @app.post("/api/my-echo/callback")
    async def echo_callback(request):
        """Webhook endpoint for incoming messages."""
        body = await request.json()

        # Forward to CoPaw agent
        from copaw.app.channels.base import TextContent, RunStatus
        channel = MyEchoChannel()
        channel.enqueue_user_message(
            user_id=body.get("user_id", "anonymous"),
            session_id=body.get("session_id", "default"),
            content=[TextContent(type="text", text=body.get("text", ""))],
        )

        return {"status": "ok"}
```

### 2. Configure the channel

Add to your CoPaw `config.json`:

```json
{
  "channels": {
    "my_echo": {
      "enabled": true
    }
  }
}
```

### 3. Start CoPaw

```bash
copaw start
```

You should see a log confirming the route was registered. Test it:

```bash
curl -X POST http://localhost:8088/api/my-echo/callback \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "session_id": "test", "text": "Hello!"}'
```

## Route Registration Rules

| Route prefix | Behavior |
|---|---|
| `/api/` | Registered silently |
| Other paths | Warning logged at startup (not blocked) |

## Key Interfaces

### `register_app_routes(app)`

- **Parameter**: `app` — FastAPI application instance
- **Return**: None
- **Scope**: Register routes, middleware, or startup/shutdown events
- **Error handling**: Errors are isolated — one channel's failure does not affect others

### `BaseChannel`

Your channel class should inherit from `copaw.app.channels.base.BaseChannel`. Key methods:

- `enqueue_user_message(user_id, session_id, content)` — Push a user message into the agent pipeline
- `_listen()` — Start listening for inbound messages (not needed for HTTP callback channels)
- `_send(target, content, **kwargs)` — Send agent reply to the user

## Real-World Example: WeChat ClawBot

A production example using this mechanism is the WeChat ClawBot integration:

- Uses `register_app_routes` to register `/api/wechat/callback`
- Handles message delivery via Tencent's official SDK (`@tencent-weixin/openclaw-weixin`)
- See PR #2140 and Issue #2043 for details

## File Structure Convention

```
<workspace>/
└── custom_channels/
    └── <channel_name>/
        ├── __init__.py          # Channel class + register_app_routes
        ├── requirements.txt     # Channel-specific dependencies
        └── README.md            # Channel documentation
```

CoPaw discovers custom channels by scanning `custom_channels/` for subdirectories containing `__init__.py` with a class that inherits from `BaseChannel`.
