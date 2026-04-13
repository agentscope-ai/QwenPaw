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

如果启用了 [Web 登录认证](./security#Web-登录认证)（`QWENPAW_AUTH_ENABLED=true`），所有 API 请求都需要提供身份验证令牌。

#### 注册账号

**首次使用需要先注册管理员账号**（QwenPaw 采用单用户模式）：

```bash
curl -X POST http://localhost:8088/api/auth/register \
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

**注册时指定令牌有效期**：

```bash
# 注册并获取永久令牌
curl -X POST http://localhost:8088/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "expires_in": 0
  }'
```

**注意事项**：

- 注册接口只能调用一次（单用户模式）
- 注册成功后会直接返回登录令牌
- 如果已有用户，会返回 `{"detail":"User already registered"}` 错误
- 支持通过 `expires_in` 参数自定义令牌有效期（同登录接口）

**如果需要重新注册**（例如忘记密码或想更换账号）：

方法 1：使用 CLI 重置密码

```bash
qwenpaw auth reset-password
```

方法 2：删除认证文件后重新注册

```bash
# 删除认证文件
rm ~/.qwenpaw.secret/auth.json

# 或者如果使用自定义工作目录
rm $WORKING_DIR.secret/auth.json

# 重启 QwenPaw 后重新注册
qwenpaw app
```

**Docker 部署**：

```bash
# 进入容器删除认证文件
docker exec -it <容器名> rm /app/working.secret/auth.json

# 或者使用 CLI 重置密码
docker exec -it <容器名> qwenpaw auth reset-password
```

**自动注册**（可选）：

你也可以在启动 QwenPaw 时通过环境变量自动创建账号：

```bash
export QWENPAW_AUTH_ENABLED=true
export QWENPAW_AUTH_USERNAME=admin
export QWENPAW_AUTH_PASSWORD=admin123
qwenpaw app
```

这样就无需手动调用注册 API。

#### 获取认证令牌

**注册后，使用登录 API 获取令牌**

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

**自定义令牌有效期**：

你可以通过 `expires_in` 参数指定令牌的有效时长（单位：秒）：

```bash
# 申请 30 天有效期的令牌
curl -X POST http://localhost:8088/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "expires_in": 2592000
  }'

# 申请永久令牌（100 年有效期）
curl -X POST http://localhost:8088/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "admin123",
    "expires_in": 0
  }'
```

**常用有效期**：

- `604800` = 7 天（默认）
- `2592000` = 30 天
- `31536000` = 1 年
- `0` 或 `-1` = 永久令牌（100 年）

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

#### 令牌特性

- **有效期**：
  - 默认：7 天
  - 可通过 `expires_in` 参数自定义（支持永久令牌）
  - 最长：100 年
- **格式**：HMAC-SHA256 签名令牌
- **存储**：建议安全存储，不要硬编码在代码中
- **本地免认证**：来自 `127.0.0.1` 或 `::1` 的请求自动跳过认证
- **多令牌共存**：
  - ⚠️ 每次登录都会创建新令牌，旧令牌不会自动失效
  - 只要令牌未过期且签名有效，多个令牌可以同时使用
  - 这意味着如果令牌泄露，需要手动撤销

#### 撤销令牌

如果你想使令牌失效（例如令牌泄露、注销登录或安全事件），有以下方法：

**方法 1：撤销单个令牌**（推荐用于注销或撤销特定设备）

```bash
# 撤销当前令牌（注销当前会话）
curl -X POST http://localhost:8088/api/auth/revoke-token \
  -H "Authorization: Bearer <YOUR_CURRENT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'

# 撤销指定令牌（例如泄露的令牌）
curl -X POST http://localhost:8088/api/auth/revoke-token \
  -H "Authorization: Bearer <YOUR_CURRENT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "token": "eyJhbGciOi..."
  }'
```

**响应示例**：

```json
{
  "message": "Current token has been revoked. Please login again.",
  "revoked": true,
  "revoked_current_token": true
}
```

**方法 2：撤销所有令牌**（用于安全事件或密码重置）

```bash
curl -X POST http://localhost:8088/api/auth/revoke-all-tokens \
  -H "Authorization: Bearer <YOUR_CURRENT_TOKEN>"
```

**响应示例**：

```json
{
  "message": "All tokens have been revoked. Please login again.",
  "revoked": true
}
```

**方法 3：修改密码**（同时撤销所有令牌）

修改密码时会自动轮换 JWT 密钥，使所有旧令牌失效：

```bash
curl -X POST http://localhost:8088/api/auth/update-profile \
  -H "Authorization: Bearer <YOUR_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "current_password": "old_password",
    "new_password": "new_password"
  }'
```

**撤销方法对比**：

| 方法         | 作用范围 | 优点                     | 缺点               | 使用场景               |
| ------------ | -------- | ------------------------ | ------------------ | ---------------------- |
| 撤销单个令牌 | 单个     | 精确控制，不影响其他设备 | 需要知道令牌内容   | 注销登录、撤销特定设备 |
| 撤销所有令牌 | 全部     | 一次性失效所有会话       | 所有设备需重新登录 | 安全事件、密码泄露     |
| 修改密码     | 全部     | 同时更新密码和撤销令牌   | 需要记住旧密码     | 定期密码更新           |
| 删除认证文件 | 全部     | 彻底清除（包括密码）     | 需要服务器访问权限 | 完全重置系统           |

**注意事项**：

- 撤销后，所有客户端都需要重新登录获取新令牌
- 撤销操作不可逆
- 建议在令牌泄露或设备丢失时立即撤销
- 如果使用永久令牌（`expires_in: 0`），强烈建议定期手动撤销并重新申请

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
