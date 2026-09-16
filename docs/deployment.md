# 多用户平台部署与运行手册

适用于本仓库包含多用户重构的源码版本。正式运行入口为 `qwenpaw service`，复用现有应用；不依赖 `tmp/start-18089.ps1`。旧 `qwenpaw app` 仍是前台启动入口，但不会自动加载 service 实例配置。`qwenpaw daemon restart` 不是操作系统服务重启命令。

## 1. 当前机器：直接运行

在项目根目录打开 PowerShell。当前机器已经配置 `deploy/service.local.json`，指向原多用户数据库和账号。

```powershell
cd "E:/git_project/QwenPaw"
docker start qwenpaw-pg
& ".venv/Scripts/python.exe" -m qwenpaw service check
& ".venv/Scripts/python.exe" -m qwenpaw service start
```

访问 [控制台](http://127.0.0.1:18089)。账号见本机 `docs/accoun.md`。`start` 返回 `ready` 才表示核心智能体和数据库已就绪；启动器退出后服务继续在后台运行。

```powershell
# 状态检查；ready 为成功，未运行或不健康时返回非零退出码
& ".venv/Scripts/python.exe" -m qwenpaw service status
# 正常停止
& ".venv/Scripts/python.exe" -m qwenpaw service stop
# 重启并加载新配置/新前端资源
& ".venv/Scripts/python.exe" -m qwenpaw service restart
# 最后 100 行日志
& ".venv/Scripts/python.exe" -m qwenpaw service logs --lines 100
# 持续日志，Ctrl+C 只退出日志查看
& ".venv/Scripts/python.exe" -m qwenpaw service logs --follow
```

激活虚拟环境后可直接使用 `qwenpaw service start` 等短命令。配置路径参数位于操作前，例如 `qwenpaw service --config "D:/QwenPaw/service.json" start`。

当前布局：

| 内容 | 当前位置 |
|---|---|
| 正式 CLI | `src/qwenpaw/cli/service_cmd.py` |
| 实例私有配置 | `deploy/service.local.json`（Git 忽略） |
| 启动日志 | `data/logs/service.log` |
| PID、锁和就绪状态 | `data/run/` |
| 原工作区、密钥、备份 | `tmp/task-2-1-acceptance/` |
| 数据库 / schema | `qwenpaw_test_migrations` / `qwenpaw_task21_acceptance` |

**本次为正式入口接管，原业务数据尚未迁出 tmp。请勿清理该目录。** 新安装应使用持久目录，旧实例迁移见第 8 节。

## 2. 命令行为

| 命令 | 作用 |
|---|---|
| `service init` | 仅生成配置，已存在则拒绝覆盖 |
| `service check` | 检查 Git、工作配置、前端、数据库和 schema、领域切换条件 |
| `service start` | 后台启动并等待就绪；重复调用复用同一进程 |
| `service run` | 前台运行，供调试、systemd 或任务计划程序托管 |
| `service status` | 校验真实进程身份、最近就绪心跳，并重新检查数据库 |
| `service stop` | 通过受控退出机制正常关闭 |
| `service stop --force` | 正常关闭超时后强制终止已核验进程 |
| `service restart` | 正常停止，然后启动；停止失败不继续启动 |
| `service logs` | 查看后台 start 的启动日志；run 日志输出到前台/托管日志 |
| `service exec init` | 在指定实例环境运行原有初始化命令 |
| `service database-upgrade --yes` | 停服后显式执行现有 Alembic 升级 |

启动失败、配置无效和端口占用返回非零。就绪超时保留进程供诊断；查看日志或 stop 后重试。控制文件使用 PID、进程创建时间和命令行核验；不要手工修改 PID 文件。每个实例必须有独立的端口、state_dir、工作区和数据库目标。

## 3. 全新源码安装

依赖：Python 3.11–3.13、Node.js/npm、Git、PostgreSQL；Windows 可使用 Docker Desktop 运行 PostgreSQL。实际需要的浏览器、PDF、图片等工具按智能体技能另行安装，启动平台不等于所有外部工具都已可用。

在可信源码目录执行，使用独立虚拟环境：

```powershell
python -m venv ".venv"
& ".venv/Scripts/python.exe" -m pip install -e .
Push-Location "console"
npm install
npm run build
Pop-Location
& ".venv/Scripts/python.exe" -m qwenpaw service --config "C:/ProgramData/QwenPaw/config/service.json" init
```

Linux 对应解释器是 `.venv/bin/python`。有经过团队维护的 npm 锁文件时使用 `npm ci`；当前仓库忽略 console 的 package-lock.json，因此首次无锁安装尚不能保证依赖逐字节可复现。上线应保留验证过的构建产物和镜像摘要。

编辑生成的 JSON 配置。相对目录以**配置文件所在目录**为基准；python 建议使用该项目虚拟环境解释器绝对路径。模板不写入可用密码，必须填写自己的数据库凭据。

配置中的 environment 值必须为字符串，可使用 `${变量名}` 引用启动终端或托管环境中的变量，未定义变量会导致配置加载失败。配置不继承终端残留的 QWENPAW/COPAW 实例变量；所需实例设置必须显式写入配置。

敏感配置不要提交到仓库。Linux 文件权限设为 600；Windows 将实例配置、secrets 和运行控制目录限制为运行服务的账户可访问。新安装不要复制本机验收账号密码。

### 3.1 正式目录配置规范

正式部署将代码与运行数据分开存放。同一个磁盘可以使用两个独立目录，无需强制分盘；不要将持久数据放进源码目录、虚拟环境或 tmp。更新/替换代码时保留数据目录。

| 配置字段 | 含义 | Windows 示例 | Linux 示例 |
|---|---|---|---|
| `project_dir` | 源码、前端构建和迁移脚本 | `D:/Apps/QwenPaw` | `/opt/qwenpaw` |
| `python` | 安装本项目的解释器 | `D:/Apps/QwenPaw/.venv/Scripts/python.exe` | `/opt/qwenpaw/.venv/bin/python` |
| 配置文件位置（`--config`） | 私有实例配置 | `C:/ProgramData/QwenPaw/config/service.json` | `/etc/qwenpaw/service.json` |
| `working_dir` | 工作配置、智能体工作区及文件 | `C:/ProgramData/QwenPaw/working` | `/var/lib/qwenpaw/working` |
| `secret_dir` | 密钥及凭据文件 | `C:/ProgramData/QwenPaw/secrets` | `/var/lib/qwenpaw/secrets` |
| `backup_dir` | 应用备份目录 | `C:/ProgramData/QwenPaw/backups` | `/var/lib/qwenpaw/backups` |
| `state_dir` | PID、锁和就绪状态 | `C:/ProgramData/QwenPaw/run` | `/var/lib/qwenpaw/run` |
| `log_dir` | 后台启动日志 | `C:/ProgramData/QwenPaw/logs` | `/var/log/qwenpaw` |

Windows 模板为 [service.example.json](../deploy/service.example.json)，Linux 模板为 [service.linux.example.json](../deploy/service.linux.example.json)。盘符和目录均可修改，应使用服务账户有权限访问的持久路径。`backup_dir` 只指定应用备份位置，不会自动执行 PostgreSQL 备份；正式备份还应复制到独立磁盘或远端存储。

`service init` 根据当前操作系统生成上述数据目录，记录当前终端目录为 `project_dir`、当前解释器为 `python`，所以须在源码根目录使用项目虚拟环境执行。它只创建配置，不创建数据目录或授予权限。运行前创建所需目录并配置服务账户权限。Linux 可复制模板到 `/etc/qwenpaw/service.json` 后编辑。

所有正式运维命令都应显式传入同一个绝对 `--config` 路径。无参数时仍读取相对当前终端的 `deploy/service.local.json`，仅用于兼容现有本机实例。已有配置和省略字段的兼容行为不变，更新代码不会自动迁移目录；正式配置应保留表中全部目录字段。

通过 service 启动时，`working_dir` 等字段决定实例位置，并覆盖终端中残留的实例目录变量。用户主目录下 `.qwenpaw` 是原有入口的默认目录，不是显式 service 配置的工作目录。数据库位置由 `environment` 中的 URL/schema 决定，不存放在 `working_dir` 中。

新服务器安装时直接指定新目录；迁移已有实例必须按第 8 节同步迁移数据库、文件、密钥及路径引用。仅修改 `working_dir` 不会搬运数据，也不会改写智能体配置或数据库中已有的绝对路径。外部项目目录应单独登记和映射。

## 4. 数据库初始化和管理员

全新部署使用新的数据库和 schema。以下 SQL 由数据库管理员执行，密码自行设置，不复用示例密码：

```sql
CREATE ROLE qwenpaw LOGIN PASSWORD '替换为随机密码';
CREATE DATABASE qwenpaw OWNER qwenpaw;
-- 切换到 qwenpaw 数据库之后：
CREATE SCHEMA qwenpaw AUTHORIZATION qwenpaw;
```

配置数据库 URL 与 schema。URL 中密码里的 `@`、`:`、`/` 等字符须做百分号编码。源码中的 `alembic.ini` URL 是无效占位值，使用 service 命令从实例配置传入真实 URL。

```powershell
& ".venv/Scripts/python.exe" -m qwenpaw service --config "C:/ProgramData/QwenPaw/config/service.json" database-upgrade --yes
& ".venv/Scripts/python.exe" -m qwenpaw service --config "C:/ProgramData/QwenPaw/config/service.json" exec init
```

初始化时按提示配置工作区；模型也可以启动后由管理员在控制台设置。不对已有实例执行 `init --force`。数据库升级不会创建数据库/schema；非空但没有 Alembic 版本的 schema 会被拒绝，避免接管不明数据。

多用户存储有三个领域切换配置：

- `QWENPAW_CUTOVER_VALIDATED_DOMAINS`：领域迁移/初始化已经验证。
- `QWENPAW_CUTOVER_LEGACY_FROZEN_DOMAINS`：旧存储停止写入。
- `QWENPAW_CUTOVER_POSTGRES_WRITES_DOMAINS`：允许新数据库写入。

**全新实例**：确认目录和 schema 均为本次新建、无旧用户和会话待迁移，版本已到 head 后，将三个值显式设置为 `all`，再执行 `service check`。**旧实例**：只能沿用已验收的声明，或者完成平台迁移预览、执行及核验后再设置；不能仅为消除报错填 `all`。

```powershell
& ".venv/Scripts/python.exe" -m qwenpaw service --config "C:/ProgramData/QwenPaw/config/service.json" start
```

首次仅在本机访问登录页，按注册引导创建第一个管理员。后续普通用户由管理员在用户管理中创建；已有账号的实例不会开放首次注册。设置模型供应商、默认模型后新建对话验证。确认完成管理员创建后才配置内网访问或反向代理。

运行时应使用经过授权配置的数据库账户。随附 Compose 面向单机部署，使用容器创建的数据库所有者；严格限制数据库角色/BYPASSRLS 的生产部署需另行审核授权，不能把此示例当作数据库最小权限方案。

## 5. Linux 服务器托管

使用部署账户 `qwenpaw`，源码放 `/opt/qwenpaw`，实例配置放 `/etc/qwenpaw/service.json`，持久数据放 `/var/lib/qwenpaw`，日志放 `/var/log/qwenpaw`。配置中的解释器和所有目录改成实际绝对路径。

Linux 在创建账户、目录并编辑实例配置后，使用相同配置完成第 4 节的初始化流程：

```bash
"/opt/qwenpaw/.venv/bin/python" -m qwenpaw service --config "/etc/qwenpaw/service.json" database-upgrade --yes
"/opt/qwenpaw/.venv/bin/python" -m qwenpaw service --config "/etc/qwenpaw/service.json" exec init
# 按第 4 节核验初始化并设置切换声明后：
"/opt/qwenpaw/.venv/bin/python" -m qwenpaw service --config "/etc/qwenpaw/service.json" check
"/opt/qwenpaw/.venv/bin/python" -m qwenpaw service --config "/etc/qwenpaw/service.json" run
```

前台验证后正常退出，再由管理员安装 `deploy/qwenpaw.service`：

```bash
sudo install -m 644 deploy/qwenpaw.service /etc/systemd/system/qwenpaw.service
sudo systemctl daemon-reload
sudo systemctl enable --now qwenpaw
sudo systemctl status qwenpaw
sudo journalctl -u qwenpaw -f
sudo systemctl restart qwenpaw
```

安装前需创建运行账户并授予代码读取、数据目录写入权限。systemd 管理的服务日常用 systemctl 停启，避免手工 stop 触发托管重启策略。PostgreSQL 必须先可用；数据库未就绪时服务失败退出，systemd 按模板重试。对外访问建议通过带 TLS 的反向代理，保留应用多用户登录；应用默认仅绑定回环地址。

## 6. Windows 长期运行

正式 Windows 实例使用以下命令；`start` 可替换为 `status`、`stop`、`restart` 或 `logs`：

```powershell
& "D:/Apps/QwenPaw/.venv/Scripts/python.exe" -m qwenpaw service --config "C:/ProgramData/QwenPaw/config/service.json" start
```

需要登录自动运行时，显式安装任务：

```powershell
& "D:/Apps/QwenPaw/deploy/install-windows-task.ps1" -Python "D:/Apps/QwenPaw/.venv/Scripts/python.exe" -Config "C:/ProgramData/QwenPaw/config/service.json"
Start-ScheduledTask -TaskName "QwenPaw"
Get-ScheduledTaskInfo -TaskName "QwenPaw"
```

模板是**当前用户登录时启动**，失败重试三次；不伪称为无人登录的系统服务。需要开机无人登录运行时，在任务计划程序中选定专用运行账户、启用“无论用户是否登录都运行”并改为系统启动触发器，按系统提示保存凭据。此时 Docker Desktop 和依赖工具也必须能在该运行账户下使用；无人值守服务器优先使用可自动启动的数据库服务。

安装任务前先停止手工 start 的实例。正常关闭先用 `service stop`，然后在任务计划程序确认任务已结束；日常启动交给任务计划程序。卸载托管只取消任务，不删除实例数据。前台 run 的应用日志仍在工作目录应用日志中，启动控制台输出由任务宿主负责收集；故障时停止任务，用 `service run` 查看启动错误。

## 7. 容器部署（新 Linux 实例）

使用 `deploy/compose.multi-user.yml` 从当前源码构建，包含 PostgreSQL 与独立持久卷。它不会复用本机 55432 验收数据库。Windows 智能体中的盘符和 PowerShell 命令不能直接迁到 Linux 容器。

复制 `deploy/.env.example` 为 `deploy/.env`，填写数据库密码和对应 URL（主机为 `db`）。在项目根目录执行：

```bash
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml build
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml up -d db
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml run --rm app python -m qwenpaw service --config /app/deploy/service.container.json database-upgrade --yes
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml run --rm app python -m qwenpaw service --config /app/deploy/service.container.json exec init
```

按第 4 节核验全新初始化后，在 `.env` 中填写三个切换值 `all`，再启动：

```bash
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml up -d
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml ps
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml logs -f app
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml restart app
docker compose --env-file deploy/.env -f deploy/compose.multi-user.yml stop app
```

配置变更后用 `up -d` 重新创建容器；仅 restart 不加载新环境变量。不要使用 `down -v`，该操作会删除数据卷。普通停止 app 不停止数据库。镜像构建耗时和磁盘占用较大，浏览器/Python 依赖需要网络；本机源码验收不等同于该 Linux 镜像已经构建验收。

## 8. 备份、升级和原数据迁移

备份必须同时覆盖 PostgreSQL、working、secrets、配置及所需外部附件目录。仅复制 working 无法恢复多用户会话，缺失 secrets 可能无法解密凭据。

推荐停服制作一致性备份：

1. 记录源码版本/构建产物、数据库当前 Alembic 版本和实例配置。
2. 正常停服，确认无运行中的会话和自动任务写入。
3. 使用 `pg_dump -Fc` 导出所选数据库到独立备份位置。密码用本地凭据文件或交互输入，不写入命令日志。
4. 复制 working、secrets 及实例配置，保留目录结构与权限，记录备份时间。
5. 在隔离数据库和目录进行恢复演练；核对账号、智能体、聊天及文件后再视为有效备份。

升级先备份并停服，再安装当前源码依赖、构建前端。有数据库版本变更时显式执行 database-upgrade；随后 check/start，登录验证。数据库升级后的回滚应恢复匹配版本的数据库和文件备份，不能仅回退 Python 代码。

原实例迁出 `tmp`：先列出工作区配置和数据库内的绝对路径引用，形成旧路径到新路径映射；停服备份后**复制**到正式目录，更新路径引用和 service 配置，在新目录验证文件下载、资料库、附件、技能和模型。旧目录保留供回滚。批量路径更新需审核具体清单后执行；本文不提供无条件字符串替换或自动删除旧目录的命令。

## 9. 故障排查

| 表现 | 检查方式 |
|---|---|
| 配置不存在 | 在仓库根目录运行或指定绝对 --config；init 只生成模板 |
| 数据库 connection_failed | 数据库进程、端口、密码、URL 编码；当前机器检查 qwenpaw-pg |
| schema_revision_incomplete | 停服备份，确认所选 schema 后显式升级 |
| domain_migration_not_validated | 核查新建或迁移验收，不能盲目填 all |
| 端口被占用 | 核对占用程序，停止旧启动方式；新命令不会杀死陌生进程 |
| starting_or_unhealthy | 查看 service.log、工作区应用日志，检查数据库与核心智能体启动 |
| 页面还是旧版本 | 重新构建前端，restart，然后强制刷新浏览器 |
| 无模型可用 | 管理员配置供应商/默认模型及授权，与服务是否启动是两件事 |
| stop 超时 | 查运行任务和关闭日志；明确需要时使用 stop --force |
| 服务日志过大 | 停服归档 service.log 后重启；run 托管使用系统日志轮转 |

API 健康接口在当前多用户模式受认证保护，运维命令使用本机受控进程心跳，结合数据库版本/切换校验判断就绪，不把首页 200 当作完整健康状态。
