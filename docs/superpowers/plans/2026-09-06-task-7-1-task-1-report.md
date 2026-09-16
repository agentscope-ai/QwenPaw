# Task 7.1 / 1 实施报告：管理入口与不可回读凭据

## 状态

DONE_WITH_CONCERNS

本任务仅实现供应商、模型、本地运行时及 Provider OAuth 管理入口授权，以及供应商凭据不可回读。未实施 `model_grants`、用户目录授权、会话模型覆盖、数据库迁移或真实配置变更。

## 基线与脏工作区保护

- 编辑前将本任务候选文件当前内容复制到 `.superpowers/task-7-1-task-1-baseline/`，作为相对于现有脏工作区的逐文件基线。
- 后续发现实际 UI 消费者和既有路由测试也需调整时，均在编辑前追加对应基线副本。
- 未执行 Git 提交、暂存、分支、工作树、重置或清理；未覆盖或回滚用户原有改动。

## RED 证据

后端首次有效 RED：

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short
6 failed, 3 passed, 1 warning
```

失败分别证明：普通成员可访问 Provider 配置、本地运行时配置和 OAuth 启动入口；`GET /models` 与保存响应会回读合成密钥；旧掩码可被写成真实凭据。

前端首次 RED：

```text
npm run test:run -- src/pages/Settings/Models/providerCredentials.test.ts
1 failed suite: Failed to resolve import "./providerCredentials"
```

第二轮 RED 补充了全局活动模型管理读、嵌套敏感值保留和自定义头显式清除：后端 2 failed，前端 2 failed。

## 实现与接口变化

### 后端

- `/models`：保留兼容目录 `GET /models` 和会话使用的非全局 `/models/active` 路径；其余 Provider/模型管理入口使用真实 `Capability.MODELS_MANAGE` 授权。`GET /models/active?scope=global` 作为管理读要求该能力。
- `/local-models`：所有本地运行时读写入口统一要求 `Capability.MODELS_MANAGE`；单用户 Legacy 模式保持原兼容行为。
- `/providers/{provider_id}/oauth`：启动与状态管理入口要求 `Capability.MODELS_MANAGE`；外部 OAuth callback 依赖不可猜测状态会话，保持回调可达，且失败不保存或返回上游异常文本。
- 新增安全响应投影：复制 `ProviderInfo` 后再清除 `api_key`，通过 `api_key_configured` 表达是否已配置；删除敏感 `custom_headers`、`generate_kwargs`、`meta` 项；剥离 URL userinfo 并遮蔽敏感查询参数。不会修改共享 Provider 运行时实例。
- Provider 配置请求新增：
  - `clear_api_key: boolean = false`
  - `clear_custom_headers: boolean = false`
- `api_key` 未提交或为空时保留旧值；提交新值时替换；掩码占位符不写入；只有 `clear_api_key=true` 明确清除。
- 自定义头未编辑时保留；提交非空头时更新且保留未提交的敏感旧头；只有 `clear_custom_headers=true` 明确清除。
- `generate_kwargs` 更新会合并回未提交的敏感嵌套值，避免安全投影后的空白值误清除旧凭据。
- Provider/模型连接失败响应改为稳定脱敏文本，不回传连接层异常中的密钥、带凭据 URL 或请求凭据。

### 前端

- `ProviderInfo` 新增 `api_key_configured`；配置请求新增两个显式清除字段。
- Provider 配置表单不回填旧密钥；空输入不发送 `api_key`；新值才替换；撤销按钮发送 `clear_api_key=true`。
- 自定义头编辑增加 dirty 状态：未编辑不提交，编辑为空发送显式清除，编辑为非空发送替换值。
- 模型设置卡片和配置判断使用 `api_key_configured`，不再依赖后端返回掩码密钥；界面仅显示固定占位符。

## 变更文件

后端与测试：

- `src/qwenpaw/app/routers/providers.py`
- `src/qwenpaw/app/routers/local_models.py`
- `src/qwenpaw/app/routers/provider_oauth.py`
- `src/qwenpaw/providers/provider.py`
- `src/qwenpaw/providers/api_projection.py`（新增）
- `tests/isolation/test_model_governance.py`（新增）
- `tests/unit/app/routers/test_provider_rename.py`

前端与测试：

- `console/src/api/types/provider.ts`
- `console/src/pages/Settings/Models/providerCredentials.ts`（新增）
- `console/src/pages/Settings/Models/providerCredentials.test.ts`（新增）
- `console/src/pages/Settings/Models/components/modals/ProviderConfigModal.tsx`
- `console/src/pages/Settings/Models/components/cards/RemoteProviderCard.tsx`
- `console/src/pages/Settings/Models/components/cards/ProviderGroupCard.tsx`
- `console/src/pages/Settings/Models/components/sections/ModelsSection.tsx`
- `console/src/pages/Settings/Models/utils.ts`

## GREEN 与回归证据

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short
11 passed, 1 warning

.venv/Scripts/python.exe -m pytest tests/unit/providers/test_provider_manager.py tests/unit/app/routers/test_provider_oauth_router.py tests/unit/app/routers/test_provider_rename.py tests/unit/app/routers/test_provider_context_window.py tests/unit/app/routers/test_providers_model_inheritance.py -q --tb=short
48 passed, 1 warning

npm run test:run -- src/pages/Settings/Models/providerCredentials.test.ts src/pages/Settings/Models/utils.test.ts src/pages/Settings/Models/useProviders.test.ts src/api/modules/provider.test.ts
4 files passed, 31 tests passed

npx tsc -b --noEmit
exit 0

.venv/Scripts/python.exe -m compileall -q <本任务 Python 文件>
exit 0
```

警告为现有 FastAPI TestClient 的 Starlette/httpx 弃用提示。

## 自审

- 授权检查发生在路由依赖阶段，未授权请求不会进入 Manager 写操作。
- 目录投影创建新的 Pydantic 对象，不修改 ProviderManager 持有的凭据实例。
- 前后端都使用显式清除字段，避免“空字符串代表保留还是清除”的歧义。
- 未引入新的存储、抽象层或迁移，符合 KISS/YAGNI；敏感字段识别和投影集中在单一模块，避免各路由重复脱敏。

## 关注点与明确未完成项

- 虚拟环境未安装 Ruff，遵守“不安装依赖”约束未补装；Python `compileall` 通过。
- 相关 5 个前端既有文件在编辑前基线中已不满足当前 Prettier 检查；未批量格式化用户已有修改。TypeScript 编译和定向测试均通过。
- `GET /models` 仍是聊天和 Agent 编辑使用的兼容目录；本任务只保证不返回明文凭据。普通用户模型授权、`model_grants`、目录拆分及会话模型覆盖仍由后续任务完成，不能据此宣称 7.1 用户模型授权已完备。
- 未执行真实 OAuth、真实供应商网络请求、服务重启、部署或真实配置/数据修改。

## Fix round 1/5（独立评审修复）

### 本轮基线与评审增量

- 修复前基线：`.superpowers/task-7-1-task-1-fix1-baseline/`
- 本轮实际 unified diff：`.superpowers/task-7-1-task-1-fix1.diff`
- diff 仅比较本轮修复前基线与当前文件，不包含 Task 1 首轮实现或其他脏工作区改动。

### 处理的评审项

1. URL 投影现已覆盖 `key`、`sig`、`signature` 等签名查询参数，移除 fragment，剥离 userinfo，并使用完整 `ProviderInfo` 中已识别的 Secret 集合替换非敏感键或普通字符串中重复出现的已知 Secret 值。
2. IPv6 host 投影恢复方括号，保留合法端口，避免脱敏后破坏 URL。
3. 嵌套敏感配置保存支持 dict 与 list 递归合并；列表采用可验证的按位置语义：对仍存在的同位置元素递归保留未提交敏感字段，新增元素按提交值写入，删除元素不复活。
4. `api_key=""` 和缺省值均保留旧密钥；仅非空新值替换，仅 `clear_api_key=true` 清除。
5. Base URL 使用显式协议：未改或空字符串直传均不持久化；非空新值替换；`clear_base_url=true` 明确清除。前端比较初始投影 URL，未编辑时测试与保存均不发送该 URL，避免脱敏 URL 覆盖原始认证 URL。

### Fix RED

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short
4 failed, 9 passed, 1 warning

npm run test:run -- src/pages/Settings/Models/providerCredentials.test.ts
2 failed, 6 passed
```

失败精准覆盖签名参数/fragment/已知 Secret 传播与 IPv6、空 API key、列表嵌套保真、Base URL 保留/替换/清除及前端未编辑序列化。

### Fix GREEN

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short
13 passed, 1 warning

npm run test:run -- src/pages/Settings/Models/providerCredentials.test.ts src/pages/Settings/Models/utils.test.ts src/pages/Settings/Models/useProviders.test.ts src/api/modules/provider.test.ts
4 files passed, 33 tests passed

npx tsc -b --noEmit
exit 0

.venv/Scripts/python.exe -m compileall -q src/qwenpaw/providers/api_projection.py src/qwenpaw/app/routers/providers.py tests/isolation/test_model_governance.py
exit 0
```

Starlette/httpx 弃用警告仍为既有技术债，本轮未安装或升级依赖。

## Fix round 2/5（第二次 scoped re-review 修复）

### 本轮基线与增量

- 修复前基线：`.superpowers/task-7-1-task-1-fix2-baseline/`
- 本轮实际 unified diff：`.superpowers/task-7-1-task-1-fix2.diff`

### 处理的剩余评审项

1. `base_url` 不再只清理 URL 结构中的 userinfo/query/fragment；结构化处理后统一对完整返回字符串替换已知 Secret，因此绝对 URL path 和非绝对 URL 中的已知 Secret 都不会回读。
2. 取消敏感列表按索引合并。当前无稳定元素 ID 契约时，以“安全投影是否隐藏信息”判定受保护列表：
   - 提交值与安全投影完全一致：视为未编辑，保留原始整个列表；
   - 删除、插入、重排或内容修改：在 Manager 写入前返回 HTTP 409，并完整保留旧配置；
   - 不含隐藏信息的普通列表：允许正常替换。
3. 新增真实 HTTP 测试覆盖绝对 URL path、非绝对 URL、受保护列表安全往返、删除、插入、修改、重排，以及普通列表编辑。

### Fix 2 RED

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short
6 failed, 14 passed, 1 warning
```

### Fix 2 GREEN

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py -q --tb=short
20 passed, 1 warning
```

既有 Starlette/httpx 弃用警告继续作为技术债记录，未安装或升级依赖。
