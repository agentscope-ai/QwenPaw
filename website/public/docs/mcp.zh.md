# MCP

**MCP（模型上下文协议，Model Context Protocol）** 允许 RyPaw 连接到外部 MCP 服务器并使用它们的工具。你可以通过控制台添加 MCP 客户端来扩展 RyPaw 的能力。

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

RyPaw 支持三种 JSON 格式导入 MCP 客户端：

### 格式 1：标准 mcpServers 格式（推荐）

```json
{
  "mcpServers": {
    "client-name": {
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
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem"],
  "env": {
    "API_KEY": "your-api-key-here"
  }
}
```

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

---

## 管理 MCP 客户端

导入后，你可以：

- **查看所有客户端** — 在 MCP 页面以卡片形式查看所有 MCP 客户端
- **启用 / 禁用** — 快速开关客户端，无需删除
- **编辑配置** — 点击卡片查看和编辑 JSON 配置
- **删除客户端** — 删除不再需要的 MCP 客户端
