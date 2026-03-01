# CoPaw 系统服务管理

`copaw service` 命令组用于将 CoPaw 注册为系统服务，实现开机自启和后台运行，替代手动使用 `nohup copaw app &` 的方式。

---

## 目录

- [前后变化对比](#前后变化对比)
  - [安装和启动流程](#安装和启动流程)
  - [日常使用](#日常使用)
  - [对已有命令的影响](#对已有命令的影响)
- [支持的平台](#支持的平台)
- [快速开始](#快速开始)
- [命令参考](#命令参考)
  - [copaw service install](#copaw-service-install)
  - [copaw service uninstall](#copaw-service-uninstall)
  - [copaw service start](#copaw-service-start)
  - [copaw service stop](#copaw-service-stop)
  - [copaw service status](#copaw-service-status)
  - [copaw service logs](#copaw-service-logs)
- [各平台详细说明](#各平台详细说明)
  - [Linux (systemd)](#linux-systemd)
  - [macOS (launchd)](#macos-launchd)
  - [Windows (任务计划程序)](#windows-任务计划程序)
- [安装脚本的自动行为](#安装脚本的自动行为)
- [卸载时的自动清理](#卸载时的自动清理)
- [文件影响汇总](#文件影响汇总)
- [常见问题](#常见问题)

---

## 前后变化对比

### 安装和启动流程

**之前（前台运行，关闭终端即停止）：**

```bash
pip install copaw
copaw init --defaults
copaw app
```

`copaw app` 是前台进程，关闭终端或 Ctrl+C 后服务即终止。如果需要后台运行，必须借助 `nohup`：

```bash
nohup copaw app > copaw.log 2>&1 &
```

且每次重启机器后需要手动重新执行。

**现在（注册为系统服务，开机自启）：**

```bash
pip install copaw
copaw init --defaults
copaw service install
copaw service start
```

之后无需保持终端打开，重启机器后也会自动运行。

> 如果通过 `install.sh` 或 `install.ps1` 脚本安装，第三步会由安装脚本自动完成，只需手动执行 `copaw service start`。

### 日常使用

| 场景 | 之前 | 现在 |
|------|------|------|
| 启动 | `copaw app` 或 `nohup copaw app &` | `copaw service start` |
| 停止 | Ctrl+C 或 `kill <pid>` | `copaw service stop` |
| 查看状态 | 手动 `ps aux \| grep copaw` | `copaw service status` |
| 查看日志 | 查看 nohup.out 或终端输出 | `copaw service logs` |
| 重启机器后 | 需要手动重新启动 | 自动启动，无需操作 |
| 修改端口 | 停止后用新参数重新运行 | `copaw service install --port 9090` |

### 对已有命令的影响

新增的 `copaw service` 功能**不影响**任何已有命令的行为：

| 命令 | 是否受影响 | 说明 |
|------|-----------|------|
| `pip install copaw` | 否 | 无新依赖，打包结构不变 |
| `copaw init --defaults` | 否 | 初始化逻辑未修改 |
| `copaw app` | 否 | 仍然可以直接前台运行，行为不变 |
| `copaw uninstall` | 有增强 | 卸载时会自动检测并清理已注册的服务 |

`copaw app` 和 `copaw service start` 可以独立使用。`copaw app` 适合调试和开发场景（直接在终端看输出），`copaw service` 适合长期部署场景（后台运行 + 开机自启）。两者不应同时使用同一端口。

---

## 支持的平台

| 平台 | 后端 | 服务级别 | 自启动时机 |
|------|------|---------|-----------|
| Linux | systemd | 用户级（默认）/ 系统级（`--system`） | 开机后（无需登录） |
| macOS | launchd | 用户级 LaunchAgent | 用户登录时 |
| Windows | 任务计划程序 (Task Scheduler) | 用户级计划任务 | 用户登录时 |

---

## 快速开始

```bash
# 1. 安装服务并启用开机自启
copaw service install

# 2. 立即启动服务
copaw service start

# 3. 查看服务状态
copaw service status

# 4. 查看日志
copaw service logs
```

如需自定义绑定地址和端口：

```bash
copaw service install --host 0.0.0.0 --port 9090
```

---

## 命令参考

### copaw service install

安装 CoPaw 为系统服务，并启用开机自启。

```
copaw service install [--host HOST] [--port PORT] [--system]
```

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `--host` | `127.0.0.1` | CoPaw 应用绑定的主机地址 |
| `--port` | `8088` | CoPaw 应用绑定的端口 |
| `--system` | 否 | 安装为系统级服务（仅 Linux 有效，需要 sudo 权限） |

**行为说明：**

- 该命令会在系统中创建服务配置文件（具体位置因平台而异，见下文）
- 将服务设置为开机自启（enable）
- Linux 用户级模式下，会额外执行 `loginctl enable-linger` 以确保不登录也能启动服务
- 如果已有同名服务存在，会先移除旧配置再重新创建
- 安装完成后需要手动执行 `copaw service start` 来立即启动

### copaw service uninstall

停止并移除 CoPaw 服务。

```
copaw service uninstall [--system] [--yes]
```

| 参数 | 说明 |
|------|------|
| `--system` | 移除系统级服务（仅 Linux） |
| `--yes` | 跳过确认提示 |

**行为说明：**

- 先停止正在运行的服务
- 删除服务配置文件
- Linux 下会执行 `systemctl daemon-reload` 刷新 systemd 配置
- 不会删除日志文件

### copaw service start

启动 CoPaw 服务。

```
copaw service start [--system]
```

### copaw service stop

停止 CoPaw 服务。

```
copaw service stop [--system]
```

### copaw service status

显示当前服务的运行状态。

```
copaw service status [--system]
```

输出内容因平台而异：
- Linux：显示 `systemctl status` 的完整输出（包含 PID、内存占用、最近日志等）
- macOS：显示 `launchctl list` 中的 PID 和状态
- Windows：显示 `schtasks /Query` 的详细任务信息

### copaw service logs

查看服务的运行日志。

```
copaw service logs [-n LINES] [-f] [--system]
```

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `-n`, `--lines` | `50` | 显示最近的日志行数 |
| `-f`, `--follow` | 否 | 持续跟踪输出（类似 `tail -f`，按 Ctrl+C 退出） |
| `--system` | 否 | 查看系统级服务的日志（仅 Linux） |

**日志来源：**
- Linux：通过 `journalctl` 读取 systemd 日志
- macOS / Windows：读取 `~/.copaw/logs/` 目录下的日志文件

---

## 各平台详细说明

### Linux (systemd)

#### 用户级服务（默认）

执行 `copaw service install` 后：

1. **创建 systemd unit 文件**

   路径：`~/.config/systemd/user/copaw.service`

   内容示例：
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

2. **执行 systemd 操作**
   - `systemctl --user daemon-reload` — 重新加载 unit 文件
   - `systemctl --user enable copaw` — 启用开机自启

3. **启用 linger**
   - `loginctl enable-linger <当前用户>` — 确保用户服务在系统启动时运行，无需用户登录

#### 系统级服务（`--system`）

执行 `copaw service install --system` 后：

1. **创建 systemd unit 文件**（需要 sudo）

   路径：`/etc/systemd/system/copaw.service`

   与用户级的区别：`WantedBy=multi-user.target`

2. **执行 systemd 操作**
   - `systemctl daemon-reload`
   - `systemctl enable copaw`

#### 系统影响

| 操作 | 影响的文件/系统状态 |
|------|-------------------|
| install（用户级） | 创建 `~/.config/systemd/user/copaw.service` |
| install（用户级） | 创建 `~/.copaw/logs/` 目录 |
| install（用户级） | 修改 linger 状态：`/var/lib/systemd/linger/<user>` |
| install（系统级） | 创建 `/etc/systemd/system/copaw.service`（需 sudo） |
| uninstall | 删除对应的 `.service` 文件 |
| logs | 只读操作，通过 `journalctl` 读取 |

---

### macOS (launchd)

执行 `copaw service install` 后：

1. **创建 launchd plist 文件**

   路径：`~/Library/LaunchAgents/com.copaw.app.plist`

   内容示例：
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
       <key>Label</key>
       <string>com.copaw.app</string>
       <key>ProgramArguments</key>
       <array>
           <string>/Users/<user>/.copaw/venv/bin/copaw</string>
           <string>app</string>
           <string>--host</string>
           <string>127.0.0.1</string>
           <string>--port</string>
           <string>8088</string>
       </array>
       <key>RunAtLoad</key>
       <true/>
       <key>KeepAlive</key>
       <true/>
       <key>StandardOutPath</key>
       <string>/Users/<user>/.copaw/logs/copaw.log</string>
       <key>StandardErrorPath</key>
       <string>/Users/<user>/.copaw/logs/copaw.err</string>
       <key>EnvironmentVariables</key>
       <dict>
           <key>COPAW_WORKING_DIR</key>
           <string>/Users/<user>/.copaw</string>
       </dict>
   </dict>
   </plist>
   ```

2. **关键配置说明**
   - `RunAtLoad=true` — 用户登录时自动启动
   - `KeepAlive=true` — 进程退出后自动重启

3. **启动/停止机制**
   - 启动：`launchctl load -w <plist路径>`
   - 停止：`launchctl unload <plist路径>`
   - 卸载：`launchctl unload -w <plist路径>` 然后删除 plist 文件

#### 系统影响

| 操作 | 影响的文件/系统状态 |
|------|-------------------|
| install | 创建 `~/Library/LaunchAgents/com.copaw.app.plist` |
| install | 创建 `~/.copaw/logs/` 目录 |
| start | 注册 launchd job（`launchctl load`） |
| stop | 注销 launchd job（`launchctl unload`） |
| uninstall | 删除 `com.copaw.app.plist` 文件 |
| 运行时 | 持续写入 `~/.copaw/logs/copaw.log` 和 `~/.copaw/logs/copaw.err` |

> **说明：** macOS 不支持 `--system` 参数。系统级 LaunchDaemon 需要 root 权限和更复杂的配置，建议有需要时手动设置。

---

### Windows (任务计划程序)

执行 `copaw service install` 后：

1. **通过 PowerShell 创建计划任务**

   任务名称：`CoPaw`

   等效的 PowerShell 操作：
   ```powershell
   $action = New-ScheduledTaskAction `
       -Execute 'C:\Users\<user>\.copaw\venv\Scripts\copaw.exe' `
       -Argument 'app --host 127.0.0.1 --port 8088' `
       -WorkingDirectory 'C:\Users\<user>\.copaw'

   $trigger = New-ScheduledTaskTrigger -AtLogOn

   $settings = New-ScheduledTaskSettingsSet `
       -AllowStartIfOnBatteries `
       -DontStopIfGoingOnBatteries `
       -StartWhenAvailable `
       -RestartCount 3 `
       -RestartInterval (New-TimeSpan -Minutes 1) `
       -ExecutionTimeLimit (New-TimeSpan -Days 0)

   Register-ScheduledTask `
       -TaskName 'CoPaw' `
       -Action $action `
       -Trigger $trigger `
       -Settings $settings `
       -Description 'CoPaw Personal Assistant'
   ```

2. **任务配置说明**
   - 触发器：用户登录时（`AtLogOn`）
   - 电池策略：使用电池时仍允许运行，且不会因切换到电池而停止
   - 失败重启：失败后自动重试 3 次，间隔 1 分钟
   - 执行时间限制：无限制（不会被系统自动终止）
   - 如果已存在同名任务，会先删除再重新创建

3. **启动/停止机制**
   - 启动：`schtasks /Run /TN CoPaw`
   - 停止：`schtasks /End /TN CoPaw`
   - 状态查询：`schtasks /Query /TN CoPaw /FO LIST /V`
   - 删除：`schtasks /Delete /TN CoPaw /F`

#### 系统影响

| 操作 | 影响的系统状态 |
|------|--------------|
| install | 在 Windows 任务计划程序中注册名为 `CoPaw` 的计划任务 |
| install | 创建 `%USERPROFILE%\.copaw\logs\` 目录 |
| uninstall | 从任务计划程序中删除 `CoPaw` 任务 |
| 运行时 | 任务计划程序默认不捕获 stdout；如需文件日志请自行配置 |

> **说明：** Windows 下的 `--system` 参数会被忽略。如果需要以真正的 Windows Service 方式运行（无需用户登录即可启动），建议使用 [NSSM](https://nssm.cc/)：
> ```cmd
> nssm install CoPaw C:\Users\<user>\.copaw\venv\Scripts\copaw.exe app --host 127.0.0.1 --port 8088
> ```

---

## 安装脚本的自动行为

通过 `install.sh`（Linux/macOS）或 `install.ps1`（Windows）安装 CoPaw 时，安装脚本在完成 Python 环境创建和包安装之后，会**自动执行** `copaw service install`。

- 如果注册成功，安装摘要中会显示 `Service: registered (auto-start enabled)`
- 如果注册失败（例如系统不支持或权限不足），会显示 `Service: skipped`，不影响整体安装流程
- 失败时可以稍后手动运行 `copaw service install`

**install.sh 中的相关逻辑：**

```bash
"$COPAW_VENV/bin/copaw" service install 2>/dev/null && {
    # 显示注册成功
} || {
    # 显示跳过（不中断安装）
}
```

**install.ps1 中的相关逻辑：**

```powershell
try {
    & $VenvCopaw service install 2>$null
    # 检查返回值并显示结果
} catch {
    # 显示跳过（不中断安装）
}
```

---

## 卸载时的自动清理

执行 `copaw uninstall` 时，会**自动检测**是否存在已安装的 CoPaw 服务。如果存在，会在删除环境文件之前先停止并移除服务。

清理顺序：
1. 检测并移除系统服务（停止 + 删除配置文件）
2. 删除 `~/.copaw/venv/` 和 `~/.copaw/bin/` 目录
3. 如果指定了 `--purge`，删除整个 `~/.copaw/` 目录（包含日志）
4. 清理 shell 配置文件中的 PATH 条目

---

## 文件影响汇总

下表列出了 `copaw service` 功能在各平台上**创建、修改或删除**的所有文件和系统状态。

### 创建的文件

| 平台 | 文件路径 | 创建时机 | 说明 |
|------|---------|---------|------|
| Linux | `~/.config/systemd/user/copaw.service` | `service install` | systemd 用户级 unit 文件 |
| Linux | `/etc/systemd/system/copaw.service` | `service install --system` | systemd 系统级 unit 文件（需 sudo） |
| macOS | `~/Library/LaunchAgents/com.copaw.app.plist` | `service install` | launchd 用户代理配置 |
| 全平台 | `~/.copaw/logs/` | `service install` | 日志目录（安装时创建） |
| macOS | `~/.copaw/logs/copaw.log` | 服务运行时 | stdout 日志 |
| macOS | `~/.copaw/logs/copaw.err` | 服务运行时 | stderr 日志 |

### 修改的系统状态

| 平台 | 状态变更 | 操作 | 说明 |
|------|---------|------|------|
| Linux | systemd unit 注册 | `service install` | `systemctl --user enable copaw` |
| Linux | linger 启用 | `service install` | `loginctl enable-linger`，使用户服务无需登录即可运行 |
| Linux | `/etc/systemd/system/` 写入 | `service install --system` | 需要 sudo |
| macOS | launchd job 注册/注销 | `service start/stop` | `launchctl load/unload` |
| Windows | 任务计划程序任务注册 | `service install` | 通过 PowerShell `Register-ScheduledTask` |
| Windows | 任务计划程序任务删除 | `service uninstall` | 通过 `schtasks /Delete` |

### 删除的文件

| 平台 | 文件路径 | 删除时机 |
|------|---------|---------|
| Linux | `~/.config/systemd/user/copaw.service` | `service uninstall` 或 `uninstall` |
| Linux | `/etc/systemd/system/copaw.service` | `service uninstall --system` |
| macOS | `~/Library/LaunchAgents/com.copaw.app.plist` | `service uninstall` 或 `uninstall` |
| Windows | 任务计划程序中的 `CoPaw` 任务 | `service uninstall` 或 `uninstall` |
| 全平台 | `~/.copaw/logs/` 目录 | 仅在 `uninstall --purge` 时随 `~/.copaw/` 一起删除 |

### 新增的源码文件

| 文件路径 | 说明 |
|---------|------|
| `src/copaw/service.py` | 服务管理核心模块，包含各平台的 `ServiceManager` 实现 |
| `src/copaw/cli/service_cmd.py` | CLI 命令组定义（`copaw service` 下的所有子命令） |

### 修改的源码文件

| 文件路径 | 变更内容 |
|---------|---------|
| `src/copaw/cli/main.py` | 注册 `service_group` 命令到 CLI |
| `src/copaw/cli/uninstall_cmd.py` | 在卸载流程中增加服务的自动检测和清理 |
| `scripts/install.sh` | 安装完成后自动调用 `copaw service install`（Linux/macOS） |
| `scripts/install.ps1` | 安装完成后自动调用 `copaw service install`（Windows） |

---

## 常见问题

### Linux 用户服务在重启后没有自动启动

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

### Windows 下如何查看任务计划程序中的任务

1. 按 `Win+R`，输入 `taskschd.msc` 打开任务计划程序
2. 在任务计划程序库中找到名为 `CoPaw` 的任务
3. 右键可查看属性、手动运行或删除

或者通过命令行：

```cmd
schtasks /Query /TN CoPaw /V
```

### 如何修改服务的启动参数（host/port）

重新安装服务即可，新配置会覆盖旧配置：

```bash
copaw service install --host 0.0.0.0 --port 9090
```

### 服务与 `copaw app` 直接运行有什么区别

功能上完全相同。`copaw service` 只是将 `copaw app` 封装为系统服务，提供：
- 开机自启
- 后台运行（无需保持终端打开）
- 进程异常退出后自动重启
- 统一的启停和日志管理
