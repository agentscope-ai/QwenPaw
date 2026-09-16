# 管理员默认 Agent 旧产物恢复

## 原因

当前产物面板只查询 user_agent_artifacts。核查时该表为空，而默认 Agent 旧 artifacts 目录仍保留 AI概览.md 和爱护环境.md。因此是旧产物未登记导致不可见，不是这两个文件被删除。

## 本次处理

- 使用既有启动脚本恢复 127.0.0.1:18089，工作目录保持 tmp/task-2-1-acceptance/working。
- 定向复制这两个用户确认归属管理员的历史文件，经 ArtifactService 登记为管理员 default Agent 私有产物。
- 原目录、原文件不删除、不移动，不扫描并批量公开其他历史文件。
- 私有副本位于 user_workspaces/b9bc4468-0626-4363-98d1-2fad14291469/default/artifacts。
- 恢复脚本 tmp/restore_admin_legacy_artifacts.py 重复运行不重复登记。

## 验证

- 恢复前数据库产物记录 0 条；恢复后管理员真实登录接口返回两个文件，下载均 HTTP 200。
- 两份副本与源文件逐字节一致。
- 重跑恢复脚本，两条 ID 保持不变。
- 普通用户 task42-user 同一 default Agent 的产物列表仍为 0，不暴露管理员文件。
- 登录页 HTTP 200。服务停止的确切触发原因尚未确认；末尾有上游模型 503 错误，但不足以证明这是进程停止原因。

本次为历史数据补登记，无数据库结构调整或应用代码变更。用户应刷新文件页，选择默认 Agent → 产物进行验收。
