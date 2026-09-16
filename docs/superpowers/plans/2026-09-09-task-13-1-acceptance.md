# Task 13.1 全角色逐页验收记录

验收日期：2026-09-09  
验收实例：`http://127.0.0.1:18089`  
数据库 Schema：`qwenpaw_task21_acceptance` / `0018_automation_authorization`

## 验收范围

- 管理员普通路径、管理员显式代操作、owner、collaborator、user、未授权六类主体。
- 匿名上下文补充验证 Chat、智能体管理和用户管理登录重定向。
- 列表、详情、创建、编辑、删除、批量归档/反归档/删除、上传下载、SSE、审批列表和失败回滚。
- 每页截图、API 请求 ID、数据库 owner/成员/会话/审计证据。

ACP 产品页面已在 Task 12.4 按产品决策退役，不属于本轮页面矩阵。

## 浏览器与 API 结果

使用一个系统 Chrome 进程创建四个隔离上下文。最终报告：

- 页面检查：80 个，80 张截图均非空，最小文件 61,242 字节。
- 主体分布：管理员普通路径 29、管理员代操作 2、owner 16、collaborator 16、user 10、未授权 4、匿名 3。
- API 请求：37 个；状态分布为 200×30、201×1、403×3、404×2、409×1，均为预期状态。
- 临时 Agent：`task131-20260909-010149`。
- 上传冲突返回 409，随后下载内容仍等于首次上传内容。
- Runtime Status SSE 首事件为 `connected`。
- 不存在的审批请求按当前用户安全返回 404。
- user 读取完整 Agent 配置返回 403；撤销后 Agent 详情和会话列表返回 403。

最终报告和截图目录：

- `tmp/task-13-1-20260909-010149/report.json`
- `tmp/task-13-1-20260909-010149/screenshots/`

报告不包含明文密码或访问令牌。

## 验收发现与修复

首次完整运行发现：批量删除 API 返回成功，但 PostgreSQL `conversations.status` 仍为 `active`。根因是创建路径使用回调同步 PostgreSQL，而 `ChatManager.delete_chats()` 只删除 JSON ChatSpec，没有对应的权威状态同步。

修复保持现有双层兼容结构：

- `ChatManager` 新增 `on_chats_deleted` 回调，在删除 JSON 记录前调用。
- 多用户工作区回调以会话 owner 绑定 PostgreSQL repository，将 conversation 更新为 `deleted` 并写入 `deleted_at`。
- PostgreSQL 同步失败时抛出错误并保留 JSON ChatSpec，避免兼容索引先删除造成半完成状态。
- 复用已有 ChatManager 时同步刷新删除回调。
- E2E 在清理后强制断言 Agent 和所有临时 conversation 均为 `deleted`。

TDD 证据：新增测试首先以 `unexpected keyword argument 'on_chats_deleted'` 失败；实现后两个删除同步/失败保留测试通过。

## 数据库证据与清理

清理前：

- Agent owner 为 `task42-user`，状态 `active`，可见性 `private`。
- `task62-user-b` 先后经过 collaborator、user 并留下撤销时间。
- 两条会话 owner 均为 `task42-user`，清理前状态 `active`。
- 关联审计日志 5 条，保存了请求 ID 和脱敏明细。

清理后：

- 临时 Agent 状态为 `deleted`。
- 两条临时 conversation 状态均为 `deleted`。
- 所有 Task 13.1 失败运行遗留的已删除 Agent 会话均已按标题、owner 和 Agent 状态三重条件清理。
- 活动 Task 13.1 临时 Agent 数为 0，已删除 Agent 下的活动 Task 13.1 会话数为 0。

## 自动化验证

- ChatManager、会话访问和会话模型：33 passed。
- 会话管理、审批、自动化路由、运行配置和 ACP 退役相关回归：54 passed，3 条既存 OpenAPI duplicate operation ID 警告。
- Python 编译、`git diff --check`：通过。
- 最终 E2E 报告状态：`passed`。

## 结论

Task 13.1 验收通过。没有执行数据库结构迁移或 Git 提交。下一项为 Task 13.2「越权与敏感信息专项测试」。
