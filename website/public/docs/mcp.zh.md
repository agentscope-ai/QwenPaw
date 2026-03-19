# MCP

**MCP（模型上下文协议，Model Context Protocol）** 允许 CoPaw 连接到外部 MCP 服务器并使用它们的工具。你可以通过控制台添加 MCP 客户端来扩展 CoPaw 的能力。

---

## 前置要求

如果使用 `npx` 运行 MCP 服务器，请确保已安装：

- **Node.js** 18 或更高版本（[下载地址](https://nodejs.org/)）

检查 Node.js 版本：

```bash
node --version
```

---

## 在控制台中添加 MCP 客户端

1. 打开控制台，进入 **智能体 → MCP**
2. 点击 **+ 创建** 按钮
3. 粘贴 MCP 客户端的 JSON 配置
4. 点击 **创建** 完成导入

---

## 配置格式

CoPaw 支持三种 JSON 格式导入 MCP 客户端：

### 格式 1：标准 mcpServers 格式（推荐）

```json
{
  "mcpServers": {
    "client-name": {
      "name": "My MCP Client",
      "description": "Optional client description",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem"],
      "env": {
        "API_KEY": "your-api-key-here"
      }
    }
  }
}
```

### 格式 2：直接键值对格式

```json
{
  "client-name": {
    "description": "Optional client description",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem"],
    "env": {
      "API_KEY": "your-api-key-here"
    }
  }
}
```

### 格式 3：单个客户端格式

```json
{
  "key": "client-name",
  "name": "My MCP Client",
  "description": "Optional client description",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {
    "API_KEY": "your-api-key-here"
  }
}
```

### 常用字段说明（含 description）

- `name`：显示名称（可选，不填时通常使用 key）
- `description`：描述信息（可选，建议填写，便于识别用途）
- `enabled`：是否启用（可选，默认 `true`）
- `transport`：传输类型（可选，支持 `stdio` / `streamable_http` / `sse`）
- `command`、`args`、`env`、`cwd`：本地命令类 MCP 常用字段
- `url`、`headers`：远程 MCP 常用字段

传输类型校验规则：

- `transport=stdio`：必须提供非空 `command`
- `transport=streamable_http` 或 `sse`：必须提供非空 `url`
- 若省略 `transport`：有 `url` 时默认按 `streamable_http` 处理；否则默认按 `stdio` 处理

---

## 示例：文件系统 MCP 服务器

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/username/Documents"
      ]
    }
  }
}
```

> 将 `/Users/username/Documents` 替换为你希望智能体访问的目录路径。

远程 MCP 示例（含 `description`）：

```json
{
  "mcpServers": {
    "example_mcp": {
      "name": "Example Mcp Server",
      "description": "Remote MCP endpoint over HTTP",
      "transport": "streamable_http",
      "url": "http://127.0.0.1:8585/mcp",
      "headers": {
        "Authorization": "Bearer <YOUR_TOKEN>"
      }
    }
  }
}
```

---

## 管理 MCP 客户端

导入后，你可以：

- **查看所有客户端** — 在 MCP 页面以卡片形式查看所有 MCP 客户端
- **启用 / 禁用** — 快速开关客户端，无需删除
- **编辑配置** — 点击卡片查看和编辑 JSON 配置
- **删除客户端** — 删除不再需要的 MCP 客户端
