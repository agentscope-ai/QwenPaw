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
- 远程服务不可用时保持 Agent 继续运行，但会停用远程长期记忆。

该后端会执行由配置驱动的网络读写。请仅使用适合存储目标对话数据的 ADBPG 服务地址。

## 快速开始

### 1. 构建配置界面

在 QwenPaw 源码目录中执行：

```bash
cd plugins/memory/adbpg/frontend
npm install
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

保存配置后，Console 会安排 Agent 重载，使新的 backend 实例使用已保存设置；无需重启整个
QwenPaw 进程。等价的 `agent.json` 配置为：

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

确认 `memory-adbpg` 已安装，然后让 Agent 记住一条事实，并在后续回合检索它。如果后端被
停用，请检查 QwenPaw 日志；常见原因包括 URL 或 API Key 缺失、服务不可达或鉴权失败。

## 运行要求

- ADBPG 记忆服务已运行，并提供 `/v3/memories/add/` 和 `/v3/memories/search/`。
- QwenPaw 支持 memory backend 插件。
- `requirements.txt` 中的 Python 包；QwenPaw 插件安装器会自动安装。

## 开发

后端代码位于 `backend/`，Console 扩展位于 `frontend/`。修改前端后，重新构建并安装插件：

```bash
qwenpaw plugin install plugins/memory/adbpg --force
```
