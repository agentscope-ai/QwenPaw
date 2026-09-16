# Task 4.5-B/6 全角色、热重载与真实页面阶段回归报告

日期：2026-08-24  
状态：实现与验证完成，等待用户验收；未进入 Task 4.5-C。

## 本任务完成内容

- 新增运行配置全角色隔离测试，覆盖 owner、collaborator、仅使用者、历史 owner、管理员普通路径和显式代管路径。
- 补齐页面打开后编辑权限被撤销的处理：保存收到 403 后重新读取权限，切换为只读摘要或错误态，不继续保留编辑能力。
- 补齐 reload 重试失败仍保持 `pending_reload` 的前端回归。
- 汇总版本冲突、保存后待重载、重试成功/失败、权限变化和 PostgreSQL 修订证据。
- 对真实多用户验收实例执行 owner、管理员显式代管、管理员普通路径、平台公用仅使用者和无授权用户回归；未修改成员关系。

## 角色与权限结果

| 场景 | 结果 |
|---|---|
| owner 普通路径 | 完整配置、版本和运行态可读，`access_role=owner` |
| collaborator | 隔离测试中完整读写成功 |
| 管理员自己的 Agent | 使用普通 owner 路径，不附加治理标记 |
| 管理员代管他人 Agent | 必须携带 `X-Agent-Governance: runtime-config`；完整配置、版本和运行态可读 |
| 管理员普通路径访问他人非公用 Agent | access、摘要、完整配置、写入和 reload 均为 403 |
| 平台公用仅使用者 | 安全摘要 200；完整配置、写入和 reload 均为 403 |
| 无授权普通用户 | access、摘要、完整配置、写入和 reload 均为 403 |

前端隐藏不是安全边界；所有拒绝均由后端接口再次强制执行，并验证拒绝后配置文件、版本和运行态不发生变化。

## 自动化命令与结果

```text
npm run test:run -- src/api/modules/agent.test.ts src/api/modules/agentRequestContext.test.ts src/pages/Agent/Config
24 files passed, 113 tests passed

npx tsc -b --noEmit
passed

npm run build
passed; Monaco CSS verification passed

pytest workspace/targeting/validation/loop/memory/revision/isolation suites
103 passed, 1 warning
```

PostgreSQL 修订测试连接 `qwenpaw-pg` 的隔离数据库 `qwenpaw_test_migrations`，不是生产数据库。

## 真实页面与持久化证据

- owner：完整配置 23 个顶层字段，配置版本 4，运行态 `applied`。
- 管理员显式代管：完整配置 23 个顶层字段，配置版本 3，运行态 `applied`。
- 平台公用仅使用者：页面只显示只读摘要；完整配置、写入和 reload 直接调用均为 403。
- 管理员普通路径和无授权普通用户：所有运行配置入口直接调用均为 403。
- 目标 Agent 与对照 Agent 的 `agent.json` 在验收前后 SHA-256 一致，没有残留测试配置、项目或 Agent。
- 管理员和普通用户的个人时区均从各自 `/api/me` 偏好读取，以不同用户 ID 隔离；没有写入 Agent 配置。

截图：

- `tmp/task-2-1-acceptance/task-4-5-b6-admin-governance.png`
- `tmp/task-2-1-acceptance/task-4-5-b6-owner.png`
- `tmp/task-2-1-acceptance/task-4-5-b6-public-readonly.png`

## 非阻塞警告与已知约束

- Starlette 报告 `TestClient/httpx` 弃用警告，不影响用例结果。
- Windows Python 在 PostgreSQL 集成测试结束阶段输出一次解释器退出访问冲突信息，但 pytest 返回码为 0，103 个用例全部通过。
- 真实验收库对“与历史修订完全相同的内容”再次保存会命中既有内容哈希唯一约束并返回 500。B/6 因此不制造重复快照；B/2 至 B/5 已提供真实逐卡片保存与恢复证据，B/6 的写入、409 和重载状态使用隔离测试验证。该约束应作为后续独立缺陷处理，不在本任务扩展数据库设计。

## 确认门

Task 4.5-B/6 已完成，Task 4.5-B 的运行配置卡片保真证据闭合。当前停止，等待用户确认；未开始 Task 4.5-C 的记忆与循环综合运行效果验收。
