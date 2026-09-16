# Task 4.5-B 运行配置卡片保真实施计划

> **执行方式：** 在当前工作区按任务顺序内联执行。每个任务完成自动化测试和真实页面验收后停止，等待用户确认再继续。不得使用子 Agent，不得创建工作树，不得执行 Git 操作。

**目标：** 逐张恢复并证明原运行配置卡片在多用户架构下的加载、保存、校验、持久化、热重载和失败恢复保真，同时消除管理员代管页面与卡片内部独立接口目标 Agent 不一致的问题。

**架构：** 页面构造唯一的 `AgentRequestContext`，主表单 Hook、基础设置卡片、项目选择弹窗以及 Embedding/记忆状态等独立请求都显式消费该上下文。后端复用 `get_running_config_workspace()` 的管理员显式治理语义扩展关联接口；完整配置保存继续基于服务端原配置做字段覆盖，并保留版本冲突、局部回滚和 `pending_reload` 契约。

**技术栈：** FastAPI、Pydantic、React 18、TypeScript、Ant Design/AgentScope Design、Vitest、pytest、Playwright、文件型 `agent.json`、PostgreSQL Agent 访问关系。

## 全局约束

- 不新增或修改数据库表，不迁移运行配置到 PostgreSQL。
- 不改变 `agent.json` 作为当前 Agent 运行配置内容源。
- 不改变用户个人时区的用户级语义。
- 不改变模型供应商和模型配置的管理员权限边界。
- 不重新设计原配置字段、默认值、卡片布局或即时/统一保存交互。
- 不提前执行 Task 4.5-C 的记忆与循环综合运行效果验收。
- 每项生产代码变更先观察对应测试 RED，再做最小实现得到 GREEN。
- 管理员代管必须显式携带目标 Agent 和治理标记，不能依赖侧边栏当前 Agent。
- 只有 owner、collaborator 或显式治理管理员可修改 Agent 配置；user 只能看安全摘要。
- 保存成功但整体热重载失败时保留配置并显示 `pending_reload`。
- Embedding 局部更新失败继续使用原有字段级安全回滚，不覆盖无关并发修改。
- 不执行 Git commit、push、reset、分支、工作树或数据删除操作。

## 文件职责

- `console/src/api/modules/agentRequestContext.ts`：集中合并目标 Agent 与治理请求头。
- `console/src/api/modules/{agent,projectDirectory,codingMode,plan}.ts`：统一消费可选请求上下文。
- `console/src/components/ProjectSelectModal/index.tsx`：项目弹窗的列表、设置、创建、导入、上传、克隆和浏览使用统一目标。
- `console/src/pages/Agent/Config/components/ReactAgentCard.tsx`：基础设置中的独立接口使用统一目标。
- `console/src/pages/Agent/Config/configMerge.ts`：纯函数完成完整配置保真合并。
- `src/qwenpaw/app/agent_context.py`：精确限定运行配置治理关联路径。
- `src/qwenpaw/app/routers/{project_directory,coding_mode,plan}.py`：普通成员与显式治理目标解析及写前授权。
- `tests/unit/app/routers/test_runtime_config_targeting.py`：跨路由目标与权限契约。
- `docs/project-audit/17-运行配置卡片保真矩阵.md`：卡片、字段、接口、模型、文件、校验和重载证据。

---

### Task 4.5-B/1：配置卡片契约与统一目标上下文

**可验收成果：** 管理员代管 Agent A 时，即使侧边栏选中 Agent B，基础设置、项目弹窗、编码能力和计划模式的所有 Agent 级请求都操作 A；普通路径不变。

**文件：**

- Create: `console/src/api/modules/agentRequestContext.ts`
- Create: `console/src/api/modules/agentRequestContext.test.ts`
- Modify: `console/src/api/modules/agent.ts`
- Modify: `console/src/api/modules/projectDirectory.ts`
- Modify: `console/src/api/modules/projectDirectory.test.ts`
- Modify: `console/src/api/modules/codingMode.ts`
- Modify: `console/src/api/modules/codingMode.test.ts`
- Modify: `console/src/api/modules/plan.ts`
- Create: `console/src/api/modules/plan.test.ts`
- Modify: `console/src/components/ProjectSelectModal/index.tsx`
- Create: `console/src/components/ProjectSelectModal/index.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/ReactAgentCard.tsx`
- Create: `console/src/pages/Agent/Config/components/ReactAgentCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/index.tsx`
- Modify: `src/qwenpaw/app/agent_context.py`
- Modify: `src/qwenpaw/app/routers/project_directory.py`
- Modify: `src/qwenpaw/app/routers/coding_mode.py`
- Modify: `src/qwenpaw/app/routers/plan.py`
- Create: `tests/unit/app/routers/test_runtime_config_targeting.py`
- Create: `docs/project-audit/17-运行配置卡片保真矩阵.md`

**接口：**

```ts
export interface AgentRequestContext {
  agentId?: string;
  governance?: "runtime-config";
}

export function withAgentRequestContext(
  options?: RequestOptions,
  context?: AgentRequestContext,
): RequestOptions | undefined;
```

- [ ] **Step 1：写前端请求上下文失败测试**

断言治理目标生成 `X-Agent-Id` 和 `X-Agent-Governance: runtime-config`，且保留已有 `If-Match`、`Content-Type` 请求头。项目目录测试覆盖 `get/set/list/create/importLocal/uploadZip/browseDirs/cloneStream`，编码模式覆盖 `get/toggle`，计划配置覆盖 `getPlanConfig/updatePlanConfig`。

- [ ] **Step 2：运行前端 API 测试确认 RED**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/api/modules/agentRequestContext.test.ts `
  src/api/modules/projectDirectory.test.ts `
  src/api/modules/codingMode.test.ts `
  src/api/modules/plan.test.ts
```

预期：统一辅助模块不存在，三个 API 模块不接受治理上下文。

- [ ] **Step 3：实现统一请求上下文辅助函数**

将 `agent.ts` 的私有治理请求头逻辑移动到新模块；各 API 方法增加最后一个可选 `context` 参数。普通调用不传参数时保持现有行为。`uploadZip` 与 `cloneStream` 直接 `fetch()` 也必须复用同一请求头函数。

- [ ] **Step 4：写组件目标传播失败测试**

向 `ReactAgentCard` 和 `ProjectSelectModal` 传入 `{agentId: "governed-agent", governance: "runtime-config"}`，断言初始化、计划切换、编码切换及项目弹窗全部使用相同对象；个人时区回调不接收该上下文。

- [ ] **Step 5：运行组件测试确认 RED**

```powershell
npm run test:run -- `
  src/pages/Agent/Config/components/ReactAgentCard.test.tsx `
  src/components/ProjectSelectModal/index.test.tsx
```

- [ ] **Step 6：由页面下发唯一目标上下文**

`AgentConfigPage` 从已确认的治理 URL 构造一次上下文，同时传给 `useAgentConfig`、`ReactAgentCard` 和项目弹窗。组件不得自行读取 URL 或管理员状态。

- [ ] **Step 7：写后端目标与权限失败测试**

覆盖项目目录读写、计划配置读写和编码能力读写：管理员治理请求操作请求头目标；管理员无治理标记访问他人 Agent 返回 403；user 写请求在保存、目录创建、上传解压或 reload 之前返回 403。

- [ ] **Step 8：运行后端测试确认 RED**

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/app/routers/test_runtime_config_targeting.py"
```

- [ ] **Step 9：实现后端显式治理目标解析**

精确加入 `/coding-mode`、`/plan/config`、`/workspace/project-directory` 及页面使用的项目目录子路径。`/plan/current` 与 `/plan/stream` 不进入治理白名单。所有写接口在文件、Git、上传解压和 reload 副作用前完成授权。

- [ ] **Step 10：运行 Task 1 全部测试确认 GREEN**

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/app/routers/test_runtime_config_targeting.py" `
  "tests/unit/app/routers/test_workspace_router.py"

Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/api/modules/agentRequestContext.test.ts `
  src/api/modules/projectDirectory.test.ts `
  src/api/modules/codingMode.test.ts `
  src/api/modules/plan.test.ts `
  src/pages/Agent/Config/components/ReactAgentCard.test.tsx `
  src/components/ProjectSelectModal/index.test.tsx `
  src/pages/Agent/Config/useAgentConfig.test.tsx
```

- [ ] **Step 11：编写卡片契约矩阵**

逐字段记录页面卡片、Form 路径或独立 API、后端模型字段、持久化位置、校验规则、热重载方式、角色权限和后续验收任务编号，不使用占位符或“同上”。

- [ ] **Step 12：真实页面验收并停止**

侧边栏选择管理员 Agent B，再代管用户 Agent A；检查项目目录、编码能力和计划模式读取 A，修改一个可恢复值并刷新，证明 A 改变且 B 不变，随后恢复。输出请求头、A/B 回读和页面截图，等待用户确认。

---

### Task 4.5-B/2：基础设置与独立即时保存保真

**可验收成果：** 语言、个人时区、Shell、项目目录、编码能力、标题生成、计划模式和记忆后端正确保存与回读；失败恢复原值，主表单保存不覆盖独立设置。

**文件：**

- Create: `console/src/pages/Agent/Config/configMerge.ts`
- Create: `console/src/pages/Agent/Config/configMerge.test.ts`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.tsx`
- Modify: `console/src/pages/Agent/Config/useAgentConfig.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/ReactAgentCard.tsx`
- Modify: `console/src/pages/Agent/Config/components/ReactAgentCard.test.tsx`
- Modify: `tests/unit/app/routers/test_workspace_router.py`
- Modify: `tests/unit/app/routers/test_runtime_config_targeting.py`
- Modify: `e2e/pages/runtime_config_page.py`
- Modify: `e2e/tests/test_runtime_config.py`

**接口：**

```ts
export function mergeRunningConfig(
  original: AgentsRunningConfig,
  formValues: Partial<AgentsRunningConfig>,
  approvalLevel: ToolExecutionLevel,
): AgentsRunningConfig;
```

- [ ] **Step 1：写配置合并失败测试**

覆盖未知字段保留、嵌套对象递归合并、数组完整替换、`max_iters` 与 `loop.iteration.max_iterations` 对齐以及 `approval_level` 写回；修改 Shell 或标题生成不能丢失记忆、上下文和循环字段。

- [ ] **Step 2：运行纯函数测试确认 RED**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- src/pages/Agent/Config/configMerge.test.ts
```

- [ ] **Step 3：提取最小配置合并纯函数**

对象递归合并，数组和标量采用表单值完整替换；服务端未知字段保留。保存成功后用服务端响应更新下一次合并基线。

- [ ] **Step 4：写即时保存失败恢复测试**

模拟语言、项目目录、编码和计划接口失败，断言页面恢复旧值、显示具体错误且不调用主表单保存；个人时区只更新当前用户且不携带治理上下文；主表单后续保存不覆盖独立配置。

- [ ] **Step 5：运行 Hook 与组件测试确认 RED**

```powershell
npm run test:run -- `
  src/pages/Agent/Config/useAgentConfig.test.tsx `
  src/pages/Agent/Config/components/ReactAgentCard.test.tsx
```

- [ ] **Step 6：实现即时保存状态与错误恢复**

每个即时设置保存旧值，请求失败后恢复并显示错误；语言保留确认弹窗，个人时区继续使用用户级接口。

- [ ] **Step 7：补后端无副作用校验测试**

覆盖 Shell 超时小于 1、非法语言及无编辑权项目目录/编码/计划写入，断言配置保存、版本递增、目录操作和 Agent reload 均未发生。

- [ ] **Step 8：运行后端测试并做最小修复**

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/app/routers/test_workspace_router.py" `
  "tests/unit/app/routers/test_runtime_config_targeting.py"
```

- [ ] **Step 9：扩展基础设置 Playwright 回归**

覆盖管理员普通路径、管理员代管、owner 和 user 只读；所有修改记录原值并在 `finally` 恢复。

- [ ] **Step 10：运行 Task 2 全部自动化测试**

执行 Step 2、Step 5、Step 8，再执行 `npx tsc -b --noEmit`。

- [ ] **Step 11：真实页面验收并停止**

逐项验证语言、Shell 超时、标题、计划、编码、项目目录的修改刷新回读；两个账号验证个人时区隔离；展示一个失败恢复路径，恢复测试值后等待确认。

---

### Task 4.5-B/3：LLM、上下文与工具执行配置保真

**可验收成果：** LLM 重试、限流、Light Context 和工具执行级别合法值完整往返，非法值不落盘，未展开字段不丢失。

**文件：**

- Modify: `console/src/pages/Agent/Config/components/LlmRetryCard.tsx`
- Create: `console/src/pages/Agent/Config/components/LlmRetryCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/LlmRateLimiterCard.tsx`
- Create: `console/src/pages/Agent/Config/components/LlmRateLimiterCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/LightContextCard.tsx`
- Modify: `console/src/pages/Agent/Config/components/LightContextCard.test.ts`
- Modify: `console/src/pages/Agent/Config/components/ToolExecutionLevelCard.tsx`
- Create: `console/src/pages/Agent/Config/components/ToolExecutionLevelCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/configMerge.test.ts`
- Create: `tests/unit/config/test_running_config_validation.py`
- Modify: `tests/unit/app/routers/test_workspace_router.py`
- Modify: `e2e/tests/test_runtime_config.py`

- [ ] **Step 1：写四组卡片字段与校验失败测试**

覆盖退避上限不得小于基础值、并发至少 1、QPM 至少 0、暂停至少 1、抖动至少 0、获取超时至少 10、上下文压缩比例关系、裁剪列表保留和工具执行级别枚举。

- [ ] **Step 2：运行前端测试确认 RED**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/pages/Agent/Config/components/LlmRetryCard.test.tsx `
  src/pages/Agent/Config/components/LlmRateLimiterCard.test.tsx `
  src/pages/Agent/Config/components/LightContextCard.test.ts `
  src/pages/Agent/Config/components/ToolExecutionLevelCard.test.tsx
```

- [ ] **Step 3：补齐最小前端校验**

规则与后端模型一致，不新增产品限制；动态字段使用稳定 Form 路径。

- [ ] **Step 4：写后端校验无副作用测试**

无效配置返回 4xx，`update_agent_config_async`、版本递增和 reload 均未调用；若现有 Pydantic 已满足则记录基线，不重复实现。

- [ ] **Step 5：写未展开字段保留测试**

只修改一个上下文字段，断言 Scroll、工具裁剪、视觉压缩和未知字段保持。

- [ ] **Step 6：运行 Task 3 全部自动化测试**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/pages/Agent/Config/components/LlmRetryCard.test.tsx `
  src/pages/Agent/Config/components/LlmRateLimiterCard.test.tsx `
  src/pages/Agent/Config/components/LightContextCard.test.ts `
  src/pages/Agent/Config/components/ToolExecutionLevelCard.test.tsx `
  src/pages/Agent/Config/configMerge.test.ts `
  src/pages/Agent/Config/useAgentConfig.test.tsx
npx tsc -b --noEmit

Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/config/test_running_config_validation.py" `
  "tests/unit/app/routers/test_workspace_router.py"
```

- [ ] **Step 7：真实页面验收并停止**

四个区域各验证合法保存刷新回读，并验证一个非法关系值不落盘；检查 Agent A/B 无串写，恢复测试值后等待确认。

---

### Task 4.5-B/4：记忆、ADBPG 与 Embedding 配置保真

**可验收成果：** ReMe Light、ADBPG 和 Embedding 切换与字段完整往返；验证、局部热更新、失败回滚和待重建状态明确。

**文件：**

- Modify: `console/src/pages/Agent/Config/components/ReMeLightMemoryCard.tsx`
- Modify: `console/src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/ADBPGConfigCard.tsx`
- Create: `console/src/pages/Agent/Config/components/ADBPGConfigCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/EmbeddingModelCard.tsx`
- Create: `console/src/pages/Agent/Config/components/EmbeddingModelCard.test.tsx`
- Modify: `console/src/pages/Agent/Config/components/useEmbeddingVerification.ts`
- Create: `console/src/pages/Agent/Config/components/useEmbeddingVerification.test.ts`
- Modify: `console/src/pages/Agent/Config/useReMeRuntimeStatus.ts`
- Create: `console/src/pages/Agent/Config/useReMeRuntimeStatus.test.ts`
- Modify: `tests/unit/config/test_memory_config.py`
- Modify: `tests/unit/agents/memory/test_reme_config.py`
- Modify: `tests/unit/app/routers/test_workspace_router.py`
- Modify: `e2e/tests/test_runtime_config.py`

- [ ] **Step 1：写记忆后端和字段往返失败测试**

覆盖 ReMe、ADBPG 可选对象初始化、密钥保留、自动搜索嵌套对象，以及切换后端再切回时字段不丢失。

- [ ] **Step 2：写独立请求目标失败测试**

Embedding 验证、运行状态与维护请求必须接收页面统一目标上下文；管理员代管不得读取当前侧边栏 Agent 状态。

- [ ] **Step 3：运行前端测试确认 RED**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx `
  src/pages/Agent/Config/components/ADBPGConfigCard.test.tsx `
  src/pages/Agent/Config/components/EmbeddingModelCard.test.tsx `
  src/pages/Agent/Config/components/useEmbeddingVerification.test.ts `
  src/pages/Agent/Config/useReMeRuntimeStatus.test.ts
```

- [ ] **Step 4：实现最小字段和上下文修复**

未配置 ADBPG 时使用后端模型默认结构；不得在多个组件复制不同默认值。

- [ ] **Step 5：扩展后端热更新和回滚测试**

明确验证保存、内存字段应用、Embedding 局部重载和 Agent 整体重载顺序；局部失败回滚同字段、保留无关并发修改、报告同字段冲突、回滚失败不继续整体 reload、`needs_reindex` 回读一致。

- [ ] **Step 6：运行 Task 4 全部自动化测试**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/pages/Agent/Config/components/ReMeLightMemoryCard.test.tsx `
  src/pages/Agent/Config/components/ADBPGConfigCard.test.tsx `
  src/pages/Agent/Config/components/EmbeddingModelCard.test.tsx `
  src/pages/Agent/Config/components/useEmbeddingVerification.test.ts `
  src/pages/Agent/Config/useReMeRuntimeStatus.test.ts
npx tsc -b --noEmit

Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/config/test_memory_config.py" `
  "tests/unit/agents/memory/test_reme_config.py" `
  "tests/unit/app/routers/test_workspace_router.py" `
  -k "memory or embedding or reindex or rollback"
```

- [ ] **Step 7：真实页面验收并停止**

验证 ReMe/ADBPG 切换、普通记忆字段、Embedding 合法与失败验证、`needs_reindex` 和失败回滚。不得声称完整记忆业务效果完成；恢复测试值后等待确认。

---

### Task 4.5-B/5：循环配置保真

**可验收成果：** 内置 Gate、Goal、Mission 和自定义循环模式在折叠、切换标签、保存和刷新后结构完整，非法参数不落盘。

**文件：**

- Modify: `console/src/pages/Agent/Config/components/AgentLoopCard.tsx`
- Modify: `console/src/pages/Agent/Config/components/AgentLoopCard.test.ts`
- Modify: `console/src/pages/Agent/Config/components/AgentLoopCard.render.test.tsx`
- Modify: `console/src/pages/Agent/Config/configMerge.test.ts`
- Create: `tests/unit/config/test_loop_config_roundtrip.py`
- Modify: `tests/unit/app/routers/test_workspace_router.py`
- Modify: `e2e/pages/runtime_config_page.py`
- Modify: `e2e/tests/test_runtime_config.py`

- [ ] **Step 1：写循环结构往返失败测试**

覆盖 iteration、doom loop stages、rubric、goal、mission、自定义模式元数据，以及 Gate 的 ID/type/enabled/params；数组顺序保持，删除 Gate 不残留旧索引。

- [ ] **Step 2：运行前端循环测试确认 RED**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- `
  src/pages/Agent/Config/components/AgentLoopCard.test.ts `
  src/pages/Agent/Config/components/AgentLoopCard.render.test.tsx `
  src/pages/Agent/Config/configMerge.test.ts
```

- [ ] **Step 3：修复最小表单注册与数组合并问题**

动态 Gate 使用稳定 NamePath；数组由当前表单结构完整替换，Gate 参数对象保留未编辑键；不重写产品交互。

- [ ] **Step 4：写后端模型 roundtrip 和无副作用测试**

合法结构 dump/load 等价；负预算、非法 Gate 类型、重复 ID 和越界阈值等无效结构不写文件、不增版本、不 reload。

- [ ] **Step 5：运行后端循环测试并最小修复**

运行 `test_loop_config_roundtrip.py` 与 workspace router 的 loop/custom_mode/gate 用例。

- [ ] **Step 6：扩展 Playwright 循环回归**

创建带两个不同 Gate 的临时自定义模式，保存、切换标签、刷新验证；删除一个 Gate 后确认旧值消失，最终恢复原配置。

- [ ] **Step 7：运行 Task 5 全部自动化测试**

执行前后端聚焦测试和 `npx tsc -b --noEmit`。

- [ ] **Step 8：真实页面验收并停止**

展示自定义模式保存前后结构和一个非法参数失败路径。不得声称循环运行效果完成；等待确认。

---

### Task 4.5-B/6：全角色、热重载与真实页面阶段回归

**可验收成果：** 全部卡片在 owner、collaborator、管理员普通路径、管理员代管和 user 只读路径下通过真实页面及直接 API 验收，完成 4.5-B 确认门。

**文件：**

- Modify: `e2e/pages/runtime_config_page.py`
- Modify: `e2e/tests/test_runtime_config.py`
- Create: `tests/isolation/test_runtime_config_card_access.py`
- Modify: `tests/integration/test_agent_config_revision.py`
- Modify: `docs/project-audit/17-运行配置卡片保真矩阵.md`
- Modify: `docs/project-audit/16-多用户架构分阶段实施计划.md`
- Create: `docs/superpowers/verification/2026-08-24-task-4-5-b-runtime-config-card-fidelity.md`

- [x] **Step 1：写全角色直接 API 失败测试**

覆盖主运行配置、语言、项目目录、编码能力、计划配置、Embedding 请求和 reload：owner/collaborator/显式治理成功；user、公用使用者、未显式治理管理员写入均返回 403，且配置快照、版本和运行时不变。

- [x] **Step 2：运行隔离与版本测试**

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/isolation/test_runtime_config_card_access.py" `
  "tests/integration/test_agent_config_revision.py"
```

- [x] **Step 3：补版本冲突、待重载和权限变化流程**

验证两个页面旧版本保存得到 409；保存成功但 reload 失败显示 `pending_reload`；重试成功切换 `applied`，重试失败保持待重载；页面打开后权限撤销时保存 403 并切到只读摘要。

- [x] **Step 4：运行完整前端测试、类型检查和构建**

```powershell
Set-Location "E:/git_project/QwenPaw/console"
npm run test:run -- src/api/modules/agent.test.ts src/api/modules/agentRequestContext.test.ts src/pages/Agent/Config
npx tsc -b --noEmit
npm run build
```

- [x] **Step 5：运行完整后端相关测试**

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src"
& ".venv/Scripts/python.exe" -m pytest -q `
  "tests/unit/app/routers/test_workspace_router.py" `
  "tests/unit/app/routers/test_runtime_config_targeting.py" `
  "tests/unit/config/test_running_config_validation.py" `
  "tests/unit/config/test_loop_config_roundtrip.py" `
  "tests/unit/config/test_memory_config.py" `
  "tests/unit/agents/memory/test_reme_config.py" `
  "tests/integration/test_agent_config_revision.py" `
  "tests/isolation/test_runtime_config_card_access.py"
```

- [x] **Step 6：运行真实浏览器逐卡片回归**

在隔离验收实例配置好 `QWENPAW_E2E_BASE_URL` 与隔离工作目录后执行：

```powershell
Set-Location "E:/git_project/QwenPaw"
$env:PYTHONPATH="src;e2e"
& ".venv/Scripts/python.exe" -m pytest -q `
  "e2e/tests/test_runtime_config.py" `
  -m "runtime_config" `
  --browser chromium
```

用例按五类主体执行，记录修改前值并在 `finally` 恢复，不保留测试配置、测试项目或测试 Agent。

- [x] **Step 7：人工检查文件与运行时证据**

每张卡片至少抽取一个字段，记录保存前后 API、目标 `agent.json`、另一个 Agent 未变化、配置版本和运行时状态；证明个人时区只影响用户账户。

- [x] **Step 8：更新矩阵和阶段清单**

只有证据齐全才标记 4.5-B 通过；Task 4.5-C 保持未完成。

- [x] **Step 9：编写验证报告并停止**

报告包含修改文件、卡片结果、角色矩阵、命令与通过数量、非阻塞警告、页面验收和恢复情况，明确未进入 4.5-C。等待用户确认后才继续下一阶段。

## 计划自检结果

- 六个任务分别对应设计中的六个用户确认门。
- 所有原运行配置卡片均已分配到明确任务。
- 管理员代管目标错位在 Task 1 优先解决，后续任务复用同一上下文。
- 主表单、即时保存、前端校验、后端校验、持久化、热重载和失败恢复均有测试步骤。
- 记忆与循环只验证配置层保真，综合运行效果留给 Task 4.5-C。
- 未包含数据库迁移、配置存储重构、Git 操作或无关重构。
