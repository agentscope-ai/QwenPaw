# 多用户部署运行 Implementation Plan

> **For agentic workers:** 使用 executing-plans 在当前任务内实施。用户已确认设计；不创建分支或提交。

**Goal:** 交付正式 service 命令、部署配置、运行手册及本机接管验收。

**Architecture:** 配置解析和进程管理放在独立 service 包；CLI 只负责参数与输出。子进程在导入应用前接收实例环境，复用现有数据库校验、迁移和应用。

**Tech Stack:** Python 标准库、现有 Click/psutil/SQLAlchemy/Alembic；Windows 和 Linux。

## Global Constraints

- 当前实例数据不批量更新、不移动、不删除；配置文件被 Git 忽略。
- 不自动安装自启动、不自动升级数据库、不提交代码。
- 新命令不使用 tmp 脚本或 Codex Git 路径。

### Task 1：配置和进程身份

- [x] 新建 tests/unit/service/test_service.py，覆盖相对路径解析、错误配置脱敏、拒绝复用 PID、重复启动与冲突。
- [x] 执行 `.venv/Scripts/python.exe -m pytest tests/unit/service/test_service.py -q`，确认新增测试失败。
- [x] 新建 src/qwenpaw/service/config.py 和 manager.py：ServiceConfig.load(path)、child_env()、process_identity()、start/stop/status，锁保护进程状态操作，身份包含 PID、创建时间及命令行。
- [x] 执行同一测试命令，修复至通过。

### Task 2：CLI 和受控运行进程

- [x] 新建 worker.py，复用 validate_runtime_cutover；使用 Uvicorn 正常退出机制响应实例停止文件。
- [x] 新建 cli/service_cmd.py，注册 init/check/run/start/stop/restart/status/logs/exec/database-upgrade；迁移仅在显式调用时执行。
- [x] 检查帮助、异常退出码和日志，不输出 DSN；真实进程测试启动、重复启动、停止和重启。

### Task 3：正式部署文件和说明

- [x] deploy/service.example.json、Windows 自启动及 Linux systemd 模板、源码构建多用户 Compose 配置。
- [x] docs/deployment.md 覆盖新安装、管理员引导、现有实例接管、备份恢复、迁移边界和故障诊断；README 链接文档。
- [x] 生成 deploy/service.local.json 接管现有数据配置，凭据不输出、不提交。

### Task 4：验收

- [x] 本机 check/start/status/restart/logs 实测，检查健康、身份模式和数据库。
- [x] 新 schema 的初始化和重复升级使用隔离库测试；不操作现有数据。
- [x] 检查模板语法，注明 Linux 和 Windows 托管未安装的验证边界。
- [x] 更新计划和验收结果，给出用户可直接执行的命令。
