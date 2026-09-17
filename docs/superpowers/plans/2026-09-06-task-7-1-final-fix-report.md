# Task 7.1 最终修复波实施报告

状态：完成限定修复与精准验证；未部署、未操作真实数据库/服务/模型配置，未执行 Git 提交、暂存、分支或清理。

## 范围与基线

本轮严格限定两项：Agent 默认模型写权限，以及 Legacy 会话模型覆盖的删除引用检查。修改前文件保存在 `.superpowers/task-7-1-final-fix-baseline/`；完整实际 unified diff 为 `.superpowers/task-7-1-final-fix.diff`，比较本轮专属基线而非 HEAD。

## 变更

1. `src/qwenpaw/app/routers/providers.py`
   - `/models/active` 路由依赖改为显式区分 GET 与 PUT。GET 保留既有非 global 读取兼容；PUT 因 scope 位于 body，明确交给 handler 分支鉴权。
   - global 写继续要求 `MODELS_MANAGE`。
   - Agent 默认写在可信 Agent 解析后复用 `require_running_config_editor`，仅 owner/collaborator（以及既有管理员代管上下文）允许配置；public/use-only 用户返回 403。
   - `HTTPException` 原样传播，不再被通用保存异常转换为 500；拒绝发生在加载、保存及 reload 前。

2. `src/qwenpaw/models/runtime.py`
   - `require_no_model_references` 在 Legacy 模式复用现有 `JsonChatRepository`，按根配置中全部 Agent 的 `workspace_dir/chats.json` 扫描 `ChatSpec.meta.model_override`。
   - provider 删除、指定模型删除和 `qwenpaw-local` 本地模型删除均使用相同匹配逻辑；命中时返回 `model_in_use: conversation_override:<agent>:<chat>`。
   - 文件读取、JSON/Schema 校验或 override 校验不完整时保守返回 `model_reference_authority_unavailable`，不允许继续删除。
   - 无会话文件或完整扫描无引用时保持原正常路径。

3. 测试
   - 真实 FastAPI `TestClient` HTTP 覆盖 MEMBER 对 public/use-only Agent PUT 返回 403 且 Agent 配置快照、私人会话覆盖快照均不变。
   - 同一路径覆盖 owner 与 collaborator 可修改 Agent 默认，同时私人会话覆盖保持独立。
   - 真实临时 `chats.json` 覆盖 provider、模型、本地模型三种 Legacy 删除引用，以及无引用放行和损坏存储失败关闭。

实现复用既有配置角色门控和 JSON 会话仓储（DRY/SOLID），仅增加当前要求的两条安全边界（KISS/YAGNI），未新增 schema、依赖或平行权限体系。

## TDD 证据

RED（生产代码修改前）：

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py tests/unit/models/test_governance.py -q --tb=short
5 failed, 28 passed, 1 warning, exit 1

失败原因：
- public/use-only Agent 默认写请求实际返回 200（期望 403）；
- provider、模型、本地模型三个 Legacy override 引用均未抛出；
- 损坏 chats.json 未失败关闭。
```

首次 GREEN：

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py tests/unit/models/test_governance.py -q --tb=short
33 passed, 1 warning, exit 0
```

最终精准回归：

```text
.venv/Scripts/python.exe -m pytest tests/isolation/test_model_governance.py tests/isolation/test_model_catalog.py tests/unit/models/test_governance.py tests/unit/app/routers/test_providers_model_inheritance.py tests/unit/app/routers/test_agent_model_inheritance.py tests/integration/test_providers.py -q --tb=short
57 passed, 1 warning, exit 0
```

唯一警告是既有 `StarletteDeprecationWarning`：当前 `fastapi.testclient` 使用已弃用的 `httpx` 集成；本轮未升级依赖。

语法与产物核验：

```text
.venv/Scripts/python.exe -m compileall -q src/qwenpaw/app/routers/providers.py src/qwenpaw/models/runtime.py
exit 0

.venv/Scripts/python.exe .superpowers/task-7-1-final-fix-make-diff.py
.superpowers/task-7-1-final-fix.diff = 5 个实际变更文件的 unified diff
```

## 未执行项

- 按要求未跑全量 build，仅运行覆盖修改路径的精准后端测试。
- 未执行真实 PostgreSQL、真实服务、供应商请求、本地模型安装/删除或配置写入。
- 未进行任何 Git 操作。
