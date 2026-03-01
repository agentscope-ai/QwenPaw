# 系统服务管理

`copaw service` 用于将 CoPaw 注册为系统服务，实现**后台运行**和**开机自启**，替代 `nohup copaw app &` 的方式。

> 不需要后台运行？直接用 `copaw app` 前台启动即可，参见 [CLI](./cli)。

---

## 前后变化

**之前**（前台运行，关闭终端即停止）：

```bash
pip install copaw
copaw init --defaults
copaw app                      # 前台运行
# 或
nohup copaw app > copaw.log 2>&1 &   # 后台运行，重启后失效
```

**现在**（注册为系统服务，开机自启）：

```bash
pip install copaw
copaw init --defaults
copaw service install          # 注册服务 + 开机自启
copaw service start            # 启动
```

> 如果通过 `install.sh` 或 `install.ps1` 安装，`copaw service install` 会由安装脚本自动完成。

### 日常使用对比

| 场景 | 之前 | 现在 |
|------|------|------|
| 启动 | `copaw app` 或 `nohup copaw app &` | `copaw service start` |
| 停止 | Ctrl+C 或 `kill <pid>` | `copaw service stop` |
| 重启 | 手动停止再启动 | `copaw service restart` |
| 查看状态 | `ps aux \| grep copaw` | `copaw service status` |
| 查看日志 | 看终端输出或 nohup.out | `copaw service logs` |
| 重启机器后 | 需要手动重新启动 | 自动启动，无需操作 |

### 对已有命令的影响

`copaw app` 仍可正常使用，行为不变。`copaw app` 适合调试和开发（直接看终端输出），`copaw service` 适合长期部署（后台 + 自启）。两者不应同时使用同一端口。

---

## 支持的平台

| 平台 | 后端 | 服务级别 | 自启动时机 |
|------|------|---------|-----------|
| Linux | systemd | 用户级（默认）/ 系统级（`--system`） | 开机后（无需登录） |
| macOS | launchd | 用户级 LaunchAgent | 用户登录时 |
| Windows | 任务计划程序 | 用户级计划任务 | 用户登录时 |

---

## 命令参考

### copaw service install

安装并启用服务。

```bash
copaw service install                          # 默认 127.0.0.1:8088
copaw service install --host 0.0.0.0 --port 9090   # 自定义地址
copaw service install --system                 # 系统级服务（仅 Linux，需 sudo）
```

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `--host` | `127.0.0.1` | 绑定地址 |
| `--port` | `8088` | 绑定端口 |
| `--system` | 否 | 安装为系统级服务（仅 Linux） |

修改参数只需重新安装，新配置会覆盖旧配置：

```bash
copaw service install --host 0.0.0.0 --port 9090
```

### copaw service uninstall

停止并移除服务。

```bash
copaw service uninstall          # 交互确认
copaw service uninstall --yes    # 跳过确认
copaw service uninstall --system # 移除系统级服务（仅 Linux）
```

### copaw service start / stop / restart

```bash
copaw service start              # 启动
copaw service stop               # 停止
copaw service restart            # 重启
```

### copaw service status

显示服务当前状态。输出因平台而异：

- **Linux**：`systemctl status` 完整输出（PID、内存占用、最近日志）
- **macOS**：launchd 中的 PID 和状态
- **Windows**：`schtasks /Query` 任务信息

### copaw service logs

查看服务日志。

```bash
copaw service logs               # 最近 50 行
copaw service logs -n 100        # 最近 100 行
copaw service logs -f            # 持续跟踪（Ctrl+C 退出）
```

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `-n` / `--lines` | `50` | 显示行数 |
| `-f` / `--follow` | 否 | 持续跟踪 |

日志来源：Linux 通过 `journalctl`，macOS / Windows 读取 `~/.copaw/logs/` 下的日志文件。

---

## 各平台详细说明

### Linux (systemd)

#### 用户级服务（默认）

`copaw service install` 会：

1. 创建 `~/.config/systemd/user/copaw.service`
2. 执行 `systemctl --user enable copaw`
3. 执行 `loginctl enable-linger` 确保不登录也能启动

生成的 unit 文件示例：

```ini
[Unit]
Description=CoPaw Personal Assistant
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/<user>/.copaw/venv/bin/copaw app --host 127.0.0.1 --port 8088
Restart=on-failure
RestartSec=5
Environment=COPAW_WORKING_DIR=/home/<user>/.copaw

[Install]
WantedBy=default.target
```

#### 系统级服务（`--system`）

写入 `/etc/systemd/system/copaw.service`（需 sudo），`WantedBy=multi-user.target`。

### macOS (launchd)

`copaw service install` 会创建 `~/Library/LaunchAgents/com.copaw.app.plist`：

- `RunAtLoad=true` — 登录时自动启动
- `KeepAlive=true` — 进程退出后自动重启
- 日志输出到 `~/.copaw/logs/copaw.log` 和 `~/.copaw/logs/copaw.err`

> macOS 不支持 `--system` 参数。系统级 LaunchDaemon 需要 root 权限，建议有需要时手动配置。

### Windows (任务计划程序)

`copaw service install` 通过 PowerShell 创建名为 `CoPaw` 的计划任务：

- 触发器：用户登录时（AtLogOn）
- 使用电池时仍运行，不会因切换到电池而停止
- 失败后自动重试 3 次，间隔 1 分钟
- 无执行时间限制

查看任务：按 `Win+R`，输入 `taskschd.msc`，在任务计划程序库中找到 `CoPaw`。

> Windows 下 `--system` 参数会被忽略。如需以 Windows Service 运行（无需用户登录），建议使用 [NSSM](https://nssm.cc/)：
> ```cmd
> nssm install CoPaw C:\Users\<user>\.copaw\venv\Scripts\copaw.exe app --host 127.0.0.1 --port 8088
> ```

---

## 文件影响

### 创建的文件

| 平台 | 文件路径 | 说明 |
|------|---------|------|
| Linux | `~/.config/systemd/user/copaw.service` | systemd 用户级 unit 文件 |
| Linux | `/etc/systemd/system/copaw.service` | 系统级 unit 文件（`--system`，需 sudo） |
| macOS | `~/Library/LaunchAgents/com.copaw.app.plist` | launchd 用户代理配置 |
| 全平台 | `~/.copaw/logs/` | 日志目录 |

### 修改的系统状态

| 平台 | 变更 | 说明 |
|------|------|------|
| Linux | systemd enable | `systemctl --user enable copaw` |
| Linux | linger | `loginctl enable-linger`，用户服务无需登录即可运行 |
| macOS | launchd job | `launchctl load/unload` |
| Windows | 任务计划程序 | `Register-ScheduledTask` / `schtasks` |

`copaw service uninstall` 会撤销上述所有变更。`copaw uninstall` 会自动检测并清理服务。

---

## 常见问题

### Linux 重启后服务没有自动启动

确认 linger 已启用：

```bash
loginctl show-user $(whoami) --property=Linger
```

如果显示 `Linger=no`，手动启用：

```bash
loginctl enable-linger $(whoami)
```

### macOS 服务启动后立即退出

查看错误日志：

```bash
copaw service logs
# 或直接查看
cat ~/.copaw/logs/copaw.err
```

常见原因：端口被占用、配置文件缺失、Python 环境损坏。

### Windows 下如何查看任务

按 `Win+R`，输入 `taskschd.msc`。或命令行：

```cmd
schtasks /Query /TN CoPaw /V
```

---

## 相关页面

- [快速开始](./quickstart) — 安装与首次运行
- [CLI](./cli) — 全部命令行用法
- [配置与工作目录](./config) — 工作目录与 config.json
