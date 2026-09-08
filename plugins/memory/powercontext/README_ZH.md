# PowerContext 记忆后端

[English](README.md)

PowerContext Memory 插件将 QwenPaw 连接到单独部署的
[PowerContext](https://github.com/oceanbase/powercontext) 服务，为跨会话的持久任务状态、
显式记忆和检索提供远程记忆作用域。

## 能力

- 在用户回合后保存有长度限制的当前任务状态摘要。
- 在普通用户回合开始前自动检索相关记忆。
- 向 Agent 提供受治理的 `memory_search` 和 `memory_remember` 工具。
- 在搜索结果中保留 PowerContext 的精确引用信息。
- 支持可选 Bearer Token、请求超时、结果数量和自动注入上下文的 UTF-8 总字节预算。
- 未指定作用域时，自动创建按安装和 Agent 隔离的默认作用域；也可显式设置共享作用域。

自动召回和回合后的持久化是由配置驱动的网络操作，Agent 可见工具则作为受治理的网络操作
注册。请仅使用适合目标数据的服务和作用域。

## 快速开始

### 1. 启动 PowerContext 服务

本地开发服务可通过以下命令启动：

```bash
uv tool install "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@master"
powercontext server run
```

默认本地地址为 `http://127.0.0.1:8000`。QwenPaw 不会自动安装或启动 PowerContext 服务。

### 2. 构建配置界面

在 QwenPaw 源码目录中执行：

```bash
cd plugins/memory/powercontext/frontend
npm install
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

- **服务地址**：PowerContext endpoint。
- **访问令牌**：可选的 Bearer Token。
- **记忆作用域**：留空时使用隔离的默认值
  `qwenpaw:<installation_id>:agent:<agent_id>`；只有需要共享记忆时才给多个 Agent 设置相同值。
- **请求超时**：1–60 秒。
- **自动记忆召回**：启用后设置结果数量和注入上下文字节预算。

保存配置后，Console 会安排 Agent 重载，使新的 backend 实例使用已保存设置；无需重启整个
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
升级后的首次启动中，插件会在创建自己的身份文件时继承根配置中原有的
`powercontext_installation_id`，因此 `scope_id` 留空时仍会访问原来的远程记忆。

### 5. 验证

```bash
qwenpaw plugin list
```

确认 `memory-powercontext` 已安装。让 Agent 记住一条事实，并在后续回合检索它。如果后端
未启动，请在 QwenPaw 日志中检查服务地址、Token 和服务可用性。

## 运行要求

- 可访问的 PowerContext 服务。
- QwenPaw 支持 memory backend 插件。
- `requirements.txt` 中的 Python 包；QwenPaw 插件安装器会自动安装。

## 开发

后端代码位于 `backend/`，Console 扩展位于 `frontend/`。修改前端后，重新构建并安装插件：

```bash
qwenpaw plugin install plugins/memory/powercontext --force
```
