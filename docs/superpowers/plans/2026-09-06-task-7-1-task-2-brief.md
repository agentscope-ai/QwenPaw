# Task 7.1 / 2 授权目录与私人会话模型闭环

## 前置和决策

用户确认设计和真实元数据初始化策略：不复制密钥、不改原供应商配置、不删数据；初始化无普通用户授权，管理员明确授权后才启用强制治理。默认保持现有运行，页面必须明确显示“尚未启用”，不得声称此时已经强制按授权隔离。

Task 1 负责管理入口/凭据响应。沿用其能力鉴权和响应投影；先读Task1报告确定新增接口。现有 ProviderManager 文件继续是供应商连接及实际模型能力来源；PG是新增授权、停用状态和会话覆盖真源，不把Secret写入PG元数据，不用第二套文件授权绕开现有表。

## 现有持久化和确定接口

既有 Schema，无需新增迁移：model_providers、models、model_grants 在0001，conversations.model_override_id 在0002，system_settings/system_setting_revisions在0003。model_grants已有platform/user/agent类型；本次UI只提供明确用户授权，管理员固有管理/使用能力不依赖grant，禁止初始化自动platform授权。支持读取已有合法platform/user/agent grant，agent grant必须结合真实Agent使用权。

新建 src/qwenpaw/models/ 下职责独立模块（目录若已存在先复用）：records.py定义安全模型与设置类型，repository.py使用Schema限定SQL和database_session，governance.py提供授权/初始化/状态业务，runtime.py负责装配。不超过所需职责，不建万能registry。

建议固定契约：

```python
# ModelGovernanceService，全部公开管理操作先require MODELS_MANAGE
async def preview_import(actor, provider_manager): ...
async def import_metadata(actor, provider_manager): ...
async def list_catalog(actor, agent_id): ...
async def require_model(actor, agent_id, provider_id, model_key): ...
async def set_user_grant(actor, model_id, user_id, enabled): ...
async def set_model_status(actor, model_id, enabled): ...
async def set_enforced(actor, enabled, expected_version, reason): ...
```

签名可根据既有类型加类型注解，但变化需写入报告供前端消费。grant和status校验不能只是UI。设置system_settings key=`model_governance` value=`{"enforced": false}`，缺行视为尚未启用；DB不可达不应当作false放行。设置变更事务包含版本检查和system_setting_revisions记录。初始化幂等按provider稳定字符串键/model_key登记UUID；ON CONFLICT不覆盖管理员停用状态或授权。provider metadata只保存稳定键，绝不存apikey、URL认证信息、custom_headers、generate_kwargs/meta等任意配置。仅登记当前已配置可用供应商/本地已可用模型，预览和应用使用同一投影。

幂等键明确为 UUIDv5(NAMESPACE_URL, `qwenpaw:model-provider:<runtime-provider-id>`)；模型UUID为 UUIDv5(provider UUID, model_key)。model_providers.name 存稳定 runtime-provider-id 以匹配现有唯一约束，展示名放非敏感元数据的 display_name；改展示名不改数据库键。导入允许更新展示名/能力，不更新status/grants。授权为有效 user OR有效agent OR有效platform grant，enabled=false只撤销该条授权，不是覆盖其他授权的deny；全局停用优先于所有grant。UI本次仅创建用户grant，不自动补其他类型。

管理API独立路由 `/model-governance`：GET status、POST import/preview、POST import、GET models、PUT models/{id}/users/{user_id}、PATCH models/{id}/status、PUT enforcement。使用认证actor不接受created_by。GET `/model-catalog?agent_id=...` 返回 `{enforced, models:[{id, provider_id, provider_name, model, name, supports_image, supports_video, max_input_length, available}]}`，仅白名单；兼容期可提供旧已配置可用模型但明确enforced=false，强制期必须grant+status+实时Provider存在/模型存在。管理员模型页面展示“初始化/授权/启用”顺序，不自动启用。启用前提供未覆盖用户/默认模型的影响提示，由管理员明确提交，禁止隐式通用授权。

## 会话模型边界

新增专用Repository契约：

```python
async def set_model_override(self, conversation_id, *, expected_agent_id, model_override_id, updated_at): ...
```

扩展app/chats/repo/conversation.py和postgres_repo.py，保留其他字段，PG单条UPDATE RETURNING并限定owner当前用户及Agent；使用with_user(actor.user_id)和现有RLS，管理员也不因角色读取其他私人会话。测试和Legacy repository补齐最小接口，不新增抽象导致现有测试全部实例化失败。

新增 `/chats/{chat_id}/model` GET/PUT（或窄独立router挂载同前缀），request `{provider_id, model}` 或显式null清除；响应 `{active_llm, source, model_override, effective_max_input_length, locked}`。先require_chat_owner + Agent access，覆盖仅写当前会话，不写agent_config、不调用reload全Agent。PG模式覆盖持久化model_override_id；Legacy使用受控ChatSpec.meta字段及ChatManager锁，不同时双写PG与JSON。清除与未提交不同，模型不存在/停用/未授权显式错误。运行中切换明确409或次轮生效，选择一种一致方式并测试，不影响当前run。

Console `_resolve_console_chat` 后，可信actor+workspace.agent_id+chat.id解析覆盖；剔除客户端可伪造模型上下文，正式构造前复核。兼容期无model_grants强制但依然校验模型存在，非法显式覆盖不降级。优先级：有效服务端共享应用发布锁定 > 当前私人会话覆盖 > Agent显式默认 > 平台默认。复用agents/effective_model.py。不要只在UI过滤或只把字段塞进request而未使用。

新会话请求独立字段 `requested_model: {provider_id, model}` 是不可信候选，不是授权结果；实际chat创建/解析后先校验并持久化成功，再执行run。旧model_slot_override及客户端“已授权模型/发布上下文”不得绕过；存在且不合法的显式候选必须报错，不当作未指定。Repository UPDATE WHERE包含expected_agent_id且依RLS检查owner；清除null是显式命令，缺字段不是清除。

公共Agent现有agents.py model_locked基于visibility=PUBLIC的误判必须移除；共享应用真正发布服务尚未在本阶段实现，不能将public当published。仅可信服务端发布上下文可锁定，客户端传published_model_id/shared_app_id不得绕过；保留明确受控解析接口和单位测试，不新增第9阶段发布后台。报告中明确目前没有共享应用实机页面可验收，不声称其发布闭环完成。

没有可信发布解析器时，普通Agent请求按无发布上下文处理；尝试共享应用上下文明确authority_unavailable，不信任客户端。删除检测如发现shared_app_publications现有记录而无法可靠解释模型引用，保守409 publication_reference_unavailable，不扫描猜测未知manifest字段后放行。应用发布闭环留在阶段9。

## 前端

console/src/pages/Chat/ModelSelector/index.tsx改用安全目录和当前会话model API；新会话未落盘选择存当前用户+Agent+草稿，仅用于首次发送，创建后后端存对应会话覆盖。离开草稿/新建会话清除，不影响已有会话。后台异步返回必须核对身份+Agent+chat id，避免旧响应串台。右上角上下文长度使用实际模型。

Agent创建/编辑模型下拉同样用安全目录；管理员Settings/Models配置继续用管理接口。普通用户不显示OAuth管理/“去设置”等不可用操作。enforced=true后GET/models管理列表管理员限定，所有合法普通消费已转目录；兼容期也不可回读敏感配置。

已核实额外消费者不能漏改：Chat/index.tsx fetchMultimodalCaps 当前 listProviders+Agent effective，应按当前会话真实模型能力；发送前 getActiveModels 的预检也不得误用 Agent 模型阻断有效会话覆盖；限流建议按钮当前 setActiveLlm(scope=agent) 必须复用当前会话选择路径且只展示已授权候选。Settings/Agents/index.tsx 和 AgentModal.tsx 的全局模型读需要调整为普通角色可用的安全继承回显，不能因 Task1 管理读鉴权而误报无默认模型。Agent/Config/index.tsx 的目录消费也需切换。不得为兼容这些消费者重新开放管理接口。

管理员Settings/Models新增小型治理面板：初始化预览/登记、单模型授权用户、停用、显式启用治理状态；不重做原供应商页面。schema已有users列表但普通用户不能调用管理员列表。复用Task1权限呈现。

删除provider/model前检查平台默认、Agent配置默认、PG已有model_override和发布引用；有引用则409和管理员可定位摘要；不得删除真实数据作演示。管理员停用不改历史，下一次显式选择/使用报错。

## 测试与约束

先RED：tests/isolation/test_model_catalog.py、tests/unit/models/test_governance.py、tests/integration/test_model_governance_repository.py、tests/unit/app/chats/test_conversation_model.py、tests/integration/test_model_resolution.py；名称可依实际归属调整。新测试使用合成Secret，真实PG测试使用现有postgres_test_schema一次性Schema，不操作18089真实表；主流程单独控制实际初始化。

覆盖幂等导入不改grants/status、不含Secret；用户A有grant/B无；伪造user/Agent/会话不生效；多用户同Agent会话模型不串；清除/刷新/新会话默认；invalid/disabled不fallback；DB异常不放行；公共Agent不锁；可信发布模型锁/伪造发布上下文拒绝；引用阻止删除。

前端TDD覆盖ModelSelector真实请求体不再scope=agent，身份切换旧响应被忽略，初始化和显式授权流程。运行相关测试+完整build一次；报告包含RED/GREEN和准确变更清单。不得修改现有用户文件、服务、依赖、系统环境、真实模型配置，不git commit/stage/branch/worktree/reset/clean。缺少权限或跨任务架构疑问先询问主流程。

## 报告

docs/superpowers/plans/2026-09-06-task-7-1-task-2-report.md。报告接口最终契约、测试、部署初始化预览方式、未验证边界。下一任务独立评审和真实浏览器初始化由主流程进行。
