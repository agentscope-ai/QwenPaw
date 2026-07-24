# RESTful API 接口

本文档将指导你如何使用 RESTful API 调用 QwenPaw 的 Agent。

> **协议详情**：QwenPaw 的 API 基于 AgentScope Runtime 协议的拓展。更多详细信息请参考：
> [AgentScope Runtime 协议文档（中文）](https://runtime.agentscope.io/zh/protocol.html)

> ⚠️ **安全提醒**：
> 如果您的 QwenPaw 实例对**公网开放**，强烈建议启用 [Web 登录认证](./security#Web-登录认证)！
> 未启用认证的公网实例存在严重安全风险，任何人都可以访问和控制您的 Agent。
> 详见文档末尾的 [Web 认证令牌](#web-认证令牌可选) 章节。

## 概述

QwenPaw 提供了 RESTful API 接口，允许你通过 HTTP 请求与 Agent 进行交互。通过 API，你可以：

- 发送消息给 Agent 并获取回复
- 管理多个 Agent 实例
- 与不同的频道集成

## API 端点

主要的聊天接口为：

```
POST /api/console/chat
```

**重要提示**：请注意路径是 `/api/console/chat` 而不是 `/console/chat`，所有 API 都在 `/api` 前缀下。

## 认证

### Agent ID（必需）

通过 `X-Agent-Id` 头部指定要交互的 Agent：

```bash
-H "X-Agent-Id: default"
```

**获取 Agent ID**：

1. 在 Console 左上角查看当前选中的 Agent
2. Agent ID 通常显示在 Agent 选择器中
3. 默认的 Agent ID 为 `default`

### Localhost 自动免认证

⚠️ **重要提示**：

- **来自 `localhost` (127.0.0.1 或 ::1) 的请求会自动跳过 Web 认证**
- 这是为了方便本地开发和 CLI 工具（`qwenpaw`）使用
- 即使启用了 Web 认证，本地请求也**不需要**提供 `Authorization` 令牌
- 如果从**远程机器**访问，则必须提供有效的认证令牌

**示例**：

```bash
# 本地请求 - 不需要 Authorization 令牌
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{"input": [...]}'

# 远程请求 - 需要 Authorization 令牌
curl -X POST http://your-server.com:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "X-Agent-Id: default" \
  -d '{"input": [...]}'
```

> **提示**：如果启用了 [Web 登录认证](./security#Web-登录认证)并从远程访问，需要提供身份验证令牌。详见文档末尾的 [Web 认证令牌](#web-认证令牌可选) 部分。

## 请求格式

API 使用特定的消息格式，与 OpenAI 的消息格式类似：

```json
{
  "input": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "你的消息内容"
        }
      ]
    }
  ],
  "session_id": "my-session",
  "user_id": "user-001",
  "channel": "console"
}
```

### 参数说明

- **input**（必需）：消息数组
  - `role`: 角色，通常为 "user"
  - `content`: 内容数组
    - `type`: 内容类型，通常为 "text"
    - `text`: 实际的文本内容
- **session_id**（可选）：会话 ID，用于维持上下文连续性
- **user_id**（可选）：用户 ID，用于标识不同的用户
- **channel**（推荐）：频道名称，建议设置为 "console"

## 使用 cURL 调用 API

### 基本示例

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
            "text": "你好，请介绍一下自己"
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

### 参数说明

- **URL**：`http://localhost:8088/api/console/chat`（如果部署在其他地址，请相应修改）
- **Headers**：
  - `Content-Type: application/json`：指定请求体为 JSON 格式
  - `X-Agent-Id: default`：指定 Agent ID，默认为 `default`
- **--no-buffer**：禁用缓冲，实时显示流式响应

### 完整示例

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
            "text": "帮我总结一下今天的任务"
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

## 响应格式

API 返回 **Server-Sent Events (SSE)** 流式响应，每个事件以 `data:` 开头：

```
data: {"sequence_number":0,"object":"response","status":"created",...}

data: {"sequence_number":1,"object":"response","status":"in_progress",...}

data: {"sequence_number":2,"object":"response","status":"in_progress","output":[{"role":"assistant","content":[{"type":"text","text":"你好！我是 QwenPaw..."}]}],...}

data: {"sequence_number":3,"object":"response","status":"completed",...}
```

### 响应字段说明

- **sequence_number**: 事件序号
- **object**: 对象类型，通常为 "response"
- **status**: 状态
  - `created`: 已创建
  - `in_progress`: 处理中
  - `completed`: 已完成
  - `failed`: 失败
- **output**: 输出内容（处理中和完成时包含）
  - `role`: 角色，通常为 "assistant"
  - `content`: 内容数组
    - `type`: 内容类型
    - `text`: 文本内容
- **error**: 错误信息（失败时包含）
- **session_id**: 会话 ID
- **usage**: 令牌使用统计（完成时包含）

## 多轮对话

QwenPaw 通过 `session_id` 和 `user_id` 自动管理对话上下文。只需在不同的请求中使用相同的 `session_id`，系统会自动保存和加载对话历史：

**第一轮对话**：

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "我的名字是小明"}]
      }
    ],
    "session_id": "my-session-001",
    "user_id": "user-001",
    "channel": "console"
  }'
```

**第二轮对话**（使用相同的 `session_id`）：

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "你还记得我的名字吗？"}]
      }
    ],
    "session_id": "my-session-001",
    "user_id": "user-001",
    "channel": "console"
  }'
```

**重要提示**：

- 无需在 `input` 中包含历史消息，系统会自动基于 `session_id` 加载上下文
- 保持 `session_id` 和 `user_id` 一致即可维持对话连续性

## 错误处理

### 常见错误

#### 405 Method Not Allowed

```
{"detail":"Method Not Allowed"}
```

**解决方法**：

- 确认使用的是 `POST` 方法
- 确认 URL 路径正确：`/api/console/chat`（注意 `/api` 前缀）

#### 400 Bad Request

```json
{
  "detail": "Validation error"
}
```

**解决方法**：

- 检查请求体格式是否正确
- 确认 `input` 字段存在且格式正确
- 验证 JSON 格式有效

#### 404 Agent Not Found

```json
{
  "detail": "Agent not found"
}
```

**解决方法**：

- 检查 `X-Agent-Id` 头部的值
- 确认该 Agent 已在 Console 中创建

#### 503 Channel Not Found

```json
{
  "detail": "Channel Console not found"
}
```

**解决方法**：

- 确认 Console 频道已启用
- 在 Console → Settings → Channels 中检查频道状态

## 完整 Python 示例

使用标准库 `urllib` 和 `json` 处理 SSE 流：

```python
import urllib.request
import json

API_URL = "http://localhost:8088/api/console/chat"
AGENT_ID = "default"
AUTH_TOKEN = ""  # 如果启用了认证，在这里设置你的 token

def chat_with_agent(message, session_id="my-session"):
    # 准备请求
    headers = {
        "Content-Type": "application/json",
        "X-Agent-Id": AGENT_ID
    }

    # 如果有 auth token，添加到请求头
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

    # 发送请求
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(data).encode('utf-8'),
        headers=headers,
        method='POST'
    )

    # 处理流式响应
    try:
        with urllib.request.urlopen(request) as response:
            for line in response:
                line = line.decode('utf-8').strip()
                if line.startswith('data: '):
                    event_data = json.loads(line[6:])  # 去掉 'data: ' 前缀

                    # 打印状态
                    status = event_data.get('status')
                    print(f"状态: {status}")

                    # 提取回复内容
                    if event_data.get('output'):
                        for item in event_data['output']:
                            if item.get('role') == 'assistant':
                                for content in item.get('content', []):
                                    if content.get('type') == 'text':
                                        print(f"回复: {content.get('text')}")

                    # 检查错误
                    if event_data.get('error'):
                        error = event_data['error']
                        print(f"错误: {error.get('message')}")

    except urllib.error.HTTPError as e:
        print(f"HTTP 错误: {e.code} - {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"错误: {e}")

# 使用示例
if __name__ == "__main__":
    chat_with_agent("你好，请介绍一下自己")
```

### 使用 requests 库（推荐）

如果你安装了 `requests` 库，可以使用以下更简洁的代码：

```python
import requests
import json

API_URL = "http://localhost:8088/api/console/chat"
LOGIN_URL = "http://localhost:8088/api/auth/login"
AGENT_ID = "default"

def get_auth_token(username, password):
    """获取认证令牌（如果启用了认证）"""
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

    # 如果提供了 auth token，添加到请求头
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

    # 流式请求
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
                        print(f"\n错误: {event_data['error'].get('message')}")
                        break

# 使用示例
# 1. 不使用认证
chat_with_agent("你好，请介绍一下自己")

# 2. 使用认证
# token = get_auth_token("admin", "admin123")
# chat_with_agent("你好，请介绍一下自己", auth_token=token)
```

## 完整 JavaScript 示例

在 Node.js 中使用 `fetch` API：

```javascript
const API_URL = "http://localhost:8088/api/console/chat";
const LOGIN_URL = "http://localhost:8088/api/auth/login";
const AGENT_ID = "default";

// 获取认证令牌（如果启用了认证）
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

  // 如果提供了 auth token，添加到请求头
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
        console.log("状态:", status);

        // 提取回复
        if (eventData.output) {
          for (const item of eventData.output) {
            if (item.role === "assistant") {
              for (const content of item.content || []) {
                if (content.type === "text") {
                  console.log("回复:", content.text);
                }
              }
            }
          }
        }

        // 检查错误
        if (eventData.error) {
          console.error("错误:", eventData.error.message);
        }
      }
    }
  }
}

// 使用示例
// 1. 不使用认证
chatWithAgent("你好，请介绍一下自己").catch((error) =>
  console.error("错误:", error),
);

// 2. 使用认证
// (async () => {
//   const token = await getAuthToken('admin', 'admin123');
//   if (token) {
//     await chatWithAgent('你好，请介绍一下自己', 'my-session', token);
//   }
// })();
```

## 最佳实践

1. **会话管理**：使用一致的 `session_id` 来维持对话上下文
2. **错误处理**：始终处理网络错误和 API 错误响应
3. **流式处理**：使用流式读取避免内存问题
4. **连接超时**：设置合理的超时时间，避免长时间等待
5. **重试机制**：实现指数退避的重试逻辑
6. **日志记录**：记录 API 调用日志，便于调试和监控

## 进阶用法

### 多 Agent 切换

与不同的 Agent 交互只需更改 `X-Agent-Id` 头部：

```bash
# 与 Agent 1 对话
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: agent-1" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"你好"}]}],"channel":"console"}'

# 与 Agent 2 对话
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Id: agent-2" \
  -d '{"input":[{"role":"user","content":[{"type":"text","text":"你好"}]}],"channel":"console"}'
```

### Web 认证令牌（可选）

如果启用了 [Web 登录认证](./security#Web-登录认证)（`QWENPAW_AUTH_ENABLED=true`），所有 API 请求都需要提供身份验证令牌。认证完全委托给 **NocoBase** —— QwenPaw 自身不再拥有本地账号存储，用户和密码均由 NocoBase 管理。

#### 启用认证

设置 `QWENPAW_AUTH_ENABLED=true` 以及 NocoBase 连接相关的环境变量：

```bash
export QWENPAW_AUTH_ENABLED=true
export QWENPAW_NOCOBASE_ENABLED=true
export QWENPAW_NOCOBASE_BASE_URL=http://nocobase:13000
qwenpaw app
```

首次启动时，这些 `QWENPAW_NOCOBASE_*` 环境变量会被写入 `~/.qwenpaw/nocobase_auth_config.json` 作为初始配置。此后应在控制台插件管理页中编辑连接信息（Base URL、管理员 API Token、用户标识字段、认证器、角色→频道映射），而不是重新导出环境变量。完整的 `QWENPAW_NOCOBASE_*` 变量列表见 [安全设置 → Web 登录认证](./security#Web-登录认证)。

**查看认证状态**：

```bash
curl http://localhost:8088/api/auth/status
```

**响应示例**：

```json
{
  "enabled": true,
  "mode": "nocobase"
}
```

#### 登录获取令牌

使用 NocoBase 用户名和密码登录以获取令牌：

```bash
curl -X POST http://localhost:8088/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123"
  }'
```

**响应示例**：

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "username": "admin"
}
```

`token` 由 NocoBase 自身签发；其格式、有效期均完全由 NocoBase 中配置的认证器（`QWENPAW_NOCOBASE_AUTHENTICATOR`，默认 `basic`）决定 —— QwenPaw 自身不签发、不存储、也不会使令牌过期。

**步骤 2：在 API 请求中使用令牌**

将返回的 `token` 添加到 `Authorization` 头部：

```bash
curl -X POST http://localhost:8088/api/console/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "X-Agent-Id: default" \
  -d '{
    "input": [
      {
        "role": "user",
        "content": [{"type": "text", "text": "你好"}]
      }
    ],
    "session_id": "my-session",
    "user_id": "my-user",
    "channel": "console"
  }'
```

#### 校验令牌

```bash
curl http://localhost:8088/api/auth/verify \
  -H "Authorization: Bearer <YOUR_TOKEN>"
```

**响应示例**：

```json
{
  "valid": true,
  "username": "admin"
}
```

如果令牌缺失、无效或已过期，会返回 `401`。

#### 令牌特性

- **签发方**：NocoBase —— 令牌格式、有效期均由 NocoBase 控制，而非 QwenPaw
- **存储**：建议安全存储，不要硬编码在代码中
- **本地免认证**：来自 `127.0.0.1` 或 `::1` 的请求默认自动跳过认证（可通过 `allow_no_auth_hosts` 配置，见[安全设置](./security#Web-登录认证)）

#### 退出登录

QwenPaw 自身不追踪或撤销令牌，因此不存在 `revoke-token` 接口。退出登录只需在客户端丢弃令牌即可（例如从本地存储中删除）。如果还想同时结束 NocoBase 侧的会话，可直接对你的 NocoBase 实例调用其自身的 `auth:signOut` 接口。

#### 关闭认证

如果你不想使用 Web 认证，可以关闭它：

**方法 1：移除环境变量**

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

**方法 2：Docker 部署**

移除 `-e QWENPAW_AUTH_ENABLED=true` 参数：

```bash
docker run -p 127.0.0.1:8088:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  -v qwenpaw-backups:/app/working.backups \
  agentscope/qwenpaw:latest
```

**重要提示**：

- 关闭认证后，所有 API 请求**无需** `Authorization` 头部
- 如果**未启用**认证，无需提供 `Authorization` 头部
- 检查认证状态：`GET /api/auth/status`

## 故障排查

### 无法连接到服务器

确认 QwenPaw 服务正在运行：

```bash
# 检查服务状态
curl http://localhost:8088/api/version
```

### 响应中断

如果流式响应中断，检查：

1. 网络连接是否稳定
2. 服务器是否正常运行
3. 模型配置是否正确

### 模型执行失败

如果看到 `MODEL_EXECUTION_FAILED` 错误：

1. 确认在 Console → Settings → Models 中正确配置了模型
2. 检查 API Key 是否有效
3. 验证模型名称是否正确
4. 查看错误详情文件（错误消息中会提供路径）

## 相关文档

- [Console 使用指南](./console)
- [安全设置](./security)
- [多智能体](./multi-agent)
- [频道配置](./channels)

## 获取帮助

如果你在使用 API 时遇到问题：

1. 查看 [FAQ](./faq) 了解常见问题
2. 加入 [社区](./community) 寻求帮助
3. 在 GitHub 上提交 [Issue](https://github.com/agentscope-ai/QwenPaw/issues)
