# PowerContext 记忆后端

[English](README.md)

PowerContext Memory 插件将 QwenPaw 连接到单独部署的
[PowerContext](https://github.com/oceanbase/powercontext) 服务，通过远程 Scope 提供跨会话的
上下文组装、持久任务状态、显式记忆和 Artifact 访问。

## 能力

- 在普通用户回合开始前组装上下文，默认按画像（1 条）、主题记忆（2 条）、记忆（3 条）、
  经验（2 条）的顺序排列。
- 通过 QwenPaw 的自动记忆流程保存有长度限制的任务状态快照。
- 向 Agent 提供 `prepare_context`、2 个记忆工具和 7 个 Artifact 工具，
  均作为受治理的网络操作注册。
- 保留精确的 Artifact 引用和状态版本；显式选择旧版记忆模式时，也兼容 PowerContext
  v0.2 返回的引用格式。
- 支持可选 Bearer Token、请求超时和自动注入上下文的 UTF-8 总字节预算。
- 未指定作用域时，自动创建或复用按安装和 Agent 隔离的默认作用域；需要共享记忆时，
  可显式填写已有作用域的 ID。

自动召回和回合后的持久化是由配置驱动的网络操作。请使用适合目标数据的服务和作用域。

### 自动上下文

`auto_memory_search_config.mode` 默认为 `prepare`。插件将用户查询发送给 PowerContext
的上下文组装接口：去除首尾空白后，保留最多 8,192 个字符。返回的 Markdown 内容保持原样，
不重新排版或截断。`max_context_bytes` 按 UTF-8 字节数限制完整的注入消息，包含外层提示
和标记；超过预算时不注入该响应。

`context_assembly.sections` 决定包含哪些类型及其顺序。每种类型只能出现一次，每个区块
允许 1–8 条，经验区块允许 1–2 条。空列表表示不请求上下文。服务端默认要求各区块条数上限
之和不超过 8，也可配置其他总上限，最终由服务端校验。插件仅校验各类型的范围，不把服务端
默认总上限写死。`show` 可选 `recall_rank` 和 `confidence`，每项最多出现一次。输出格式
为 `markdown`。

使用 PowerContext v0.2 时，需要显式设置 `auto_memory_search_config.mode` 为 `memory`，
或在 Console 中选择“旧版记忆搜索”。该模式使用 `max_results`，范围为 1–50；Prepare
模式使用 `context_assembly` 中的条数设置。Prepare 请求失败时不会静默切换到记忆搜索。
旧版模式也不会让旧服务获得其本身不支持的 Artifact 或 Prepare 接口。

### Agent 工具

| 工具               | 用途                                                            |
| ------------------ | --------------------------------------------------------------- |
| `prepare_context`  | 使用配置中的上下文区块和 Scope，为查询组装上下文。              |
| `memory_search`    | 在配置的 Scope 中搜索记忆。                                     |
| `memory_remember`  | 保存显式记忆。                                                  |
| `artifact_schema`  | 从所连接服务的 `/openapi.json` 获取 Artifact 内容 schema。      |
| `artifact_search`  | 搜索 `atomic-memory`、`experience`、`skill` 和 `topic-memory`。 |
| `artifact_list`    | 按类型列出 Artifact。                                           |
| `artifact_get`     | 读取 Artifact 及其当前 ETag。                                   |
| `artifact_history` | 读取 Artifact 的修订历史。                                      |
| `artifact_create`  | 按所选类型的内容 schema 正式创建 Artifact。                     |
| `artifact_replace` | 使用读取时取得的 ETag 替换内容。                                |

`prepare_context(query, max_bytes=8000)` 供 Agent 显式请求上下文。它使用插件配置中的
`context_assembly` 和已绑定的 Scope；Agent 只需提供查询和响应字节预算。

Artifact 的列举、读取、历史、创建和替换支持 `atomic-memory`、`experience`、`skill`、
`topic-memory`、`profile`、`handoff` 和 `prompt`，具体约束和权限由所连接的服务决定。
写入前先调用 `artifact_schema`，按该服务实际返回的内容字段构造请求。
`artifact_create` 会直接正式写入，包括 Experience 和 Skill，不会先创建等待审批的
Candidate。`artifact_replace` 必须使用读取时取得的 ETag，版本冲突时不会自动重试；
需要重新读取并核对内容后再提交。把读取结果中的 `etag` 传给替换工具的
`expected_etag` 参数。

插件继续使用 QwenPaw 现有的自动任务状态持久化流程。本插件不提供 Source 采集、特殊
生命周期操作、Candidate 审批、Skill 分发或 Handoff 激活与接续。通用 Handoff 内容访问
不会执行这些生命周期操作。

## 快速开始

### 1. 启动 PowerContext 服务

以下命令安装固定的 PowerContext v1.4.1 正式版，并启动新的本地服务：

```bash
uv tool install "powercontext[cli,server]==1.4.1"
POWERCONTEXT_HOME="$HOME/.powercontext-qwenpaw-1.4.1" powercontext server run
```

默认本地地址为 `http://127.0.0.1:8000`。QwenPaw 不会自动安装或启动 PowerContext 服务。

PowerContext v1.4.1 仅支持新数据库：其
[发布说明](https://github.com/oceanbase/powercontext/releases/tag/powercontext-v1.4.1)
明确指出本次跳过了升级验收，不支持现有数据库升级。请使用独立的 `POWERCONTEXT_HOME`
创建新数据库，不要让此版本连接现有服务的数据库。

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
- **自动上下文**：选择“组装上下文（Prepare）”，编辑各类型的条数和顺序，并设置注入
  上下文字节预算。连接 v0.2 服务时，选择“旧版记忆搜索”并设置结果条数。

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
          "mode": "prepare",
          "max_results": 3,
          "max_context_bytes": 12000
        },
        "context_assembly": {
          "format": "markdown",
          "sections": [
            { "family": "profile", "limit": 1 },
            { "family": "topic-memory", "limit": 2 },
            { "family": "memory", "limit": 3 },
            { "family": "experience", "limit": 2 }
          ],
          "show": []
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

启动时绑定作用域若遇到网络故障或 HTTP 5xx，同一个管理器会在后台重试，等待间隔从
1 秒指数递增，最长 30 秒。绑定成功前，记忆工具、自动召回和自动写入均不可用。
鉴权、配置和无效作用域错误会明确报告，不会自动重试；请修正配置后重新加载 Agent。
关闭管理器会取消待执行的重试。恢复后，从后续回合开始正常工作，不会补写故障期间跳过的回合。

创建默认作用域和重放创建请求都需要 `server.admin` 权限。读取显式作用域需要
`scope.read`，写入记忆需要 `scope.contribute`。部分 Artifact 类型的写入需要额外权限。
使用受限 Token 时，请由管理员创建作用域并授予所需权限，再显式配置 Scope ID。

### 5. 验证

```bash
qwenpaw plugin list
```

确认 `memory-powercontext` 已安装。让 Agent 记住一条事实，并在后续回合检索它。如果后端
未启动，请在 QwenPaw 日志中检查服务地址、Token 和服务可用性。

## 运行要求

- 可访问的 PowerContext 服务；使用新数据库时，推荐 v1.4.1 正式版。
- QwenPaw 支持 memory backend 插件。
- `requirements.txt` 中的 Python 包；QwenPaw 插件安装器会自动安装。

## 开发

后端代码位于 `backend/`，Console 扩展位于 `frontend/`。修改前端后，重新构建并安装插件：

```bash
qwenpaw plugin install plugins/memory/powercontext --force
```

已使用正式发布的 [PowerContext v1.4.1 包](https://pypi.org/project/powercontext/1.4.1/)，
在全新、隔离的 SQLite 数据库上通过全部 13 项真实 HTTP 测试，测试服务关闭认证且未配置
推理模型。249 项非集成插件测试和 6 项宿主 memory-backend 契约测试也全部通过。
该结果验证适配器与新建服务数据库的兼容性，不代表现有数据库迁移通过验收。

旧版
[v0.2（`685b31dd`）](https://github.com/oceanbase/powercontext/commit/685b31dd2961df5e31daa565f87d004755ebd2cf)
使用 `mode="memory"`，4 项旧版记忆测试通过。

当前服务版本的测试覆盖默认作用域创建与复用、显式作用域、记忆持久化与召回、七种 Artifact
的创建/读取/列举/历史/替换、四种类型的搜索投影、作用域隔离、ETag 冲突，以及四类上下文
组装结果的逐字节保留。这些测试通过真实 HTTP 和 SQLite 运行插件后端，不包含完整的
Console 模型会话，也不包含 Candidate 审批、Skill 分发或 Handoff 生命周期操作。

运行 `pytest plugins/memory/powercontext/tests` 时，未设置 `POWERCONTEXT_TEST_URL`
会跳过真实 HTTP 测试。要运行这些测试，请先启动独立、可丢弃且未启用认证的测试服务，再执行：

```bash
POWERCONTEXT_TEST_URL=http://127.0.0.1:8000 pytest \
  plugins/memory/powercontext/tests/test_server_integration.py \
  plugins/memory/powercontext/tests/test_context_artifacts_integration.py
```

v0.2 测试服务仅运行旧版记忆测试：

```bash
POWERCONTEXT_TEST_URL=http://127.0.0.1:8000 \
POWERCONTEXT_TEST_RECALL_MODE=memory pytest \
  plugins/memory/powercontext/tests/test_server_integration.py
```

测试会创建持久化的作用域和 Artifact，请使用专用测试数据库，并在测试后丢弃。
