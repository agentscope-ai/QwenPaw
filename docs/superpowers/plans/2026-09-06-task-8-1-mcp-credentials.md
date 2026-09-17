# Task 8.1 MCP 与凭据实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。以下为一个纵向任务的内部步骤；完成整体验收再交用户，不提交单独中间层。

**Goal:** 让原 MCP 页面、OAuth、工具调用和实际用户审批使用受权限保护的凭据与 PostgreSQL 配置事实。

**Architecture:** 复用五张现表、CredentialRecord、DriverCard 和 DriverManager；PG 保存事实，运行物化可重建，Legacy 使用文件 Adapter。原环境保持不变，先在隔离环境完成闭环。

**Tech Stack:** 仓库既有 Python、SQLAlchemy async/PostgreSQL、FastAPI、React/TypeScript、pytest/Vitest/Playwright；不安装核心依赖。

## 全局约束

- 已确认设计：`docs/superpowers/specs/2026-09-06-task-8-1-mcp-credential-design.md`。
- 不 git 提交、分支、worktree，不删除历史数据或备份。中文文档 UTF-8，代码注释沿用局部语言。
- 使用各子任务独立事前快照和差异，不以已有脏 HEAD 作为本任务基线。
- 原18089、原6项MCP和模型/频道凭据保持；迁移写入、事实来源切换等实际变更须在可审查结果完成后单独确认。
- 先记录失败测试再最小实现；每内部任务实施者自测后由独立审查者复核。共享文件不并行修改。

## 接口契约

保留原 MCP API 路径和基础字段，新增字段如下，后端/前端共用：

```typescript
type SecretAction = { action: "keep" | "delete" } | { action: "replace"; value: string };
type CredentialUpdates = { headers?: Record<string, SecretAction>; env?: Record<string, SecretAction> };
// MCPClientInfo 增量：
type GovernanceInfo = {
  credential_fields?: { headers: string[]; env: string[] };
  revision?: number;
  runtime_status?: string;
  runtime_error?: string | null;
  can_edit?: boolean;
};
// 编辑提交 credential_updates，普通 headers/env 不携带旧秘密。
// PG编辑提交 expected_revision；策略/白名单请求同样带 expected_revision。
// toggle/delete 使用 expected_revision 查询参数。
```

创建保留 headers/env 输入，新记录所有值入密文。读取时 headers/env 返回空映射，credential_fields 只包含已配置字段名。Legacy API 也不回读秘密，保留旧运行行为和创建兼容性。OAuth 弹窗完成消息携带 session_id/client_key/agent_id，前端校验同源、当前发起会话及身份，不把 Token 存入浏览器。

## Task 1：凭据、MCP 配置与运行时

**Files:** 新增 `drivers/credentials/postgres_store.py`、`app/mcp/postgres_repository.py`、必要的 scoped adapter/helper；修改 `drivers/credentials/store.py`、`app/driver_config_service.py`、`app/mcp/config_service.py`、`schemas.py`、`routers/mcp.py`、`drivers/adapters/mcp_binding.py`、`mcp_card_builder.py`、`app/workspace/service_factories.py`、必要的 `drivers/manager.py`/`app/agent_context.py`。测试放 `tests/parity/test_credential_store.py`、`tests/isolation/test_mcp_permissions.py` 与独立 PG 集成用例。

**Interfaces:** 消费既有 database_session、agent_database_id、ActorContext 和 CredentialRecord；产出上述安全 DTO、绑定解析及 OAuth 所需 PG 配置事务入口，具体 Python 签名在实现初期写入 task1-interface.md 通知 Task2。

- [ ] 记录现有 MCP/Driver 回归基线与事前文件快照。
- [ ] 写失败测试，证明秘密不回读、跨Agent引用拒绝、null/[]白名单不同、编辑冲突和撤销后解析失败。例如：
```python
assert response.json()["headers"] == {}
assert response.json()["credential_fields"]["headers"] == ["Authorization"]
assert stale_update.status_code == 409
assert denied_cross_agent.status_code in (403, 404)
```
- [ ] 实现 PG create/replace/revoke/status/bind 与内部 scoped resolve，事务涵盖凭据、绑定和修订。
- [ ] PG模式从数据库加载，DriverCard仅物化；多用户旧数据未切换时安全拒绝静默覆盖，保留明确迁移门。Legacy保持可用。
- [ ] 连接运行重载状态、安全 GET 和成员身份候选，不能读取私人会话名称。
- [ ] 运行针对性与真实 PG 回归，提交独立差异、测试和接口报告供审查。

## Task 2：OAuth 归属与回调

**Files:** 修改 `app/routers/mcp_oauth.py`；新增 `app/mcp/oauth_repository.py` 和独立隔离/集成测试。不得与Task1修改同一文件。

**Interfaces:** 消费Task1事务入口及既有 get_agent_for_request/身份仓储。PG mcp_oauth_sessions 保存 state_hash/initiated_by/status，PKCE留进程内；弹窗按上面契约反馈。

- [ ] 记录事前快照和现有OAuth基线。
- [ ] 写失败测试：成功后第二次回调拒绝；撤权、禁用用户、删除/替换Driver、过期均不保存Token。例如：
```python
assert second_callback.status_code >= 400
assert saved_tokens_after_revocation == saved_tokens_before_revocation
assert synthetic_secret not in callback.text
```
- [ ] 实现原子state消费、落盘前权限复核、事务Token绑定和固定安全错误；重启后未完成会话安全失效。
- [ ] 收紧弹窗消息来源、会话标识及失效语义，保留Legacy OAuth协议流程。
- [ ] 运行目标测试及OAuth原有集成，报告差异供独立审查。

## Task 3：原 MCP 页面闭环

**Files:** `console/src/api/types/mcp.ts`、`api/modules/mcp.ts`、`pages/Agent/MCP/` 及必要局部测试/文案；不修改后端。

**Interfaces:** 使用上面DTO；已有 API请求身份捕获方式用于Agent/账号范围。编辑时带 revision，凭据字段显式 keep/replace/delete。

- [ ] 记录前端基线和事前快照。
- [ ] 写失败测试覆盖原值不可回读、仅使用者不可编辑、切Agent迟到结果丢弃。例如：
```typescript
expect(updateBody.credential_updates.headers.Authorization).toEqual({ action: "keep" });
expect(updateBody.expected_revision).toBe(client.revision);
expect(screen.queryByRole("button", { name: /保存/ })).not.toBeInTheDocument();
```
- [ ] 原表单增加凭据状态与动作，保留JSON创建、白名单、策略和原卡片，运行未生效反馈可见。
- [ ] OAuth仅接受同源当前session结果；切Agent/账号/关闭清除草稿和迟到请求。
- [ ] 前端目标测试、类型检查与构建通过，提交差异供审查。

## Task 4：整体验收与迁移预览

**Files:** 本任务验收文档、`tmp/task81-*`隔离环境脚本、必要测试fixture；不写原业务数据。

- [ ] 各内部任务限定复审通过，实际检查PG提交/回滚与运行事件，修复整合问题。
- [ ] 独立PG、合成账户、本机MCP/OAuth协议服务，双账户浏览器演示CRUD、凭据保持/替换/撤销、OAuth、白名单、策略、实际调用审批及跨用户拒绝。
- [ ] 只读预览原6项MCP的归属、引用、哈希、冲突和拒绝项；保留模型/频道/Secret基线，不显示明文。
- [ ] 完成整体审查、最终限定修复、构建和原数据保真复核。
- [ ] 提交页面、API、DB、差异证据及具体原环境迁移预览，请用户确认实际数据写入/切换；未授权前不重启原环境为新事实来源。

## 自检

已覆盖凭据契约、配置/修订事务、运行物化、OAuth身份、原页面权限、审批事件、Legacy保真和原数据切换门。未增加独立凭据管理中心或跨进程PKCE恢复，不进入8.2。
