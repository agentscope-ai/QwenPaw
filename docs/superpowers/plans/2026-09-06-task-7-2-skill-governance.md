# Task 7.2 技能池与用户技能闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. 本任务用户禁止 git 提交、分支、工作树和清理，使用原目录及变更前快照生成独立 diff。

**Goal:** 在原技能系统实现按 Agent 授权、固定版本发布审核、独立副本脱离与显式更新的前后端闭环。

**Architecture:** 沿用根 migrations 中的技能表与文件内容体系；新增授权及快照字段。治理服务负责可信主体、PG 事务和不可变内容版本；原 SkillService/SkillPoolService 继续负责扫描、安装、manifest 保真和 reload，不复制业务实现。

**Tech Stack:** Python/FastAPI/PostgreSQL/SQLAlchemy，React/TypeScript，现有 pytest/vitest/Playwright。

## Global Constraints

- 原目录 E:/git_project/QwenPaw，原数据根 tmp/task-2-1-acceptance/working，端口 18089；不建工作树、不提交、不清理用户文件。
- 技能池按 Agent 授权；所有者和协作者可载入；仅使用者只能调用已启用技能。
- 新增授权规则不追溯禁用、删除现有已安装副本；撤销仅阻止后续载入、更新、恢复。
- 发布申请限 Agent 所有者，管理员审核固定快照；不得复制 Agent 私有配置和有效凭据到共享模板。
- 保留原技能、市场、ZIP/Hub、扫描、冲突预检、频道、启停、配置和标签行为；不扩展语音、应用、模型治理。
- 真实迁移已获授权，但仅主流程在测试、审查通过并备份后执行；实现者只用隔离测试库和临时测试目录，不接触真实服务、账号、技能、凭据。
- 文件编辑使用 apply_patch、UTF-8。测试先 RED 后 GREEN；独立审查后方可完成。

## Task 1: 治理持久化、不可变快照与管理/读取入口

**Files:** 新建 migrations/versions/0015_skill_governance.py；新建 src/qwenpaw/skills/{records,repository,snapshots,service,runtime}.py 和 __init__.py；新建 app/routers/skill_governance.py；必要修改 access/capabilities.py、access/service.py、app/routers/__init__.py、app/routers/skills.py；测试 tests/isolation/test_skill_pool_governance.py、tests/integration/test_skill_governance_repository.py、tests/unit/skills/test_snapshots.py。

**Interfaces:** 本任务定义并在报告锁定治理 DTO/API（供后续原页面消费）。GET /skill-catalog?agent_id=... 返回只有有效 Agent 授权的活动池版本安全目录；管理 API /skill-governance 下提供初始化预览/登记、条目状态、Agent 授权、发布申请列表及审批。Agent 所有者提交 /skill-governance/requests（agent_id,skill_name），管理员审批决定固定快照。原管理入口均复用同一服务端管理员权限，不只隐藏按钮；包括 /agents/{agentId}/skills 别名和流式导入任务。用户载入入口由 Task 2 接入，不允许旧入口直接绕过管理权限。

- [x] 写真实 HTTP 失败用例：普通用户管理请求 403 且池不变；跨 Agent 目录和伪造主体拒绝；只读目录不返回路径/配置/Secret；获取管理 DTO 需管理员。
- [x] 运行 `.venv/Scripts/python.exe -m pytest tests/isolation/test_skill_pool_governance.py -q --tb=short`，记录预期失败。
- [x] 基于既有四表添加 Agent 授权表（skill_id/agent_id 唯一、外键、enabled、操作者时间）；发布申请新增 snapshot_key/content_hash/必要来源及审批版本标识。新增迁移，不改旧 revision；适配既有数据库角色授权。
- [x] 实现快照：仅内部受控英文目录、全目录哈希、拒绝链接与越界、扫描通过后固定内容；版本同内容幂等，读取校验哈希，故障明确拒绝；不复制 workspace manifest/config/Secret。
- [x] PG 事务保证 grants、版本切换、审批及审计一致；重复批准不重复发布；源修改或删除不改变待审内容；旧无快照申请不能直接批准。
- [x] 写并执行真实隔离 PG 测试和临时目录测试：双角色授权、审批重复、源变化、禁用、校验失败、迁移升级、metadata 登记幂等不授权。仅使用 tests/fixtures/postgres.py，一次性 schema；凭据不输出。
- [x] 报告明确 routes/DTO/服务接口、异常码、旧路由集成边界、RED/GREEN 证据和独立 diff，完成 Task 1 审查。

```python
# 行为验收契约，HTTP fixtures 绑定真实测试目录/数据库，不能 mock 掉权限或持久化。
response = member_client.post('/api/skill-governance/import')
assert response.status_code == 403
assert snapshot_pool_files() == before
# 申请固定 A 内容，源改 B 后审批，发布快照仍为 A；重复审批只产生一个版本。
assert published_content == b'approved snapshot A'
assert version_count == 1
```

## Task 2: 载入、脱离、显式更新及恢复

**Files:** 修改 src/qwenpaw/agents/skill_system/{pool_service,workspace_service,store,sync}.py 中实际存在的对应模块；app/routers/skills.py、skills_stream.py；必要修改 agents/tools/load_skill.py；新增 skills/lifecycle.py；tests/integration/test_agent_skill_lifecycle.py、tests/isolation/test_skill_lifecycle_access.py。

**Interfaces:** 使用 Task 1 报告锁定的可信 Agent/版本解析，不自行解析 request actor。Agent 技能列表补充 source_pool_version_id、detached、update_available；提供显式 update/restore 动作，使用 expected_content_hash 检测确认后的变化。生命周期服务仅接受服务端已校验 Agent 与授权版本。

- [x] 写并观察失败：所有者/协作者有授权可载入、use-only 拒绝，伪造 workspace_id 拒绝，撤销后旧副本可运行但不能更新。
- [x] 接入授权载入和固定版本目录；拒绝走旧池目录或直接下载管理接口绕过；新技能默认启用、覆盖保留原运行配置，扫描失败保留旧内容。
- [x] 编辑实际内容设置 detached；仅改启停、频道、标签和 config 不脱离。整目录 hash 覆盖 scripts/references 变化，不能只看 SKILL.md。
- [x] 显式更新到获授权活动版本；恢复到已绑定来源版本也需当前授权。确认带 expected hash，冲突 409；恢复成功解除脱离，保留原运行状态。detached 禁止自动覆盖。
- [x] 广播及后台自动更新逐目标校验；无可信目标或状态不全时拒绝并报告，不能悄悄部分成功；复用已有扫描/快照回滚。
- [x] 验证仅使用者只发现/调用启用技能，保留原加载与聊天斜杠行为；不改通用文件工具。
- [x] `.venv/Scripts/python.exe -m pytest tests/integration/test_agent_skill_lifecycle.py tests/isolation/test_skill_lifecycle_access.py -q --tb=short`，报告真实副作用及原技能回归，独立审查。

```python
assert installed_manifest['enabled'] is False  # 覆盖前已停用
assert installed_manifest['channels'] == ['console']
assert modified_skill.detached is True
assert auto_update_result.skipped_detached == [skill_name]
assert restored_skill.detached is False
assert other_agent_skill_bytes == original_other_agent_bytes
```

## Task 3: 原页面治理和生命周期交互

**Files:** console/src/pages/Settings/SkillPool/{index,useSkillPool}.tsx 及独立 GovernancePanel；console/src/pages/Agent/Skills/{index,useSkillsPage}.tsx、components/PoolTransferModal.tsx 和来源操作组件；console/src/api/modules/skill.ts、api/types、locales/zh.json/en.json；对应 .test.tsx。

**Interfaces:** 精确使用 Task 1/2 最终报告的 API/DTO；不新建另一套技能页面。管理员授权、状态、审核固定版本；用户可载入目录与管理池完全分开。所有者申请发布，协作者不能申请，use-only 不显示写入口。

- [x] 先写组件失败测试：普通用户不见管理控件；授权目录载入；来源/脱离提示；显式更新/恢复确认；409 显示冲突且不丢旧状态。
- [x] 实现管理面板：初始化预览、登记、Agent 授权、发布申请审核；显示原版本与新版本，不默认全选/授权/审批。
- [x] 原技能列表显示来源、版本和脱离，替换普通用户直接上传池入口为所有者申请发布；保留原市场、导入和搜索。
- [x] 切账户/Agent 清理旧目录及待处理状态，丢弃旧异步响应，防止跨上下文写入。
- [x] 运行定向 vitest、TypeScript 检查；完整构建仅交付阶段一次；报告并独立审查。

```typescript
expect(screen.queryByRole('button', { name: '审核通过' })).not.toBeInTheDocument();
await user.click(screen.getByRole('button', { name: '恢复池版本' }));
expect(screen.getByRole('dialog')).toBeVisible();
// 确认前无写请求，确认后请求包含当前 Agent 和 expected_content_hash。
```

## Task 4: 集成审查、授权迁移与双角色验收

- [x] 全任务差异独立审查；一轮最终集中修复及限定复审，不以单测代替权限检查。
- [x] 主流程运行技能相关后端、前端回归和完整 npm run build，记录未覆盖及既有警告。
- [x] 确认原服务进程、原数据库 schema 与 migration head；备份原 schema，验证备份可读取，执行增量迁移；不改变原模型开关/授权。
- [x] 在原目录重启 18089 并确认登录可用。用 TASK72 测试技能验证管理员授权/审批、普通用户载入/脱离/恢复、无权账户拒绝；不改已有技能。
- [x] 更新验收报告，列实际功能、数据变化、端口、测试证据和限制；不自动推进 Task 7.3。

## 进度

- Task 1–4 已完成。最终代码、迁移、构建和真实浏览器验收证据见同目录 `2026-09-06-task-7-2-acceptance.md`；18089服务运行，schema为0015。原数据保真通过，未提交或创建分支。等待用户验收本纵向任务，不自动推进Task7.3。
