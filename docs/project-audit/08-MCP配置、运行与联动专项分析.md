# MCP 配置、运行与联动专项分析

## 1. 结论

原项目的 MCP 不是一个孤立的“服务器列表”页面，而是横跨 Agent 配置、凭据管理、运行时工具发现、对话工具调用、权限审批、斜杠命令、ACP 会话、备份恢复和 Agent 复制的完整子系统。

当前有效主链路已经从旧版 `agent.json.mcp.clients` 迁移为：

```text
Agent workspace
├─ drivers/mcp/<client>.yaml      MCP DriverCard、工具白名单和访问策略
├─ credentials.yaml              加密后的环境变量、请求头和 OAuth 凭据
└─ agent.json                     仅保留旧配置迁移兼容入口，不再是 MCP 主存储
```

控制台 MCP 页面和主要运行时已经使用新的 Driver 架构，但斜杠命令目录和旧 Runner 仍保留 `mcp_manager`/旧 `agent_config.mcp` 引用，形成确定的新旧架构断层。多用户改造不能只给 MCP 页面加角色判断，必须统一对象归属、配置版本、密钥边界、调用授权、真实用户审批和审计链路。

根据已经确认的目标边界：

- 私有 Agent 的所有者可以配置 MCP；协作者可以配置其有编辑权的 Agent；仅有使用权的用户不能配置。
- 共享应用的 MCP、外部工具和第三方密钥由所有者/协作者在草稿中配置，由管理员在发布时审核。
- 普通使用者只能间接调用已发布、已批准的能力，不能查看、编辑或导出密钥。
- 对外部系统产生真实副作用的调用，仍必须由实际发起操作的用户确认并形成审计记录。

## 2. MCP 页面原有功能

### 2.1 页面范围与入口

MCP 页面位于 Agent 管理范围内，而不是部署级全局设置。当前页面随侧边栏选中的 Agent 重新加载，前端通过 `X-Agent-Id` 或 Agent 路由把请求定向到对应 workspace。

页面显示受运行能力控制，区分：

- QwenPaw 原生 MCP 管理能力。
- 兼容投影能力。
- Harness/Provider 自有 MCP 发现能力。

Harness/Provider MCP 只读展示，不归 QwenPaw MCP CRUD 管理，不能与 Agent 自己配置的 MCP 客户端混为同一对象。

主要前端源码：

- `console/src/pages/Agent/MCP/index.tsx`
- `console/src/pages/Agent/MCP/useMCP.ts`
- `console/src/pages/Agent/MCP/components/MCPClientCard.tsx`
- `console/src/pages/Agent/MCP/components/MCPAccessModal.tsx`
- `console/src/pages/Agent/MCP/components/MCPAccessClientPanel.tsx`
- `console/src/pages/Agent/MCP/components/MCPAccessToolPanel.tsx`
- `console/src/pages/Agent/MCP/components/MCPOAuthSection.tsx`
- `console/src/api/modules/mcp.ts`
- `console/src/types/mcp.ts`

### 2.2 客户端配置

页面支持列表、创建、编辑、启停和删除 MCP 客户端，并支持表单和 JSON 两种创建方式。JSON 导入兼容：

1. 带 `mcpServers` 包装的配置。
2. 以客户端键为索引的映射配置。
3. 单个客户端对象。

支持的传输方式包括：

- `stdio`：命令、参数、环境变量和工作目录。
- `streamable_http`：URL 和请求头。
- `sse`：URL 和请求头。

前端和后端会兼容部分旧别名，并可根据是否存在 URL 推断传输类型。后端校验 `stdio` 必须有命令，远程传输必须有 URL。

客户端还包含：

- 稳定键、显示名称和描述。
- 启用状态。
- 工具白名单。
- OAuth 配置。
- 客户端默认及细粒度访问策略。

### 2.3 工具与访问策略

页面可以读取 MCP 服务实时暴露的工具、工具描述和输入 Schema，并设置工具白名单。白名单为空值表示允许暴露全部工具；指定列表表示只把选中的工具加载到 Agent 运行时。

工具白名单与访问策略是两个不同控制面：

- **工具白名单**决定工具是否进入 Agent 可见能力集合。
- **访问策略**决定工具被调用时是直接允许、需要确认还是拒绝。

访问策略支持：

- 客户端默认 `allow / ask / deny`。
- 按来源渠道和用户覆盖客户端默认策略。
- 单个工具默认策略。
- 按来源渠道和用户覆盖单个工具策略。

策略匹配综合目标、主体和来源的具体程度；同等匹配下采用更严格结果，严格程度为 `deny > ask > allow`。控制台会从该 Agent 的历史对话中提取最近出现的渠道和用户标识，辅助配置规则。

新建 MCP 客户端默认使用 `ask`，而通用 Driver 的底层安全默认值更严格。这个差异是产品层主动选择，后续重构不能意外改成默认放行。

### 2.4 OAuth

远程 MCP 支持 OAuth 授权、重新授权、撤销和状态轮询，并允许填写高级参数：

- Client ID。
- Scope。
- Authorization Endpoint。
- Token Endpoint。

后端实现 OAuth 2.1 元数据发现、PKCE、可选动态客户端注册、回调页面和令牌交换。授权状态暂存在进程内存，默认有效期约十分钟；服务重启会丢失尚未完成的授权流程，这是当前实现限制。

## 3. 后端 API 与 Agent 范围

MCP API 主要位于 `src/qwenpaw/app/routers/mcp.py` 和 `src/qwenpaw/app/routers/mcp_oauth.py`，包括：

- 列出和创建客户端。
- 读取、更新和删除指定客户端。
- 启用或停用客户端。
- 读取和更新工具白名单。
- 读取和更新访问策略。
- 读取最近访问主体。
- 发起、查询、回调和撤销 OAuth。

所有主 CRUD 都先通过请求中的 Agent 标识解析 workspace，因此当前 MCP 的自然归属对象是 **Agent**，不是全局部署，也不是某个聊天会话。

当前系统只有单账户认证，没有所有者、协作者、使用者和管理员授权判断。多用户目标中，必须在服务端按 Agent ACL 鉴权；隐藏前端菜单不能替代 API 授权。

## 4. 存储、迁移与密钥

### 4.1 DriverCard 主存储

`DriverConfigService` 将 MCP DriverCard 保存在 Agent workspace 的 `drivers/mcp` 目录。DriverCard 包含协议、端点绑定、普通配置、启用状态、工具白名单和访问策略。

workspace 启动时会：

1. 创建 `DriverManager`。
2. 注册 MCP Driver Handler。
3. 执行旧 MCP 配置迁移。
4. 启动 DriverManager。
5. 启动 DriverCard 文件监视器。

文件监视器允许人工编辑 `drivers/<protocol>/<name>.yaml` 后触发刷新或删除，说明文件仍是当前运行时的有效事实来源之一。

### 4.2 旧配置迁移

旧版模型仍在 `config.py` 中定义 `MCPConfig` 和 `MCPClientConfig`，并提供一个默认禁用的 Tavily MCP 示例。这些定义主要服务兼容和迁移，不代表 `agent.json.mcp.clients` 仍是当前页面的写入目标。

迁移由 `migrate_legacy_mcp_if_needed` 执行：

- 第一阶段将旧客户端转换为 DriverCard。
- 第二阶段将值完全等于 `${VAR}` 的环境变量或请求头转换为运行时环境凭据引用。
- 迁移水位会被持久化，防止用户删除的新 Driver 客户端在下次启动时又从旧配置“复活”。
- 迁移过程会生成报告，便于诊断。

测试已经明确验证：通过新 MCP API 创建客户端后，应写入 DriverCard 和凭据文件，而不是回写 `agent.json`。

### 4.3 密钥分类和加密

环境变量和请求头会先分类为公开值或敏感值：

- `Accept`、`Content-Type`、`User-Agent`、`X-Client-Name` 等常见请求头可作为公开配置。
- `Authorization`、`Cookie`、API Key 类请求头属于敏感数据。
- `NODE_ENV`、`LOG_LEVEL`、`DEBUG`、`MCP_MODE` 等环境变量可作为公开配置。
- 名称包含 `KEY`、`TOKEN`、`SECRET`、`PASSWORD`、`PASSWD`、`CREDENTIAL`、`AUTH` 的环境变量属于敏感数据。
- 未知项采用保守策略，默认按敏感数据处理。

敏感值进入 Agent workspace 的 `credentials.yaml`，由实例主密钥使用 Fernet 加密，写入采用原子替换；支持的平台会进一步限制文件权限。API 返回时只给脱敏值，更新请求再次提交脱敏占位符时会保留原密钥，而不是覆盖为占位文本。

普通 MCP 凭据记录使用 `mcp/<client>` 命名，OAuth 使用 `mcp/<client>/oauth`。完全等于 `${VAR}` 的值可以在运行时从服务进程环境解析，从而避免把真实值持久化到 Agent 文件。

旧 `MCPOAuthConfig` 中仍有“令牌明文保存到 agent.json”的过时注释；当前 Driver 主链路实际使用加密凭据存储。该注释只能视为历史遗留，不能作为现状设计依据。

## 5. 运行时工具加载和调用

### 5.1 连接生命周期

`MCPDriverHandler` 支持：

- 启动并管理 `stdio` 子进程。
- 建立 `streamable_http` 或 SSE 客户端连接。
- 将凭据注入环境变量和请求头。
- 自动补充认证请求头。
- 查询工具清单和调用工具。
- 缓存能力元数据并处理重连。

有状态远程客户端使用专门的生命周期任务，避免异步上下文在不同任务间退出导致连接损坏。发生短暂断线时可以暂用缓存的工具 Schema，但真正调用必须恢复有效连接；401 等响应会进入 OAuth/认证错误处理。

配置保存后会触发后台刷新。仅策略变化可以同步到现有实例而无需重新建立远程连接；名称、协议、端点、凭据或启用状态等关键变化会要求重连。

### 5.2 请求时能力构建

Agent 每次请求构建运行时工具集合时，从活跃 Driver 能力生成工具，而不是把 MCP 工具永久写死到 Agent 静态工具列表。调用上下文包含：

- 会话 ID。
- 用户 ID。
- 渠道来源。
- Agent ID 或根 Agent。

因此策略可以在调用时结合当前会话和调用者判断。MCP 返回的文本、结构化数据和资源内容会转换为统一的对话消息块，进入现有工具调用展示链路。

### 5.3 审批联动

Driver 策略进入 QwenPaw 审批服务：

- `allow` 可以直接执行，但仍受更高层会话审批模式影响。
- `ask` 会等待实际会话中的确认。
- `deny` 始终阻断，不得被会话级“关闭审批”绕过。

当前审批记录会携带 Driver、工具和扩展上下文，可能包含完整工具参数。多用户版本的审计存储必须对令牌、口令、Cookie、个人数据和业务敏感字段进行结构化脱敏，不能直接把全部参数写入普通审计文本。

## 6. 与其他模块的联动

### 6.1 Agent 管理

MCP 配置属于 Agent workspace，并随选中 Agent 切换。当前 Agent 复制接口主要复制 `agent.json`、指定 Markdown 文件、技能和任务等内容，不会复制新的 `drivers/` 目录与 `credentials.yaml`。

这意味着当前复制 Agent 后，源 Agent 的 MCP Driver 主配置不会完整出现在目标 Agent 中。另一方面，不复制凭据本身是正确的安全倾向：后续若增加“复制 MCP 配置”，也只能复制脱敏模板、工具白名单和策略，必须要求目标 Agent 重新绑定密钥，不能克隆可用凭据。

### 6.2 对话和斜杠命令

普通模型驱动的工具调用走新 DriverManager 主链路，可以发现并调用 MCP 工具。

但 `/slash/catalog` 及显式 MCP 斜杠路由仍读取旧 `agent_config.mcp.clients`，并尝试访问 workspace 上当前并未公开的 `mcp_manager`。旧 Runner 也保留 `set_mcp_manager` 和相关调用，而当前 workspace 工厂只注册 `driver_manager`，未发现给旧 Runner 注入 `mcp_manager` 的有效调用。

因此当前存在以下风险：

- MCP 页面新建的 DriverCard 客户端可能不会出现在斜杠命令目录。
- 显式 `/mcp client.tool` 校验可能无法使用新主链路的客户端。
- 页面、自动工具调用和斜杠命令对“已配置 MCP”的判断可能不一致。

`tests/unit/app/test_mcp_background_startup.py` 仍引用已经移除的旧 MCP manager 模块，也印证相关测试未完成迁移。这是现有缺陷，不是多用户改造产生的新需求；在实现权限体系前应先建立统一 Driver 接口并补足回归测试。

### 6.3 ACP 会话

ACP 客户端可以把会话级 MCP Server 配置传给 QwenPaw。后端将其转换为临时 DriverCard，通过作用域 ID 调用 `replace_transient_drivers`，会话结束时再调用 `remove_transient_drivers`。

这些 Driver：

- 只在对应 ACP 会话作用域内生效。
- 不写入持久 DriverCard 或凭据文件。
- 会防止与持久 Driver 名称发生不安全冲突。

多用户版本必须把 ACP 连接身份映射到平台用户和 Agent ACL；临时 MCP 不能借由 ACP 绕过“使用者不可配置共享应用工具”的限制。

### 6.4 Harness/Provider MCP

Harness Agent 可以从 Provider workspace 发现其自带 MCP 配置，控制台把这部分能力单独显示为只读内容。其生命周期和配置所有权属于 Provider 适配器，不应通过 Agent MCP CRUD 修改。

多用户设计中仍需统一运行时授权与审计，但管理入口和持久化边界必须保持分离。

### 6.5 备份与恢复

Agent 备份会递归打包整个 Agent workspace，因此 `drivers/mcp/*.yaml` 和 Agent 内的 `credentials.yaml` 都会随所选 Agent workspace 进入备份。备份若包含这些文件，就包含加密后的敏感数据；能否恢复解密还依赖匹配的实例主密钥。

全局备份可选择额外包含 secrets 目录。恢复逻辑在发现备份主密钥与当前主密钥不一致时，会先把当前主密钥备份到备份目录之外，避免无法恢复旧凭据。

对来自其他实例或旧版本、经用户显式信任的备份，恢复默认保留本地全局配置中的 `security` 和旧 `mcp` 键，防止外部备份静默替换本机安全控制。但这一保护只针对全局配置键，不会自动剥离 Agent workspace 内的 DriverCard 和加密凭据。

多用户版本必须把备份范围从“Agent 目录”提升为显式的数据归属策略：普通用户只能导出有权管理的私有对象；共享应用、密钥、审计和平台配置的备份恢复只能由管理员执行，并记录恢复来源和覆盖范围。

## 7. 当前缺陷与风险清单

| 编号 | 现状 | 影响 |
|---|---|---|
| MCP-01 | 新 Driver 主链路与旧斜杠命令/Runner 并存 | 同一 MCP 配置在页面、自动调用和斜杠命令中的可见性可能不一致 |
| MCP-02 | 旧 MCP 后台启动测试引用已移除模块 | 测试集合失败或无法覆盖当前真实启动链路 |
| MCP-03 | Agent 复制不复制 DriverCard | 复制后的 Agent 与源 Agent 功能不等价，且界面未必明确提示 |
| MCP-04 | OAuth 授权 state 仅在内存保存 | 服务重启后进行中的授权失效 |
| MCP-05 | 策略主体主要来自渠道/聊天用户标识 | 不能直接等同于未来的 Web 登录用户，存在身份碰撞和越权风险 |
| MCP-06 | 审批扩展信息可能包含完整工具参数 | 审计落库后可能泄露敏感业务数据或凭据 |
| MCP-07 | `stdio` 可启动本地进程，远程 MCP 可访问任意目标地址 | 存在命令执行、SSRF、内网访问和数据外传风险 |
| MCP-08 | 远程工具 Schema 可在服务端变化 | 已审核的共享应用能力可能在不重新发布时发生漂移 |
| MCP-09 | workspace 备份默认递归包含 DriverCard 和加密凭据 | 多用户导出、跨实例恢复和密钥轮换边界不清晰 |

## 8. 多用户目标设计约束

### 8.1 权限矩阵

| 操作 | 使用者 | 协作者 | 所有者 | 管理员 |
|---|---:|---:|---:|---:|
| 查看可用工具名称和用途 | 允许，限已发布能力 | 允许 | 允许 | 允许 |
| 调用工具 | 允许，按发布策略和实际审批 | 允许 | 允许 | 按审计/运维需要 |
| 查看 MCP 连接配置 | 禁止 | 允许脱敏查看可编辑 Agent | 允许脱敏查看自有 Agent | 允许审核全部 |
| 新增、编辑、停用 MCP | 禁止 | 允许编辑范围内草稿 | 允许自有 Agent/草稿 | 允许治理和紧急停用 |
| 查看、导出密钥 | 禁止 | 禁止 | 禁止读取明文，仅可替换 | 禁止普通读取明文，仅可治理/轮换 |
| 修改共享应用已发布版本 | 禁止 | 只能修改草稿 | 只能修改草稿 | 审核后发布、下架或回滚 |

任何角色都不应通过普通查询 API 取回密钥明文。管理员权限代表治理和轮换权，不等于任意读取第三方密钥明文。

### 8.2 身份模型

未来必须区分两类主体：

1. 平台登录用户：Web 控制台和共享应用的真实账户 ID。
2. 外部渠道身份：钉钉、飞书、微信、ACP 等来源中的发送者 ID。

访问策略不能只用一个裸 `user_id` 字符串。应至少带 `identity_type + source + subject_id`，并在已绑定外部身份时映射到平台用户；未绑定身份只能在明确渠道作用域内匹配，不能跨渠道或冒充平台账户。

### 8.3 草稿、发布和运行时

共享应用发布快照需要冻结：

- 脱敏后的 DriverCard 配置。
- 端点、命令、参数、工作目录和 OAuth Scope。
- 工具列表和工具 Schema 摘要。
- 工具白名单与访问策略。
- 所引用凭据的逻辑版本，不包含明文。

所有者/协作者修改 MCP 时只修改草稿。管理员审核并发布后，普通用户运行已发布快照；草稿变化不能直接影响线上版本。远程工具 Schema 或能力发生变化时应产生漂移告警，涉及新增工具、参数扩权或高风险能力时要求重新审核。

发布版本回滚只有在对应凭据仍存在且有效时才能恢复可运行状态；否则应明确显示“配置已回滚但凭据不可用”，不能静默换用其他密钥或服务。

### 8.4 密钥与数据存储

PostgreSQL 适合存储：

- Agent MCP 元数据与所有权。
- 草稿、发布版本和审核状态。
- DriverCard 的结构化配置与策略。
- 凭据引用、版本、创建者、更新时间和撤销状态。
- 调用审批和脱敏审计记录。

真实密钥仍应进入专门的加密凭据存储，数据库只保存密文或安全引用。密钥必须按 Agent/应用隔离，支持替换、撤销、轮换和引用检查。

私有运行时 workspace 必须限制 `stdio.cwd` 和文件访问范围。远程 URL 需要协议、目标地址和网络出口校验；共享应用中的 `stdio`、内网地址或高风险 OAuth Scope 至少必须进入管理员发布审核，必要时由部署级策略直接禁用。

### 8.5 删除与停用

- 删除私有 Agent 的 MCP 客户端时，应删除其配置并撤销专属凭据，但保留必要的脱敏审计。
- 已被共享应用发布版本引用的 MCP 配置不能直接物理删除，应先创建新草稿、重新审核发布或下架应用。
- 管理员紧急停用必须立即阻断运行时调用，并明确显示不可用原因，不能静默切换到其他工具或连接。
- 删除 Agent 时要检查共享、发布版本、凭据、审批中任务和备份策略，不能只删除目录。

## 9. 建议的修复与改造顺序

本节仅记录依赖顺序，不代表已经获得实施授权：

1. 用统一 Driver 查询与调用接口替换斜杠命令和旧 Runner 的 `mcp_manager` 引用，并补回归测试。
2. 明确 Agent 复制、导出和备份时 MCP 配置与凭据的产品语义。
3. 建立平台用户与外部渠道身份的统一调用主体模型。
4. 在服务端实现 Agent ACL 和 MCP 管理权限，不复用前端隐藏逻辑。
5. 建立密钥引用、轮换、撤销和敏感参数脱敏审计。
6. 把 MCP 配置纳入 Agent 草稿/发布快照和管理员审核。
7. 增加 `stdio`、远程 URL、OAuth Scope 和工具 Schema 漂移的安全治理。
8. 最后恢复页面、自动工具调用、斜杠命令、ACP、备份/恢复和共享应用的端到端回归测试。

## 10. 主要源码索引

### 前端

- `console/src/pages/Agent/MCP/`
- `console/src/api/modules/mcp.ts`
- `console/src/types/mcp.ts`

### API 与应用服务

- `src/qwenpaw/app/routers/mcp.py`
- `src/qwenpaw/app/routers/mcp_oauth.py`
- `src/qwenpaw/app/mcp/config_service.py`
- `src/qwenpaw/app/driver_config_service.py`
- `src/qwenpaw/app/driver_config_watcher.py`
- `src/qwenpaw/app/workspace/service_factories.py`
- `src/qwenpaw/app/approvals/driver_gate.py`

### Driver、凭据与迁移

- `src/qwenpaw/drivers/`
- `src/qwenpaw/drivers/handlers/mcp/`
- `src/qwenpaw/drivers/adapters/mcp_console.py`
- `src/qwenpaw/drivers/adapters/mcp_legacy_config.py`
- `src/qwenpaw/drivers/credentials/`
- `src/qwenpaw/config/config.py`

### 联动模块

- `src/qwenpaw/app/routers/slash.py`
- `src/qwenpaw/app/runner/runner.py`
- `src/qwenpaw/app/routers/agents.py`
- `src/qwenpaw/agents/acp/server.py`
- `src/qwenpaw/agents/acp/session_mcp.py`
- `src/qwenpaw/backup/_ops/create_helpers.py`
- `src/qwenpaw/backup/_ops/restore.py`
- `src/qwenpaw/backup/_ops/restore_helpers.py`

### 相关测试

- `tests/integration/test_acp_mcp_driver_flow.py`
- `tests/unit/app/test_mcp_background_startup.py`
- `tests/unit/backup/test_restore_trust_helpers.py`
- MCP Driver、策略、凭据和控制台路由相关测试目录。

## 11. 本专项的确认门

在进入总体多用户架构方案前，需要确认以下 MCP 目标边界：

1. MCP 以 Agent/共享应用为归属对象，而不是每个普通使用者自行配置一套连接。
2. 所有者和协作者可以在有编辑权的 Agent 草稿中配置 MCP；使用者只能调用。
3. 共享应用的 MCP 配置、工具范围和外部权限必须随发布版本由管理员审核。
4. 使用者不能查看或导出密钥；所有角色都不能通过普通接口读取密钥明文，只能替换、撤销和轮换。
5. 外部副作用由实际调用用户确认，且审批和调用都要形成脱敏审计。
6. ACP 临时 MCP、斜杠命令和 Harness MCP 也必须遵守同一身份、权限和审计边界。

