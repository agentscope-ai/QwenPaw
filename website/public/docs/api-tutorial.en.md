# RESTful API

This document will guide you through using the RESTful API to interact with QwenPaw Agents.

> **Protocol Details**: QwenPaw's API is based on an extension of the AgentScope Runtime protocol. For more details, see:
> [AgentScope Runtime Protocol Documentation (English)](https://runtime.agentscope.io/en/protocol.html)

> ⚠️ **Security Warning**:
> If your QwenPaw instance is **exposed to the public internet**, strongly recommend enabling [Web Login Authentication](./security#web-authentication)!
> Public instances without authentication pose serious security risks, allowing anyone to access and control your Agents.
> See the [Web Authentication Token](#web-authentication-token-optional) section at the end of this document.

## Overview

QwenPaw provides a RESTful API interface that allows you to interact with Agents via HTTP requests. Through the API, you can:

- Send messages to Agents and receive responses
- Manage multiple Agent instances
- Integrate with different channels

## API Endpoint

The main chat interface is:

```
POST /api/console/chat
```

**Important**: Note the path is `/api/console/chat` not `/console/chat` - all APIs are under the `/api` prefix.

## Authentication

### Agent ID (Required)

Specify the Agent to interact with via the `X-Agent-Id` header:

```bash
-H "X-Agent-Id: default"
```

**Getting Your Agent ID**:

1. Check the currently selected Agent in the top-left corner of Console
2. The Agent ID is typically displayed in the Agent selector
3. The default Agent ID is `default`

### Localhost Auto-Bypass Authentication

⚠️ **Important Notice**:

- **Requests from `localhost` (127.0.0.1 or ::1) automatically bypass Web authentication**
- This is designed for local development and CLI tools (`qwenpaw`) convenience
- Even if Web authentication is enabled, local requests do **NOT** require an `Authorization` token
- If accessing from a **remote machine**, you must provide a valid authentication token

**Examples**:

```bash
# Local request - No Authorization token needed
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{"input": [...]}'

# Remote request - Authorization token required
curl -X POST http://your-server.com:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "X-Agent-Id: default" \
  -d '{"input": [...]}'
```

> **Tip**: If [Web Login Authentication](./security#web-authentication) is enabled and you're accessing remotely, you'll need to provide an authentication token. See the [Web Authentication Token](#web-authentication-token-optional) section at the end of this document.

## Request Format

The API uses a specific message format, similar to OpenAI's message format:

```json
{
  "input": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "Your message here"
        }
      ]
    }
  ],
  "session_id": "my-session",
  "user_id": "user-001",
  "channel": "console"
}
```

### Parameter Explanation

- **input** (required): Message array
  - `role`: Role, typically "user"
  - `content`: Content array
    - `type`: Content type, typically "text"
    - `text`: Actual text content
- **session_id** (optional): Session ID for maintaining context continuity
- **user_id** (optional): User ID to identify different users
- **channel** (recommended): Channel name, recommend setting to "console"

## Making API Calls with cURL

### Basic Example

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "Hello, please introduce yourself"
          }
        ]
      }
    ],
    "session_id": "my-session",
    "user_id": "my-user",
    "channel": "console"
  }' \
  --no-buffer
```

### Parameter Explanation

- **URL**: `http://localhost:8088/api/console/chat` (modify if deployed elsewhere)
- **Headers**:
  - `Content-Type: application/json`: Specifies JSON format for the request body
  - `X-Agent-Id: default`: Specifies the Agent ID, defaults to `default`
- **--no-buffer**: Disables buffering for real-time streaming response

### Complete Example

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "Please summarize today'\''s tasks for me"
          }
        ]
      }
    ],
    "session_id": "my-session-001",
    "user_id": "user-001",
    "channel": "console"
  }' \
  --no-buffer
```

## Response Format

The API returns **Server-Sent Events (SSE)** streaming responses, with each event prefixed with `data:`:

```
data: {"sequence_number":0,"object":"response","status":"created",...}

data: {"sequence_number":1,"object":"response","status":"in_progress",...}

data: {"sequence_number":2,"object":"response","status":"in_progress","output":[{"role":"assistant","content":[{"type":"text","text":"Hello! I'm QwenPaw..."}]}],...}

data: {"sequence_number":3,"object":"response","status":"completed",...}
```

### Response Field Explanation

- **sequence_number**: Event sequence number
- **object**: Object type, typically "response"
- **status**: Status
  - `created`: Created
  - `in_progress`: In progress
  - `completed`: Completed
  - `failed`: Failed
- **output**: Output content (included during processing and completion)
  - `role`: Role, typically "assistant"
  - `content`: Content array
    - `type`: Content type
    - `text`: Text content
- **error**: Error information (included on failure)
- **session_id**: Session ID
- **usage**: Token usage statistics (included on completion)

## Multi-turn Conversation

QwenPaw automatically manages conversation context through `session_id` and `user_id`. Simply use the same `session_id` across different requests, and the system will automatically save and load conversation history:

**First turn**:

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "My name is Alice"}]
      }
    ],
    "session_id": "my-session-001",
    "user_id": "user-001",
    "channel": "console"
  }'
```

**Second turn** (using the same `session_id`):

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "Do you remember my name?"}]
      }
    ],
    "session_id": "my-session-001",
    "user_id": "user-001",
    "channel": "console"
  }'
```

**Important**:

- No need to include message history in `input` - the system automatically loads context based on `session_id`
- Keep `session_id` and `user_id` consistent to maintain conversation continuity

## Error Handling

### Common Errors

#### 405 Method Not Allowed

```
{"detail":"Method Not Allowed"}
```

**Solutions**:

- Confirm you're using the `POST` method
- Verify the URL path is correct: `/api/console/chat` (note the `/api` prefix)

#### 400 Bad Request

```json
{
  "detail": "Validation error"
}
```

**Solutions**:

- Check the request body format is correct
- Ensure the `input` field exists and is properly formatted
- Verify JSON format is valid

#### 404 Agent Not Found

```json
{
  "detail": "Agent not found"
}
```

**Solutions**:

- Check the value of the `X-Agent-Id` header
- Confirm the Agent has been created in Console

#### 503 Channel Not Found

```json
{
  "detail": "Channel Console not found"
}
```

**Solutions**:

- Confirm the Console channel is enabled
- Check channel status in Console → Settings → Channels

## Complete Python Example

Using standard library `urllib` and `json` to handle SSE streams:

```python
import urllib.request
import json

API_URL = "http://localhost:8088/api/console/chat"
AGENT_ID = "default"
AUTH_TOKEN = ""  # Set your token here if authentication is enabled

def chat_with_agent(message, session_id="my-session"):
    # Prepare request
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Id": AGENT_ID
    }

    # Add auth token if available
    if AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"

    data = {
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": message
                    }
                ]
            }
        ],
        "session_id": session_id,
        "user_id": "python-user",
        "channel": "console"
    }

    # Send request
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(data).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    # Handle streaming response
    try:
        with urllib.request.urlopen(request) as response:
            for line in response:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    event_data = json.loads(line[6:])  # Remove 'data: ' prefix

                    # Print status
                    status = event_data.get('status')
                    print(f"Status: {status}")

                    # Extract reply content
                    if event_data.get('output'):
                        for item in event_data['output']:
                            if item.get('role') == 'assistant':
                                for content in item.get('content', []):
                                    if content.get('type') == 'text':
                                        print(f"Reply: {content.get('text')}")

                    # Check for errors
                    if event_data.get('error'):
                        error = event_data['error']
                        print(f"Error: {error.get('message')}")

    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"Error: {e}")

# Usage example
if __name__ == "__main__":
    chat_with_agent("Hello, please introduce yourself")
```

### Using requests Library (Recommended)

If you have the `requests` library installed, you can use this more concise code:

```python
import requests
import json

API_URL = "http://localhost:8088/api/console/chat"
LOGIN_URL = "http://localhost:8088/api/auth/login"
AGENT_ID = "default"

def get_auth_token(username, password):
    """Get authentication token (if authentication is enabled)"""
    response = requests.post(LOGIN_URL, json={
        "username": username,
        "password": password
    })
    if response.status_code == 200:
        return response.json()["token"]
    return None

def chat_with_agent(message, session_id="my-session", auth_token=None):
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Id": AGENT_ID
    }

    # Add auth token if provided
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    data = {
        "input": [
            {
                "role": "user",
                "content": [{"type": "text", "text": message}]
            }
        ],
        "session_id": session_id,
        "user_id": "python-user",
        "channel": "console"
    }

    # Streaming request
    with requests.post(API_URL, headers=headers, json=data, stream=True) as response:
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    event_data = json.loads(line[6:])
                    status = event_data.get('status')

                    if status == 'in_progress' or status == 'completed':
                        if event_data.get('output'):
                            for item in event_data['output']:
                                if item.get('role') == 'assistant':
                                    for content in item.get('content', []):
                                        if content.get('type') == 'text':
                                            print(content.get('text'), end='', flush=True)

                    if event_data.get('error'):
                        print(f"\nError: {event_data['error'].get('message')}")
                        break

# Usage examples
# 1. Without authentication
chat_with_agent("Hello, please introduce yourself")

# 2. With authentication
# token = get_auth_token("admin", "admin123")
# chat_with_agent("Hello, please introduce yourself", auth_token=token)
```

## Complete JavaScript Example

Using the `fetch` API in Node.js:

```javascript
const API_URL = "http://localhost:8088/api/console/chat";
const LOGIN_URL = "http://localhost:8088/api/auth/login";
const AGENT_ID = "default";

// Get authentication token (if authentication is enabled)
async function getAuthToken(username, password) {
  try {
    const response = await fetch(LOGIN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (response.ok) {
      const data = await response.json();
      return data.token;
    }
  } catch (error) {
    console.error("Login failed:", error);
  }
  return null;
}

async function chatWithAgent(
  message,
  sessionId = "my-session",
  authToken = null,
) {
  const headers = {
    "Content-Type": "application/json",
    "X-Agent-Id": AGENT_ID,
  };

  // Add auth token if provided
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }

  const response = await fetch(API_URL, {
    method: "POST",
    headers,
    body: JSON.stringify({
      input: [
        {
          role: "user",
          content: [
            {
              type: "text",
              text: message,
            },
          ],
        },
      ],
      session_id: sessionId,
      user_id: "js-user",
      channel: "console",
    }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split("\n");

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const eventData = JSON.parse(line.slice(6));

        const status = eventData.status;
        console.log("Status:", status);

        // Extract reply
        if (eventData.output) {
          for (const item of eventData.output) {
            if (item.role === "assistant") {
              for (const content of item.content || []) {
                if (content.type === "text") {
                  console.log("Reply:", content.text);
                }
              }
            }
          }
        }

        // Check for errors
        if (eventData.error) {
          console.error("Error:", eventData.error.message);
        }
      }
    }
  }
}

// Usage examples
// 1. Without authentication
chatWithAgent("Hello, please introduce yourself").catch((error) =>
  console.error("Error:", error),
);

// 2. With authentication
// (async () => {
//   const token = await getAuthToken('admin', 'admin123');
//   if (token) {
//     await chatWithAgent('Hello, please introduce yourself', 'my-session', token);
//   }
// })();
```

## Best Practices

1. **Session Management**: Use consistent `session_id` to maintain conversation context
2. **Error Handling**: Always handle network errors and API error responses
3. **Stream Processing**: Use streaming reads to avoid memory issues
4. **Connection Timeout**: Set reasonable timeout values to avoid long waits
5. **Retry Mechanism**: Implement retry logic with exponential backoff
6. **Logging**: Log API calls for debugging and monitoring

## Advanced Usage

### Multi-Agent Switching

Interact with different Agents by changing the `X-Agent-Id` header:

```bash
# Chat with Agent 1
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: agent-1" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"Hello"}]}],"channel":"console"}'

# Chat with Agent 2
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: agent-2" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"Hello"}]}],"channel":"console"}'
```

### Web Authentication Token (Optional)

If [Web Login Authentication](./security#web-authentication) is enabled (`QWENPAW_AUTH_ENABLED=true`), all API requests require an authentication token.

#### Register Account

**First-time setup requires registering an admin account** (QwenPaw uses single-user mode):

```bash
curl -X POST http://localhost:8088/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123"
  }'
```

**Response Example**:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "username": "admin"
}
```

**Register with Custom Token Expiration**:

```bash
# Register and get a permanent token
curl -X POST http://localhost:8088/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "expires_in": 0
  }'
```

**Important Notes**:

- Registration endpoint can only be called once (single-user mode)
- Registration returns a login token immediately
- Returns `{"detail":"User already registered"}` error if a user already exists
- Supports custom token expiration via `expires_in` parameter (same as login)

**If you need to re-register** (e.g., forgot password or want to change account):

Method 1: Use CLI to reset password

```bash
qwenpaw auth reset-password
```

Method 2: Delete auth file and re-register

```bash
# Delete auth file
rm ~/.qwenpaw.secret/auth.json

# Or use QWENPAW_SECRET_DIR environment variable
rm "${QWENPAW_SECRET_DIR}/auth.json"

# Restart QwenPaw and re-register
qwenpaw app
```

**Docker Deployment**:

```bash
# Enter container to delete auth file
docker exec -it <container_name> rm /app/working.secret/auth.json

# Or use CLI to reset password
docker exec -it <container_name> qwenpaw auth reset-password
```

**Auto-Registration** (Optional):

You can also auto-create an account via environment variables when starting QwenPaw:

```bash
export QWENPAW_AUTH_ENABLED=true
export QWENPAW_AUTH_USERNAME=admin
export QWENPAW_AUTH_PASSWORD=admin123
qwenpaw app
```

This eliminates the need to manually call the registration API.

#### Obtaining an Authentication Token

**After registration, use the login API to get a token**

```bash
curl -X POST http://localhost:8088/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123"
  }'
```

**Response Example**:

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "username": "admin"
}
```

**Customize Token Expiration**:

You can specify token expiration time using the `expires_in` parameter (in seconds):

```bash
# Request a 30-day token
curl -X POST http://localhost:8088/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "expires_in": 2592000
  }'

# Request a permanent token (100-year validity)
curl -X POST http://localhost:8088/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "expires_in": 0
  }'
```

**Common Expiration Values**:

- `604800` = 7 days (default)
- `2592000` = 30 days
- `31536000` = 1 year
- `0` or `-1` = permanent token (100 years)

**Step 2: Use Token in API Requests**

Add the returned `token` to the `Authorization` header:

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "Hello"}]
      }
    ],
    "session_id": "my-session",
    "user_id": "my-user",
    "channel": "console"
  }'
```

#### Token Characteristics

- **Validity**:
  - Default: 7 days
  - Customizable via `expires_in` parameter (supports permanent tokens)
  - Maximum: 100 years
- **Format**: HMAC-SHA256 signed token
- **Storage**: Store securely, do not hardcode in code
- **Local Bypass**: Requests from `127.0.0.1` or `::1` automatically skip authentication
- **Multiple Tokens**:
  - ⚠️ Each login creates a new token; old tokens are NOT automatically revoked
  - Multiple tokens can be used simultaneously if they are valid and not expired
  - If a token is compromised, you need to manually revoke all tokens

#### Revoking Tokens

If you need to invalidate tokens (e.g., logout, token leak, or security incident):

**Method 1: Revoke a Single Token** (Recommended for logout or specific device revocation)

```bash
# Revoke current token (logout current session)
curl -X POST http://localhost:8088/api/auth/revoke-token \
  -H "Authorization: Bearer <YOUR_CURRENT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Revoke a specific token (e.g., leaked token)
curl -X POST http://localhost:8088/api/auth/revoke-token \
  -H "Authorization: Bearer <YOUR_CURRENT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "eyJhbGciOi..."
  }'
```

**Response Example**:

```json
{
  "message": "Current token has been revoked. Please login again.",
  "revoked": true,
  "revoked_current_token": true
}
```

**Method 2: Revoke All Tokens** (For security incidents or password reset)

```bash
curl -X POST http://localhost:8088/api/auth/revoke-all-tokens \
  -H "Authorization: Bearer <YOUR_CURRENT_TOKEN>"
```

**Response Example**:

```json
{
  "message": "All tokens have been revoked. Please login again.",
  "revoked": true
}
```

**Method 3: Change Password** (Also revokes all tokens)

Changing your password automatically rotates the JWT secret, invalidating all old tokens:

```bash
curl -X POST http://localhost:8088/api/auth/update-profile \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "current_password": "old_password",
    "new_password": "new_password"
  }'
```

**Comparison of Revocation Methods**:

| Method              | Scope  | Advantages                                    | Disadvantages                 | Use Cases                         |
| ------------------- | ------ | --------------------------------------------- | ----------------------------- | --------------------------------- |
| Revoke Single Token | Single | Precise control, doesn't affect other devices | Need to know token content    | Logout, revoke specific device    |
| Revoke All Tokens   | All    | Invalidates all sessions at once              | All devices need re-login     | Security incidents, password leak |
| Change Password     | All    | Updates password and revokes tokens           | Need to remember old password | Regular password updates          |
| Delete auth file    | All    | Complete reset (including password)           | Requires server access        | Full system reset                 |

**Important Notes**:

- After revocation, all clients must re-login to get new tokens
- Revocation is irreversible
- Recommended to revoke immediately when tokens are compromised or devices are lost
- If using permanent tokens (`expires_in: 0`), strongly recommend periodic manual revocation and reissuance

#### Disabling Authentication

If you don't want to use Web authentication, you can disable it:

**Method 1: Remove Environment Variable**

```bash
# Linux / macOS
unset QWENPAW_AUTH_ENABLED
qwenpaw app

# Windows (CMD)
set QWENPAW_AUTH_ENABLED=
qwenpaw app

# Windows (PowerShell)
Remove-Item Env:\QWENPAW_AUTH_ENABLED
qwenpaw app
```

**Method 2: Docker Deployment**

Remove the `-e QWENPAW_AUTH_ENABLED=true` parameter:

```bash
docker run -p 127.0.0.1:8088:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  agentscope/qwenpaw:latest
```

**Important**:

- After disabling authentication, all API requests **do not need** the `Authorization` header
- If authentication is **not enabled**, no `Authorization` header is needed
- Check authentication status: `GET /api/auth/status`

## Troubleshooting

### Cannot Connect to Server

Verify QwenPaw service is running:

```bash
# Check service status
curl http://localhost:8088/api/version
```

### Response Interrupted

If streaming response is interrupted, check:

1. Network connection stability
2. Server is running properly
3. Model configuration is correct

### Model Execution Failed

If you see `MODEL_EXECUTION_FAILED` error:

1. Confirm models are properly configured in Console → Settings → Models
2. Check if API Key is valid
3. Verify model name is correct
4. Check the error details file (path provided in error message)

## Related Documentation

- [Console Guide](./console)
- [Security Settings](./security)
- [Multi-Agent](./multi-agent)
- [Channels Configuration](./channels)

## Getting Help

If you encounter issues using the API:

1. Check the [FAQ](./faq) for common questions
2. Join the [Community](./community) for assistance
3. Submit an [Issue](https://github.com/agentscope-ai/QwenPaw/issues) on GitHub
