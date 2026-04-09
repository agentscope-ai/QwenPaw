# NapCat Channel for CoPaw

此 Channel 使用 NapCat (OneBot 11 协议) 连接 QQ，实现消息收发功能。

## 功能特性

- **消息收发**: 支持群聊和私聊消息的接收与发送
- **WebSocket 实时消息**: 通过 WebSocket 实时接收消息
- **HTTP API 发送**: 通过 HTTP API 发送消息
- **消息过滤**: 支持过滤工具消息和思考过程
- **灵活的权限控制**: 支持白名单、消息前缀过滤、DM/群策略控制
- **MCP 集成**: 支持配置 MCP 客户端扩展功能

## 使用前提

1. **安装并运行 NapCat**
   - 参考 [NapCat 官方文档](https://napcatnapcat.github.io/NapCatDocs/) 安装
   - 需要配置 WebSocket 连接用于接收消息

2. **配置 NapCat 端**

   确保 NapCat 的 `config/onebot11.json` 中已启用 WebSocket：

   ```json
   {
     "httpPort": 3000,
     "httpHosts": ["0.0.0.0"],
     "wsPort": 3001,
     "wsHosts": ["0.0.0.0"],
     "enableHttp": true,
     "enableWs": true,
     "accessToken": ""
   }
   ```

3. **配置 config.json**

   在 `~/.copaw/config.json` 的 `channels` 中添加：

```json
{
  "napcat": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 3000,
    "ws_port": 3001,
    "access_token": "",
    "bot_prefix": "",
    "filter_tool_messages": false,
    "filter_thinking": false,
    "dm_policy": "open",
    "group_policy": "open",
    "allow_from": [],
    "deny_message": ""
  }
}
```

---

## 配置项说明

| 配置项 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| enabled | 是 | false | 是否启用此 Channel |
| host | 是 | 127.0.0.1 | NapCat 服务器地址 |
| port | 是 | 3000 | NapCat HTTP API 端口 |
| ws_port | 是 | 3001 | NapCat WebSocket 端口 |
| access_token | 否 | - | 访问令牌（如果 NapCat 配置了认证） |
| bot_prefix | 否 | - | 消息前缀，只有带此前缀的消息才会被处理 |
| filter_tool_messages | 否 | false | 是否过滤工具消息 |
| filter_thinking | 否 | false | 是否过滤思考过程 |
| dm_policy | 否 | open | 私聊策略：open/deny |
| group_policy | 否 | open | 群消息策略：open/deny |
| allow_from | 否 | [] | 允许的发送者列表（QQ 号） |
| deny_message | 否 | - | 拒绝时的提示消息 |

---

## 快速开始

### 1. 安装 NapCat

参考 [NapCat 官方文档](https://napcatnapcat.github.io/NapCatDocs/) 下载并安装 NapCat。

### 2. 配置 NapCat

编辑 NapCat 的 `config/onebot11.json`，确保启用 HTTP 和 WebSocket：

```json
{
  "httpPort": 3000,
  "httpHosts": ["0.0.0.0"],
  "wsPort": 3001,
  "wsHosts": ["0.0.0.0"],
  "enableHttp": true,
  "enableWs": true,
  "accessToken": ""
}
```

### 3. 启动 NapCat

```bash
# 运行 NapCat
./NapCat.sh
# 或 Windows
NapCat.exe
```

### 4. 启动 CoPaw

确保 config.json 中 NapCat channel 已启用，然后启动 CoPaw。

### 5. 使用方式

- **私聊**: 直接发送消息给机器人
- **群聊**: 在群中 @机器人 或使用配置的前缀

---

## MCP 配置（可选）

你可以通过配置 MCP 客户端来扩展 NapCat Channel 的功能。以下是几种常用的 MCP 配置示例：

### 方式一：通过 CoPaw 控制台添加（推荐）

1. 打开 CoPaw 控制台，进入 **智能体 → MCP**
2. 点击 **+ 创建** 按钮
3. 粘贴 MCP 客户端的 JSON 配置
4. 点击 **创建** 完成导入

### 方式二：手动编辑 config.json

在 `~/.copaw/config.json` 的 `mcp` 节点添加：

#### 示例 1: NapCat MCP 工具服务器

```json
{
  "mcp": {
    "clients": {
      "napcat_mcp": {
        "name": "napcat_mcp",
        "description": "NapCat MCP 工具服务",
        "enabled": true,
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@some/mcp-server"],
        "env": {}
      }
    }
  }
}
```

#### 示例 2: 带认证的 HTTP MCP 服务

```json
{
  "mcp": {
    "clients": {
      "my_mcp": {
        "name": "my_mcp",
        "description": "我的 MCP 服务",
        "enabled": true,
        "transport": "streamable_http",
        "url": "http://localhost:8080/mcp",
        "headers": {
          "Authorization": "Bearer your-token-here"
        }
      }
    }
  }
}
```

#### 示例 3: 标准 mcpServers 格式

```json
{
  "mcp": {
    "clients": {
      "filesystem": {
        "name": "filesystem",
        "description": "文件系统访问",
        "enabled": true,
        "transport": "stdio",
        "command": "npx",
        "args": [
          "-y",
          "@modelcontextprotocol/server-filesystem",
          "/Users/username/Documents"
        ]
      }
    }
  }
}
```

---

## 高级配置

### 使用消息前缀过滤

只有带特定前缀的消息才会被处理：

```json
{
  "napcat": {
    "enabled": true,
    "bot_prefix": "/",
    "host": "127.0.0.1",
    "port": 3000,
    "ws_port": 3001
  }
}
```

此时，用户需要发送 `/hello` 这样的消息才会被处理。

### 白名单用户

只允许特定用户使用：

```json
{
  "napcat": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 3000,
    "ws_port": 3001,
    "allow_from": ["123456789", "987654321"],
    "deny_message": "抱歉，你没有使用权限"
  }
}
```

### 过滤工具消息

过滤 CoPaw 内部的工具调用消息：

```json
{
  "napcat": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 3000,
    "ws_port": 3001,
    "filter_tool_messages": true,
    "filter_thinking": true
  }
}
```

---

## 故障排除

### 1. 连接失败

确保：
- NapCat 已启动并运行
- 端口 3000 和 3001 未被占用
- 防火墙允许这些端口

### 2. 消息发送失败

检查：
- 机器人是否有发送消息的权限
- 群号/QQ号是否正确
- access_token 是否匹配

### 3. 110 错误

如果收到 "Error 110: 被移出群" 相关的错误：
- 检查 NapCat 日志
- 确保机器人仍在群中
- 验证 group_id 配置正确

### 4. 查看日志

CoPaw 会输出详细日志，关注以下关键词：
- `NapCat connected` - WebSocket 连接成功
- `NapCat send` - 发送消息
- `NapCat receive` - 接收消息
- `NapCat error` - 错误信息

---

## 注意事项

- 确保 NapCat 已经启动并正常运行
- WebSocket 用于接收消息，HTTP API 用于发送消息
- 如果 NapCat 配置了 access_token，需要在配置中填写
- 群聊和私聊使用不同的 session_id 格式进行区分

