# Task 11.4 平台一致性备份和恢复编排验收记录

## 结论

Task 11.4 已完成技术验收，等待用户确认。平台备份现在同时覆盖 PostgreSQL 和文件数据；恢复必须经过服务端影响预览，并由服务端强制创建恢复前保护备份。

## 实现范围

- 每个新备份追加 `platform/manifest.json`，记录数据库、workspace、内容存储和 Secret Store 版本；不暴露 Secret 值。
- 多用户数据库在 repeatable-read 只读事务中按表写入 JSONL，记录行数和 SHA-256，修改归档后重新签名。
- 数据库恢复先校验表集合和内容哈希，再由表所有者在单事务内临时停用约束触发器、整组替换并恢复触发器，支持真实 schema 的循环外键；任一步失败则整笔回滚。
- 所有备份路由统一要求平台设置管理能力，普通用户服务端返回 403。
- `POST /api/backups/{id}/restore/preview` 返回影响组件、Agent、归档清单和 10 分钟一次性 token；token 绑定管理员、备份 ID 与完整恢复请求。
- 恢复写入前自动创建包含数据库和文件的签名保护备份；文件阶段失败时自动回滚数据库和文件。
- 前端先展示服务端返回的实际影响清单，再允许第二次确认；移除可绕过保护备份的旧选项。

## 验证证据

- 后端备份组合：`51 passed, 1 skipped`；专用 PostgreSQL 隔离 schema 的父子表及完整迁移 schema 循环外键往返 `2 passed`。
- 前端备份组合：`54 passed`；流程收敛后相关页面 `33 passed`。
- TypeScript、Prettier、Python 编译、目标 diff 检查通过。
- 生产构建两次通过，18,889 个模块构建成功，Monaco CSS 校验通过；仅有仓库既有 chunk 提示。
- 既有 Legacy API 集成测试 `11 passed`，确认多用户确认门没有破坏 Legacy 行为。

## 页面验收与数据影响

- 管理员创建仅含全局设置的测试备份，归档成功后恢复预览显示 `database, global_config, content_store`，涉及 0 个 Agent；随后取消，没有执行恢复。
- 普通用户设置菜单无“备份”，直接访问 `/backups` 返回 403。
- 截图：`tmp/task-11-4-restore-impact-preview.png`、`tmp/task-11-4-member-backup-forbidden.png`。
- 测试备份已通过页面删除，备份目录除本地签名密钥外无测试归档；浏览器已关闭。
- 18089 当前为多用户模式，PID `6968`，认证状态接口 HTTP 200。

## 下一确认门

用户确认后进入 Task 11.5「Agent 可移植导出/导入」。本次没有对现有环境执行真实恢复；以后任何真实恢复仍需要针对影响清单取得明确危险操作确认。
