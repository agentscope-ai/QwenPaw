# Task 4.5-C/2 Agent 初始化与默认模型继承设计

## 1. 目标

修复新建或复制 Agent 时默认模型继承不一致的问题，使 Agent 的聊天模型语义明确、可持续运行，并保证 ReMe、聊天、自动记忆等使用 Agent 聊天模型的组件采用同一套有效模型解析规则。Embedding 模型继续使用它自己的独立配置。

已确认的业务规则：

1. Agent 未指定模型时，自动跟随管理员配置的全局默认模型。
2. Agent 明确指定模型时，固定使用该模型。
3. 管理员拥有模型供应商和模型配置权限；普通用户只能使用平台已配置模型，不改变供应商权限边界。
4. 现有 Agent 的 `active_model` 有值，视为显式固定；为空，视为继承全局默认，不根据不可靠的历史数据库字段反向覆盖。

## 2. 当前根因

当前实现存在四个不一致点：

- `POST /api/agents` 在请求未指定模型时尝试从 `ProviderManager` 读取全局模型，但异常被静默吞掉，可能保存没有 `active_model` 的 `agent.json`。
- `POST /api/agents/{agentId}/copy` 复制源配置的 `active_model`，但没有明确表达源 Agent 是继承还是显式固定。
- `POST /api/models/active` 在全局模型变更时，会把当前 Agent 的空 `active_model` 写成新模型，导致继承型 Agent 被静默固化。
- 聊天的 `create_model_and_formatter` 和部分运行时组件支持全局回退，但 ReMe 启动依赖直接调用模型创建，导致“聊天可能可用、ReMe 启动失败”的分裂状态。

## 3. 设计方案

### 3.1 配置事实来源

`agent.json.active_model` 继续作为 Agent 是否显式固定的唯一配置事实来源：

```text
active_model = {provider_id, model}  -> explicit，固定模型
active_model = null                  -> inherited，实时跟随全局默认
```

PostgreSQL 的 `default_model_mode` 只保存治理索引和列表查询摘要。创建、编辑和复制成功后同步该字段；历史数据迁移以 `agent.json` 为准幂等校正数据库摘要，绝不反向覆盖已有 Agent 配置。

### 3.2 统一有效模型解析器

新增一个单一职责的解析接口，所有运行时模型依赖通过该接口获得有效模型：

```python
def resolve_effective_model(
    agent_config: AgentProfileConfig,
    *,
    provider_manager: ProviderManager | None = None,
) -> ModelSlotConfig:
    """Resolve explicit Agent model or current global default."""
```

解析顺序：

1. `agent_config.active_model` 存在且 provider/model 均非空：校验供应商和模型存在后返回。
2. `active_model` 为空：读取当前全局默认模型并校验供应商和模型存在后返回。
3. 两者均无效：抛出包含操作建议的明确异常，不返回隐式 128K 或空模型。

该接口只负责解析和校验，不写磁盘、不修改数据库、不触发 reload，便于单元测试和复用。

### 3.3 创建

`POST /api/agents` 的行为：

- 请求包含完整 `active_model`：校验 provider/model，保存显式配置，数据库写入 `explicit`。
- 请求未包含模型：不复制当前全局模型快照，保存 `active_model=null`，数据库写入 `inherited`。
- 创建继承型 Agent 时不要求把全局模型写进 `agent.json`，但在启动前必须通过统一解析器确认当前全局模型有效。
- 若无全局默认模型，创建操作在创建目录、写数据库草稿和写配置前完成校验并返回明确错误，避免残留半成品。

### 3.4 编辑

- 选择具体供应商和模型：保存 `active_model`，同步 `explicit`。
- 清空模型：保存 `active_model=null`，同步 `inherited`。
- 保存前校验模型存在；失败不改 `agent.json`、版本、数据库模式或运行态。
- 保存成功后按既有配置版本和 reload 机制处理，不改变其他运行配置字段。

### 3.5 复制

- 源 Agent `active_model=null`：副本保持 `null`，数据库模式为 `inherited`。
- 源 Agent 有有效 `active_model`：副本复制该值，数据库模式为 `explicit`。
- 复制不复制会话、记忆索引、用户私有目录和频道绑定；保留现有白名单文件复制语义。
- 如果源 Agent 的显式模型已经失效，复制应失败并说明供应商/模型，而不是生成不可启动副本。

### 3.6 全局默认模型变更

全局模型变更只更新 ProviderManager 全局配置：

- 不批量改写继承型 Agent 的 `agent.json`。
- 不把继承型 Agent 写成显式模型。
- 全局模型保存成功后，对已加载的继承型 Agent 执行受控 reload，使聊天和 ReMe 等长生命周期组件立即使用新模型；显式 Agent 不重载。
- 任一继承型 Agent reload 失败时，全局模型保存仍保持成功，但响应必须返回待重载 Agent 列表，页面显示可重试状态。
- `/api/models/active?scope=effective&agent_id=...` 返回解析后的有效模型；`scope=agent` 仍只返回显式配置，空值表示继承。

### 3.7 ReMe 与其他运行时

以下入口必须改为调用同一个有效模型解析器：

- RuntimeBuilder 模型校验和模型创建。
- `create_model_and_formatter` 的 Agent 模型选择。
- ReMe Light 的 LLM 更新。
- 自动记忆、手动记忆、梦境和其他使用 Agent 模型的后台入口。

Embedding 配置和重建索引语义不参与本解析器，避免将聊天模型错当成 Embedding 模型。

这样可以保证：如果继承型 Agent 的全局模型有效，ReMe 与聊天都能启动；如果全局模型无效，所有组件给出同一类明确错误，且记忆服务仍保持可选服务语义，不拖垮整个 Agent。

## 4. 错误与事务边界

- Provider 不存在、模型不存在、全局默认为空：返回可读错误，包含 provider/model 或“请先配置全局默认模型”的建议。
- 创建失败发生在持久化前；若数据库 owner 登记已先执行，则必须在同一操作中回滚或清理草稿登记。
- 编辑失败不改变旧配置和版本。
- 运行时解析失败不把私有记忆降级为公共记忆，不把空模型伪装成可用模型。
- 日志记录 Agent ID、解析来源（explicit/inherited）和 provider/model，但不记录 API key。

## 5. 前端行为

Agent 创建/编辑弹窗保持现有交互：

- 模型下拉为空时显示“使用全局默认”，并显示当前全局模型摘要。
- 选择模型后显示“指定模型”。
- 清空选择可恢复继承。
- 列表中区分“全局默认（当前模型）”与“指定模型”。
- 不向普通用户开放供应商配置入口；已有共享/仅使用 Agent 的模型锁定和只读摘要不变。

## 6. 验收设计

必须同时通过后端、前端和真实服务验证：

1. 创建继承型 Agent，检查 `agent.json.active_model=null`、数据库模式 `inherited`，启动聊天和 ReMe 成功。
2. 修改全局模型，继承型 Agent 的有效模型随之变化，`agent.json` 不被改写。
3. 创建显式模型 Agent，修改全局模型后仍使用原模型。
4. 编辑清空模型后恢复继承；重新指定模型后恢复固定。
5. 复制继承型和显式型 Agent，分别验证副本语义。
6. 无全局默认模型时，创建继承型 Agent 被拒绝且无残留目录、配置或数据库草稿。
7. ReMe、聊天和自动记忆使用同一有效模型；工具执行过程、Reasoning、审批和其他既有聊天事件不改变。
8. 管理员和普通用户权限边界不变；普通用户不能修改供应商或平台全局模型。

## 7. 非目标

- 不迁移记忆正文到 PostgreSQL。
- 不改变 Agent Loop、聊天事件模型、工具执行展示、频道绑定或 ACP 开关。
- 不批量覆盖已有 Agent 配置。
- 不删除现有 Agent、模型供应商或临时验收 Agent。
