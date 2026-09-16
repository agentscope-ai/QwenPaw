# Task 13.3 Legacy 写入口清理验收报告

日期：2026-09-09  
范围：身份、会话运行映射、Cron、Inbox、Token、部署环境配置与领域仓库切换门。

## 结论

已切换领域的多用户生产路径不存在可复现的 Legacy 业务事实写入。Legacy 数据文件继续作为单用户模式的数据源和多用户迁移/归档来源保留；本任务没有删除文件、旧数据、数据库记录，也没有执行数据库结构变更。

## 最终存储边界

| 领域 | 多用户权威写入 | Legacy 状态 |
| --- | --- | --- |
| 身份与会话 | PostgreSQL users/user_sessions | auth.json 仅供只读迁移；禁止自动加密改写及显式保存 |
| 会话归属、标题、状态、模型、消息与 Run | PostgreSQL | chats.json 仅保留 Session 运行寻址投影；旧格式迁移在多用户模式禁止写入 |
| Cron 与执行历史 | PostgreSQL | jobs.json/jobs_history 只读归档；JSON 保存与格式迁移均有写门 |
| Inbox 与回执 | PostgreSQL | inbox_events.json 只读归档；文件写方法有写门 |
| Token 用量 | PostgreSQL usage_records | token_usage.json 只读归档；文件写方法有写门 |
| 部署环境配置 | SECRET_DIR/envs.json 加密文件 | 明确声明为部署级文件权威，不属于租户业务双写 |

## 实现

1. 在 `repository_provider.py` 增加统一 `assert_legacy_write_allowed()`；多用户模式或 PostgreSQL 模式调用 Legacy 业务写入时以稳定错误码 `legacy_write_blocked` 失败关闭。
2. 将写门接入 auth.json、Cron JSON/历史、Inbox JSON 和 token_usage.json 的底层写方法，防止上层分支遗漏后静默回退。
3. 多用户读取旧 auth.json 时不再触发明文到密文的文件改写；旧管理员迁移仍可只读解析。
4. 多用户工作区启动跳过 weixin→wechat、Cron mode 等旧文件迁移；直接调用迁移函数也会在生成备份或写临时文件前失败。
5. 明确 chats.json 是 Session 运行寻址投影，envs.json 是部署级加密文件权威，避免将允许的文件状态误判为业务双写。

## 验证证据

- 无双写、切换门和 Repository 组合：`34 passed`。
- 认证、会话、Cron、Inbox、Token、环境配置与迁移预览相关回归：`254 passed`。
- parity + isolation 广域回归（排除已记录的 Windows 检查点长路径文件）：`514 passed, 40 skipped`。
- Python compileall 与新增测试 Flake8：通过。
- Legacy 单用户写入、旧格式迁移和迁移只读扫描：通过。
- 多用户旧文件迁移源内容与备份目录不变：通过。
- 本地验收服务已加载写保护：`http://127.0.0.1:18089/` 返回 200，PID `49708`。

## 基线差异

广域回归另有 3 项 `test_route_manifest.py` 失败。实际路由比阶段 0 的旧 manifest 多出已在此前任务实现并验收的治理、附件等接口；失败不经过本任务修改的持久化路径。该基线清单将在 Task 13.4 最终报告中按当前已验收功能校准。

Task 13.3 已具备确认条件。下一项也是最后一项主任务：Task 13.4「最终发布验收报告」。
