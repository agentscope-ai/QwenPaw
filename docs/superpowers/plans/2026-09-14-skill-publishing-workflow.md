# 技能池发布与审核工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为管理员提供明确的技能直接发布入口，将技能列表、已发布技能和发布申请拆分为三个标签页，并让普通用户申请与管理员审核形成可理解、可验证的完整流程。

**Architecture:** 保留现有 PostgreSQL 发布版本、逐智能体授权和不可变申请快照模型。前端在技能池根页面控制三个标签页，将现有治理大组件拆成发布版本与申请审核两个单一职责组件；管理员单技能发布复用现有 preview/import 接口，后端只补充申请列表所需的申请人和智能体展示信息。

**Tech Stack:** React 18、TypeScript、Ant Design、Vitest、FastAPI、SQLAlchemy、PostgreSQL、pytest。

## Global Constraints

- 管理员直接发布，不经过二次管理员审核。
- 普通用户只能从自己拥有的智能体提交私有技能申请。
- 技能列表、已发布技能、发布申请必须是三个一级标签页。
- 已处理申请只读展示结果，不显示灰色审核按钮。
- 广播继续自动发布当前版本、授权并安装。
- 不新增数据库表，不实现多级审批、定时发布、版本回滚或版本差异比较。
- 所有界面文案同时维护简体中文和英文；文件使用 UTF-8。
- 按用户指示不创建分支、不执行 `git commit` 或 `git push`。

---

### Task 1: 丰富发布申请列表数据

**Files:**
- Modify: `src/qwenpaw/skills/repository.py`
- Modify: `console/src/api/types/skillGovernance.ts`
- Test: `tests/integration/test_skill_governance_repository.py`

**Interfaces:**
- Produces: `SkillPublicationRequest` 增加 `applicant_name`、`agent_id`、`agent_name`；`list_requests()` 按待审核优先、创建时间倒序返回。

- [x] **Step 1: 写失败的仓储集成测试**

在已有申请测试中断言普通用户提交后，管理员列表能读到申请人用户名和 Agent 名称，并断言 pending 排在 approved/rejected 前面。

- [x] **Step 2: 运行目标测试确认失败**

Run: `pytest tests/integration/test_skill_governance_repository.py -q`

- [x] **Step 3: 实现查询联表和类型字段**

`list_requests()` 联结 `agent_skills`、`agents`、`users`，用 `COALESCE(users.display_name, users.username)` 返回申请人名称，用 Agent 稳定键映射展示名称；排序使用 `CASE WHEN status='pending' THEN 0 ELSE 1 END, created_at DESC`。

- [x] **Step 4: 运行测试确认通过**

Run: `pytest tests/integration/test_skill_governance_repository.py -q`

### Task 2: 拆分发布版本与申请审核组件

**Files:**
- Create: `console/src/pages/Settings/SkillPool/PublishedSkillsPanel.tsx`
- Create: `console/src/pages/Settings/SkillPool/PublicationRequestsPanel.tsx`
- Modify: `console/src/pages/Settings/SkillPool/GovernancePanel.tsx`
- Modify: `console/src/pages/Settings/SkillPool/GovernancePanel.test.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Produces: `GovernancePanel` 接受 `view: "published" | "requests"`，每个视图只呈现对应功能。
- Consumes: Task 1 的申请展示字段。

- [x] **Step 1: 写失败的标签内容与审核状态测试**

覆盖：发布视图只显示版本与授权；申请视图只显示申请；待审核行按钮为“审核”；已处理行按钮为“查看详情”；已处理详情不渲染通过/拒绝按钮；待审核详情加载快照后按钮可用。

- [x] **Step 2: 运行目标测试确认失败**

Run: `npm test -- --run src/pages/Settings/SkillPool/GovernancePanel.test.tsx`

- [x] **Step 3: 拆分组件并实现状态展示**

`PublishedSkillsPanel` 负责版本列表、启停和 Agent 授权；`PublicationRequestsPanel` 负责状态筛选、详情、文件读取和审核。申请状态使用本地化标签；已处理详情页展示审核人、审核时间和备注，footer 仅保留关闭按钮。

- [x] **Step 4: 运行目标测试确认通过**

Run: `npm test -- --run src/pages/Settings/SkillPool/GovernancePanel.test.tsx`

### Task 3: 增加管理员单技能直接发布

**Files:**
- Modify: `console/src/pages/Settings/SkillPool/useSkillPool.tsx`
- Modify: `console/src/pages/Settings/SkillPool/components/PoolSkillCard.tsx`
- Modify: `console/src/pages/Settings/SkillPool/components/PoolSkillListItem.tsx`
- Modify: `console/src/pages/Settings/SkillPool/useSkillPool.governance.test.tsx`
- Create: `console/src/pages/Settings/SkillPool/components/PoolSkillPublishActions.test.tsx`

**Interfaces:**
- Produces: `publicationState(name): "unpublished" | "outdated" | "current"`；`handlePublish(skill): Promise<void>`。
- Consumes: `createSkillGovernanceApi(scope).preview()`, `.items()`, `.register()`。

- [x] **Step 1: 写失败的发布状态和直接发布测试**

覆盖未发布显示“发布”、内容变化显示“发布新版本”、哈希一致显示“已是最新版本”，并断言确认发布只把所选技能的名称与精确哈希发送到 initialization/import。

- [x] **Step 2: 运行目标测试确认失败**

Run: `npm test -- --run src/pages/Settings/SkillPool/useSkillPool.governance.test.tsx src/pages/Settings/SkillPool/components/PoolSkillPublishActions.test.tsx`

- [x] **Step 3: 实现最小发布状态与动作**

刷新技能池时并行读取模板预览和已发布版本，按名称与内容哈希计算状态。发布时重新 preview、弹出包含技能名和哈希的确认框、register 单个技能、刷新治理和技能池数据；哈希已一致时不写入。

- [x] **Step 4: 运行目标测试确认通过**

Run: `npm test -- --run src/pages/Settings/SkillPool/useSkillPool.governance.test.tsx src/pages/Settings/SkillPool/components/PoolSkillPublishActions.test.tsx`

### Task 4: 技能池根页面改为三个标签页

**Files:**
- Modify: `console/src/pages/Settings/SkillPool/index.tsx`
- Modify: `console/src/pages/Settings/SkillPool/index.module.less`
- Create: `console/src/pages/Settings/SkillPool/index.tabs.test.tsx`

**Interfaces:**
- Consumes: `GovernancePanel view`、`handlePublish` 和 `publicationState`。
- Produces: URL 查询参数 `tab=skills|published|requests`，默认 `skills`。

- [x] **Step 1: 写失败的三个标签页测试**

断言三个标签存在；默认只显示技能模板；切换后只挂载对应治理视图；刷新时从 `tab` 查询参数恢复当前页；技能编辑工具栏只在技能列表显示。

- [x] **Step 2: 运行目标测试确认失败**

Run: `npm test -- --run src/pages/Settings/SkillPool/index.tabs.test.tsx`

- [x] **Step 3: 实现受控 Tabs 与条件内容**

PageHeader 下方添加 Ant Design `Tabs`。技能列表标签包含原有工具栏、卡片/列表、抽屉和导入弹窗；已发布技能与发布申请分别挂载对应治理视图。切换时只更新 `tab`，保留 `view=market` 的现有行为。

- [x] **Step 4: 运行目标测试确认通过**

Run: `npm test -- --run src/pages/Settings/SkillPool/index.tabs.test.tsx`

### Task 5: 明确普通用户申请入口并完成回归验收

**Files:**
- Modify: `console/src/pages/Agent/Skills/components/HeaderActions.tsx`
- Modify: `console/src/pages/Agent/Skills/components/PoolTransferModal.tsx`
- Modify: `console/src/pages/Agent/Skills/index.governance.test.tsx`
- Modify: `console/src/locales/zh.json`
- Modify: `console/src/locales/en.json`

**Interfaces:**
- Consumes: 现有 `scope.canSubmit` 和 `governance.submit(name)`。

- [x] **Step 1: 补充申请入口权限与说明测试**

断言 owner 看见“申请发布”和用途说明，只能选择无发布来源的私有技能；collaborator/user 看不到入口；提交成功保留现有不可变快照请求行为。

- [x] **Step 2: 运行目标测试确认失败或暴露缺口**

Run: `npm test -- --run src/pages/Agent/Skills/index.governance.test.tsx`

- [x] **Step 3: 补足文案和交互**

将入口 tooltip 与弹窗说明明确为“将当前私有技能的固定快照提交给管理员审核”；没有可申请技能时显示原因，不改变现有 owner-only 权限判断。

- [x] **Step 4: 运行前后端相关测试和生产构建**

Run:

```powershell
pytest tests/integration/test_skill_governance_repository.py tests/isolation/test_skill_pool_governance.py -q
Set-Location "console"
npm test -- --run src/pages/Settings/SkillPool/GovernancePanel.test.tsx src/pages/Settings/SkillPool/useSkillPool.governance.test.tsx src/pages/Settings/SkillPool/index.tabs.test.tsx src/pages/Agent/Skills/index.governance.test.tsx
npm run build
```

- [x] **Step 5: 重启并进行浏览器验收**

重启 `18089` 服务后以管理员和普通用户分别验证：管理员直接发布、三个标签页、待审核操作、历史结果只读、普通用户提交申请、审核通过后出现在已发布技能。确认 `/api/auth/status` 返回 `mode=multi_user`。
