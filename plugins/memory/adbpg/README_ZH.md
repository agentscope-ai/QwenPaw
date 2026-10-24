# ADBPG 记忆后端

[English](README.md)

ADBPG Memory 插件通过 REST API 将 QwenPaw 连接到 AnalyticDB for PostgreSQL
记忆服务。它适用于需要持久化集中管理、跨设备访问，或需要突破单一本地 workspace 规模进行
语义检索的场景。

## 能力

- 将用户消息写入 ADBPG 记忆服务，由服务端完成事实抽取和存储。
- 对远程记忆执行语义检索，并与 Agent 本地 `MEMORY.md`、`memory/*.md` 文件的关键词匹配结果合并。
- 在普通用户回合开始前自动召回相关记忆。
- 默认按 Agent 隔离远程记忆，也可以显式启用共享模式。
- 远程请求失败时 Agent 继续运行；远程搜索失败后仍可检索本地 Markdown 文件。

该后端会执行由配置驱动的网络读写。请仅使用适合存储目标对话数据的 ADBPG 服务地址。

## 快速开始

### 1. 构建配置界面

在 QwenPaw 源码目录中执行：

```bash
cd plugins/memory/adbpg/frontend
npm ci
npm run build
cd ../../../../
```

### 2. 安装插件

```bash
qwenpaw plugin install plugins/memory/adbpg
```

如果 QwenPaw 已停止，安装后重新启动；如果正在运行，CLI 会使用热安装 API。重新安装已有
插件时添加 `--force`。

### 3. 配置 Agent

在 Console 中打开 Agent 运行配置，选择 **ADBPG** 作为长期记忆后端，并设置：

- **REST Base URL**：ADBPG 记忆服务的基础地址。
- **REST API Key**：以 `Authorization: Token <key>` 形式发送的访问密钥。
- **按 Agent 隔离**：除非多个 Agent 应共享远程身份，否则保持启用。
- **搜索超时**：远程搜索的超时秒数。
- **自动记忆召回**：如需在普通用户回合前注入记忆，启用并设置最大结果数。

保存配置后，Console 会安排 Agent 重载。backend 或有效配置发生变化时会创建新实例；
backend 上下文未变化时可以复用原实例。无需重启整个 QwenPaw 进程。等价的 `agent.json`
配置为：

```json
{
  "running": {
    "memory_manager_backend": "adbpg",
    "memory_backend_configs": {
      "adbpg": {
        "rest_base_url": "https://your-adbpg-memory-api.example.com",
        "rest_api_key": "your-rest-api-key",
        "memory_isolation": true,
        "search_timeout": 10.0,
        "auto_memory_search_config": {
          "enabled": true,
          "max_results": 3
        }
      }
    }
  }
}
```

配置必须放在 `memory_backend_configs.adbpg`；原先由核心定义的
`adbpg_memory_config` 字段已不再支持。

### 4. 验证

```bash
qwenpaw plugin list
```

确认 `memory-adbpg` 已安装，然后让 Agent 记住一条事实。等待服务端抽取完成后，再在后续
回合检索。可通过 `/auto_memory_status` 和 QwenPaw 日志检查提交失败。

## 远程身份

| 配置                      | `agent_id`    | `user_id` | 写入时的 `run_id` |
| ------------------------- | ------------- | --------- | ----------------- |
| `memory_isolation: true`  | 当前 Agent ID | `shared`  | `shared`          |
| `memory_isolation: false` | `shared`      | `shared`  | `shared`          |

搜索只按 `agent_id` 和 `user_id` 过滤，不限制 `run_id`，因此可以跨会话召回。这里的隔离
粒度是 Agent，不是聊天用户或会话；同一服务数据集内启用共享模式的 Agent 会使用同一远程
命名空间。切换隔离开关会改变读写命名空间，不会迁移已有记忆。本地 Markdown 文件始终
属于各 Agent 自己的工作区。

## 运行要求

- ADBPG 记忆服务已运行，并提供 `/v3/memories/add/` 和 `/v3/memories/search/`。
- QwenPaw 支持 memory backend 插件。
- `requirements.txt` 中的 Python 包；QwenPaw 插件安装器会自动安装。

## 开发

后端代码位于 `backend/`，Console 扩展位于 `frontend/`。修改前端后，重新构建并安装插件：

```bash
qwenpaw plugin install plugins/memory/adbpg --force
```
