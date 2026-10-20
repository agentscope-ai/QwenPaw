# PowerContext 记忆后端

[English](README.md)

PowerContext Memory 插件将 QwenPaw 连接到单独部署的
[PowerContext](https://github.com/oceanbase/powercontext) 服务，为跨会话的持久任务状态、
显式记忆和检索提供远程记忆作用域。

## 能力

- 通过 QwenPaw 的自动记忆流程保存有长度限制的任务状态快照。
- 在普通用户回合开始前自动检索相关记忆。
- 向 Agent 提供受治理的 `memory_search` 和 `memory_remember` 工具。
- 支持当前 Atomic Memory 搜索结果，保留精确的 Artifact 引用和状态版本；同时兼容
  v0.2 搜索结果中的旧引用格式。
- 支持可选 Bearer Token、请求超时、结果数量和自动注入上下文的 UTF-8 总字节预算。
- 未指定作用域时，自动创建或复用按安装和 Agent 隔离的默认作用域；需要共享记忆时，
  可显式填写已有作用域的 ID。

自动召回和回合后的持久化是由配置驱动的网络操作，Agent 可见工具则作为受治理的网络操作
注册。请仅使用适合目标数据的服务和作用域。

## 快速开始

### 1. 启动 PowerContext 服务

以下命令安装固定的 PowerContext v1.4.0 正式版，并启动本地服务：

```bash
uv tool install "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@powercontext-v1.4.0"
powercontext server run
```

默认本地地址为 `http://127.0.0.1:8000`。QwenPaw 不会自动安装或启动 PowerContext 服务。

### 2. 构建配置界面

在 QwenPaw 源码目录中执行：

```bash
cd plugins/memory/powercontext/frontend
npm ci
npm run build
cd ../../../../
```

### 3. 安装插件

```bash
qwenpaw plugin install plugins/memory/powercontext
```

如果 QwenPaw 已停止，安装后重新启动；如果正在运行，CLI 会使用热安装 API。重新安装已有
插件时添加 `--force`。

### 4. 配置 Agent

在 Console 中打开 Agent 运行配置，选择 **PowerContext**，并设置：

- **服务地址**：PowerContext 服务地址。
- **访问令牌**：可选的 Bearer Token。
- **记忆作用域**：留空时自动创建或复用当前 Agent 的默认作用域，也可填写 Token 有权访问的
  已有 Scope ID。只有需要共享记忆时，才给多个 Agent 填写相同的 ID。
- **请求超时**：1–60 秒。
- **自动记忆召回**：启用后设置结果数量和注入上下文字节预算。

保存配置后，Console 会安排 Agent 重载，使新的后端实例使用已保存设置；无需重启整个
QwenPaw 进程。等价的 `agent.json` 配置为：

```json
{
  "running": {
    "memory_manager_backend": "powercontext",
    "memory_backend_configs": {
      "powercontext": {
        "base_url": "http://127.0.0.1:8000",
        "token": "",
        "scope_id": "",
        "timeout": 10.0,
        "auto_memory_search_config": {
          "enabled": true,
          "max_results": 3,
          "max_context_bytes": 12000
        }
      }
    }
  }
}
```

配置必须放在 `memory_backend_configs.powercontext`；原先由核心定义的
`powercontext_memory_config` 字段已不再支持。
升级后的首次启动中，插件会把根配置中原有的 `powercontext_installation_id` 继承到
QwenPaw 规范工作目录下的 `plugin-state/memory-powercontext/installation-id`。即使 Agent
使用自定义工作区路径，安装身份也保持不变。

`scope_id` 留空时，插件先查找已注册的历史作用域
`qwenpaw:<installation_id>:agent:<agent_id>`，存在时继续使用。否则，插件以固定幂等键调用
`POST /v1/scopes`，使用服务端返回的 `scp_...` Scope ID。幂等键按安装和 Agent 区分，
使用相同身份重启时会复用同一个作用域。复制 QwenPaw 工作目录也会复制安装身份，因此副本中
相同 Agent ID 会共享默认作用域。

显式填写的 `scope_id` 必须已在 PowerContext 中创建，且 Token 有权访问。插件只绑定这个
作用域；访问失败时，不会替换它或另建作用域。

创建默认作用域和重放创建请求都需要 `server.admin` 权限。读取显式作用域需要
`scope.read`，写入记忆需要 `scope.contribute`。使用受限 Token 时，请由管理员创建作用域并
授予所需权限，再显式配置 Scope ID。

### 5. 验证

```bash
qwenpaw plugin list
```

确认 `memory-powercontext` 已安装。让 Agent 记住一条事实，并在后续回合检索它。如果后端
未启动，请在 QwenPaw 日志中检查服务地址、Token 和服务可用性。

## 运行要求

- 可访问的 PowerContext 服务，推荐使用 v1.4.0 正式版。
- QwenPaw 支持 memory backend 插件。
- `requirements.txt` 中的 Python 包；QwenPaw 插件安装器会自动安装。

## 开发

后端代码位于 `backend/`，Console 扩展位于 `frontend/`。修改前端后，重新构建并安装插件：

```bash
qwenpaw plugin install plugins/memory/powercontext --force
```

已分别使用独立 SQLite 数据库，通过真实 HTTP 在 PowerContext
[v1.4.0（`cab054db`）](https://github.com/oceanbase/powercontext/commit/cab054dbf6d86e2311b079388e5158178257def2)、
[master（`fe50f894`）](https://github.com/oceanbase/powercontext/commit/fe50f89406153121883d278c7fe89ea272cd894b)
和旧版 [v0.2（`685b31dd`）](https://github.com/oceanbase/powercontext/commit/685b31dd2961df5e31daa565f87d004755ebd2cf)
上完成验证，每个版本 4 项测试全部通过。覆盖默认作用域创建与复用、显式作用域、手动及排队
写入、带精确引用的搜索、后端重启后召回，以及 Agent 和安装之间的隔离。这些测试直接运行
插件后端，未包含 QwenPaw 中的真实模型会话。

运行 `pytest plugins/memory/powercontext/tests` 时，未设置 `POWERCONTEXT_TEST_URL`
会跳过真实 HTTP 测试。要运行这些测试，请先启动独立、可丢弃且未启用认证的测试服务，再执行：

```bash
POWERCONTEXT_TEST_URL=http://127.0.0.1:8000 pytest plugins/memory/powercontext/tests/test_server_integration.py
```

测试会创建持久化的作用域和记忆，请使用专用测试数据库，并在测试后丢弃。
