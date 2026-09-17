---
title: "QwenPaw 2.0 Sandbox 模块介绍"
date: 2026-07-29
author: QwenPaw Team
tags: [Sandbox, 安全隔离, Landlock, Seatbelt, Windows]
cover: https://img.alicdn.com/imgextra/i4/O1CN01lN8QDc1ZB2kAtxHH5_!!6000000003155-2-tps-1536-1024.png
excerpt: "Sandbox 是 QwenPaw 的内置安全隔离层：内核级文件隔离、敏感路径屏蔽、环境变量清洗，以及违规时的审批升级——让 Agent 执行命令时只看得到该看的，只改得了该改的。"
---

# QwenPaw 2.0 Sandbox 模块介绍

## 一、Sandbox 是什么

Sandbox（沙箱）是 QwenPaw 的内置安全隔离层。当 AI Agent 执行 Shell 命令或运行代码时，Sandbox 将命令限制在一个受控的环境中——命令只能访问你允许它访问的文件和资源，无法触及系统中的敏感信息。

简而言之：**Sandbox 让 Agent 执行命令时"只看得到该看的，只改得了该改的"。**

## 二、设计理念

QwenPaw Sandbox 的设计围绕以下四个核心理念：

### 2.1 全面防护能力

Sandbox 提供的是**内核级**的强制隔离，而非应用层的软限制。无论沙箱内的命令如何尝试绕过（提权、路径遍历、符号链接跟踪等），操作系统内核都会在最底层阻断越权访问。具体而言，Sandbox 能够防护以下类型的攻击：

- **未授权文件读取** — 阻止命令窃取 SSH 密钥、API Token、云凭据等敏感文件
- **未授权文件写入** — 阻止命令篡改系统配置、植入后门或覆盖关键数据
- **环境变量泄露** — 清空进程环境中的 API Key 等秘密信息，防止通过 `env`/`printenv` 泄露
- **进程逃逸** — 通过 PID 命名空间（Linux）或 Job Object（Windows）限制进程可见性和传播
- **超时耗尽资源** — 强制终止超时进程，防止死循环或资源耗尽攻击

这些保护直接由操作系统内核执行（Linux Landlock LSM / mount namespace、macOS Seatbelt 内核策略、Windows 安全令牌与 ACL），任何用户态代码无法绕过。

### 2.2 灵活的文件隔离控制

Sandbox 将文件系统权限分为三个等级：

| 权限等级   | 能力                                 | 适用场景                    |
| ---------- | ------------------------------------ | --------------------------- |
| **不可读** | 无读、写、执行权限，路径完全不可访问 | 敏感凭据目录（如 `~/.ssh`） |
| **可读**   | 有读和执行权限，无写权限             | 系统库、依赖包、参考文档    |
| **可写**   | 有读、写、执行权限                   | 工作区、构建输出目录        |

基于这三个等级，Sandbox 通过四个参数组合出灵活的隔离策略：

1.  `allow_read_all` — 控制默认读取权限。当为 `True`（默认）时，系统上所有文件默认可读；当为 `False` 时，仅显式声明的路径可读
2.  `workspace_dir` — 工作区目录，始终拥有完全读写权限，是 Agent 的主要工作空间
3.  `mounts` — 显式挂载的额外路径列表，每个路径通过 `writable` 参数独立控制是只读（可读）还是可读写（可写）
4.  `deny_paths` — 显式拒绝列表，无论上述规则如何配置，这些路径一律不可访问（不可读），优先级最高

这种分层设计既能满足"宽松读取 + 精确写控制"的日常开发需求，也能通过关闭 `allow_read_all` 切换为严格白名单模式。

### 2.3 用户友好

安全机制不应成为生产力的障碍。Sandbox 在日常使用中对用户和 Agent 完全透明——命令自动在沙箱中执行，无需额外确认，输出格式也与直接执行完全一致，用户感知不到隔离层的存在。

当命令触碰到安全边界时，Sandbox 不会简单地报错或静默丢弃，而是采用"先限制，后升级"的策略：首先在受限环境中尝试执行；如果命令确实需要超出沙箱范围的权限，系统会向用户展示清晰的违规说明和风险提示，由用户决定是否批准无沙箱重新执行。这使得 Sandbox 既不会像"默认全放行"那样留下安全隐患，也不会像"一律拒绝"那样频繁打断工作流。

### 2.4 原生轻量级

Sandbox 利用每个操作系统的原生内核级隔离能力（Linux 内核命名空间、macOS 内核策略、Windows 安全令牌），而非跨平台模拟层。系统在启动时自动探测平台能力并选择最佳方案，用户无需关心底层差异。当平台不支持隔离时，优雅降级为人工审批，而非静默跳过。

与虚拟机或 Docker 容器不同，Sandbox 不需要启动额外的操作系统实例或守护进程，也不需要构建镜像、分配虚拟磁盘。它直接在宿主进程中通过内核安全原语施加约束，因此：

- **启动开销极低** — Linux/macOS 上额外延迟 < 50ms，无需等待容器拉起
- **直接访问本地文件系统** — 沙箱内的命令直接操作宿主机文件（在授权范围内），无需文件复制或卷挂载同步
- **无资源冗余** — 不占用额外的内存、CPU 或磁盘空间来维护隔离环境
- **零前置依赖** — Windows、macOS 开箱即用，Linux 仅需一个轻量包（`bubblewrap`）或内核原生支持（Landlock）

---

## 三、Sandbox 提供的保护能力

### 3.1 文件系统隔离

| 保护项       | 说明                                                    |
| ------------ | ------------------------------------------------------- |
| 工作区限写   | 沙箱内的命令只能写入当前工作区目录和显式声明的路径      |
| 敏感路径屏蔽 | `~/.ssh`、`~/.aws`、`~/.gnupg` 等目录在沙箱内被完全屏蔽 |
| 系统目录只读 | `/usr`、`/lib`、`/etc` 等系统路径可读但不可写           |
| 灵活挂载     | 可通过策略规则为特定目录授予读或读写权限                |

### 3.2 环境变量保护

沙箱会自动清除以下环境变量，防止 Agent 泄露你的凭据：

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_ACCESS_KEY_ID`

命令在沙箱内执行时，这些变量的值为空字符串。

### 3.3 敏感路径默认屏蔽列表

以下路径在沙箱内默认被拒绝访问：

| 路径                     | 保护的内容               |
| ------------------------ | ------------------------ |
| `~/.ssh`                 | SSH 私钥和配置           |
| `~/.aws`                 | AWS 凭据                 |
| `~/.gnupg`               | GPG 密钥                 |
| `~/.kube`                | Kubernetes 配置          |
| `~/.config/gcloud`       | Google Cloud 凭据        |
| `~/.azure`               | Azure CLI 凭据           |
| `~/.docker/config.json`  | Docker 认证信息          |
| `~/.env`                 | 通用环境变量文件         |
| `~/.claude`              | Claude Code 配置与记忆   |
| `~/Library/Keychains`    | macOS 钥匙串             |
| `~/.git-credentials`     | Git 凭据                 |
| `~/.gitconfig`           | Git 配置（可能含 token） |
| `~/.npmrc` / `~/.yarnrc` | npm/yarn 认证 token      |
| `~/.pypirc`              | PyPI API token           |
| `~/.netrc`               | 通用登录凭据             |
| `~/.vault-token`         | HashiCorp Vault token    |
| `~/.terraformrc`         | Terraform 配置           |
| `~/.config/nix`          | Nix 配置                 |

### 3.4 网络访问

目前的Sandbox可以粗略地控制沙箱内的网络访问能力：

- 允许所有网络连接：适合需要联网的日常开发命令（`pip`、`git`、`npm`、`curl` 等）
- 完全阻断网络：沙箱内的命令无法建立任何出入站连接

默认允许网络是因为大量常用开发命令依赖联网，完全阻断会严重影响可用性。未来版本计划加入基于域名或 IP 的精细过滤控制，在不影响正常使用的前提下进一步收窄网络权限。

## 四、Sandbox 何时生效

### 4.1 触发条件

Sandbox 在以下条件同时满足时生效：

1.  **全局开关已开启** — `security.sandbox_enabled = true`
2.  **平台支持沙箱** — 当前操作系统能提供隔离能力
3.  **命令未被策略显式放行或拒绝** — 命令没有匹配到任何已有的 ALLOW/DENY 规则

当这三个条件都满足时，命令会透明地在沙箱内执行——**用户无需额外确认，也不会收到审批提示**。

### 4.2 与治理策略的协作关系

QwenPaw 的安全决策分为多个阶段：

```plaintext
命令到达
  │
  ├─ Phase 0: 工具类型检查（内部工具直接放行，未知工具拒绝）
  ├─ Phase 1: 深度安全扫描（检测危险模式，CRITICAL 级别直接拒绝）
  ├─ Phase 1.5: 危险命令关键词检测（sudo rm -rf /、fork bomb 等 → 拒绝）
  ├─ Phase 2: 规则匹配（builtin_rules + user_rules，首次命中生效）
  │     ├─ 匹配到 ALLOW → 直接执行（不进沙箱）
  │     ├─ 匹配到 DENY → 拒绝
  │     └─ 匹配到 ASK → 弹出审批卡片
  └─ Phase 3: 无规则匹配（Fallback）
        └─ Shell 命令 → SANDBOX_FALLBACK → 在沙箱内执行

```

**关键点**: Sandbox 处理的是"灰色地带"——那些没有被明确允许也没有被明确禁止的命令。已经通过规则显式放行的命令不会进入沙箱。

### 4.3 Sandbox 不可用时的行为

当沙箱不可用（平台不支持或全局开关关闭）时：

- 本应进入沙箱的命令会改为**弹出审批提示**（ASK），由用户手动决定是否放行
- Phase 0-2 的保护（秘密文件检测、危险命令阻断）不受影响

---

## 五、如何启用 Sandbox

### 5.1 通过配置文件

在 `config.json` 中设置：

```json
{
  "security": {
    "sandbox_enabled": true
  }
}
```

### 5.2 通过 Console 界面

在 QwenPaw Console 的 Security 设置页面，切换 Sandbox 开关即可。

### 5.3 确认沙箱状态

启动时日志会显示平台探测结果：

```plaintext
ResourceGovernor: sandbox capability: bubblewrap available with user namespaces

```

或当不可用时：

```plaintext
ResourceGovernor: sandbox not available — bwrap not found on PATH.
SANDBOX_FALLBACK will escalate to ASK.

```

---

## 六、支持的平台与隔离方式

Sandbox 自动检测当前操作系统并选择最强的可用隔离方式：

| 操作系统    | 隔离方式                        | 要求                               | 特点                                           |
| ----------- | ------------------------------- | ---------------------------------- | ---------------------------------------------- |
| **Linux**   | Bubblewrap (首选)               | 安装 `bwrap` 包 + 支持用户命名空间 | 敏感目录完全不可见（不是权限拒绝，而是不存在） |
| **Linux**   | Landlock (回退)                 | Linux 内核 5.13+                   | 内核级文件系统规则，无需额外安装               |
| **macOS**   | Seatbelt                        | macOS 自带 `sandbox-exec`          | 内核策略语言，零配置可用                       |
| **Windows** | AppContainer / Restricted Token | Windows 10+，管理员权限            | 原生 Windows 安全机制                          |

用户无需手动选择，系统会自动使用当前平台可用的最佳方案。

### 各平台安装指引

**Linux (推荐安装 Bubblewrap)**:

```bash
# Debian/Ubuntu
sudo apt install bubblewrap

# Fedora/RHEL
sudo dnf install bubblewrap

# Arch
sudo pacman -S bubblewrap

```

**macOS**: 无需安装，`sandbox-exec` 为系统自带。

**Windows**: 需以管理员身份运行 QwenPaw。

---

## 七、Sandbox 违规处理

### 7.1 什么是违规

当沙箱内的命令试图访问被禁止的路径或执行被阻断的操作时，会产生"Sandbox Violation"（沙箱违规）。

例如，命令尝试读取 `~/.ssh/id_rsa` 时：

- 在 Bubblewrap 下：路径不存在（`No such file or directory`）
- 在其他后端：返回权限拒绝（`Permission denied`）

### 7.2 用户看到什么

当检测到违规时，QwenPaw 会向用户展示一个审批卡片：

```plaintext
⚠️ Sandbox Violation — Approve Unsandboxed Execution?

Sandbox violation: Permission denied: /home/user/.ssh/id_rsa

如果你批准，此命令将在没有沙箱隔离的情况下重新执行（拥有完整的宿主机访问权限）。
内核级文件系统限制将不再生效。

[批准] [拒绝]

```

- **批准**: 命令将不带沙箱限制地重新执行
- **拒绝**: 命令被阻止，Agent 收到失败反馈

### 7.3 设计原理

Sandbox 的违规处理体现了"先限制，后升级"的理念：

1.  默认在沙箱中执行，防止意外泄露
2.  如果命令确实需要更多权限，通过用户审批升级
3.  用户在充分知情的情况下做出决策

---

## 八、执行级别与 Sandbox 的关系

QwenPaw 的治理系统有四个执行级别：

| 级别             | 行为                               | Sandbox 角色                   |
| ---------------- | ---------------------------------- | ------------------------------ |
| **OFF**          | 工具守卫完全关闭，所有调用直接执行 | 不使用                         |
| **AUTO**         | 仅被标记的调用需要审批             | 未匹配规则的命令进入沙箱       |
| **SMART** (默认) | 低风险自动放行，高风险需审批       | 未匹配规则的命令进入沙箱       |
| **STRICT**       | 所有工具调用都需要手动审批         | 无适用场景（所有命令都需审批） |

在 `AUTO` 和 `SMART` 模式下，Sandbox 作为"安全网"发挥作用——让 Agent 能高效执行日常命令，同时确保不会触及敏感区域。

---

## 九、Sandbox 的权限编译逻辑

Sandbox 的权限不是固定的，而是根据你的项目策略规则**动态编译**的：

1.  **工作区目录** — 始终可读写（Agent 需要在这里工作）
2.  **编码项目目录** — 始终可读写（如果与工作区不同）
3.  **规则中涉及的路径**:

    - 文件读取工具规则（Read/ViewImage 等）→ 路径挂载为只读
    - 文件写入工具规则（Write/Edit/Append）→ 路径挂载为可读写

4.  **敏感路径** — 无论如何都被屏蔽（见第 3.3 节列表）
5.  **环境变量** — 黑名单中的 Key 值被清空

这意味着：如果你添加了一条规则允许 Agent 读取 `/data/datasets/`，沙箱内的命令也会自动获得该目录的只读访问权限。

---

## 十、Windows 平台特殊说明

### 10.1 实现挑战

Windows 平台的进程隔离是 Code Agent 领域的已知难题。目前主流框架（如 Codex、Claude Code）在 Windows 沙箱方面的支持都不完善。核心挑战在于：Windows 实现文件隔离的主要机制是修改文件/目录的 ACL（访问控制列表），而 ACL 修改具有两个特性：

1.  **持久性** — ACL 修改直接写入 NTFS 文件系统元数据，重启后依然生效，必须显式撤销
2.  **时间开销大** — 对大目录设置可继承 ACE 时，系统需要递归传播到所有子对象（例如 Python conda 环境可能需要 60 秒以上）

### 10.2 两种实现方式

为应对上述挑战，我们提供了两种实现来尽可能减少 ACL 修改次数，根据 `allow_read_all` 参数自动选择：

**1. AppContainer 模式**（`allow_read_all=False`）

适用于严格隔离场景。利用 Windows 原生的 AppContainer 安全容器，对需要访问的路径逐个设置 ACL，由于 AppContainer 进程默认无法访问任何用户文件，只需对**要允许的路径**设置 ACL，数量较少。

**2. Write Restricted Token 模式**（`allow_read_all=True`，默认）

适用于日常开发场景。使用 `CreateRestrictedToken` API 创建带有 `WRITE_RESTRICTED` 标志的token，而同个token访问目录是默认可写不可读的，从而减少ACL设置次数。

### 10.3 创建流程与复用机制

对于 Linux/macOS，创建沙箱的开销极低（< 50ms），可以每次 Shell 调用时全新创建。而 Windows 的首次创建流程较重：

1.  创建 AppContainer Profile 或本地用户账户
2.  对工作区、挂载路径设置 ACL（耗时取决于目录大小）
3.  配置 Windows 防火墙规则（网络受限时）

因此，Windows 平台提供了**配置指纹复用机制**：系统根据 `workspace_dir`、`mounts`、`deny_paths`、`network_allow` 等参数计算 SHA256 指纹，生成确定性的沙箱名称（`qwenpaw_<fingerprint>`）。相同配置的后续调用会直接复用已有的 Profile 和 ACL，跳过整个创建流程，执行开销与 Linux/macOS 相当。只有当配置发生变化（如工作区切换、挂载路径变更）时才需要重新创建。

### 10.4 清理机制

**自动清理（正常退出）**：

QwenPaw 进程退出时，通过 `atexit` 注册的清理函数自动执行以下步骤：

1.  撤销所有已设置的文件系统 ACL
2.  删除 Windows 防火墙阻断规则
3.  删除本地用户账户（Restricted Token 模式）
4.  移除用户 Profile 目录
5.  删除磁盘上的 metadata JSON 文件

清理函数是幂等的，多次调用安全。同时会跳过属于其他仍在运行的 QwenPaw 进程的沙箱实例。

**自动清理失效的情况**：

以下场景 `atexit` 清理不会执行：

- 进程被 `SIGKILL`（`taskkill /F`）强制终止
- 调用了 `os._exit()` 直接退出
- 直接关闭终端退出

**失效后的应对措施**：

当自动清理失效时，残留的沙箱构件（ACL、用户账户、防火墙规则）会保留在系统上，再次启动QwenPaw再正常退出时也会一并清理。也可通过以下方式手动清理：

```bash
python scripts/cleanup_windows_sandbox.py

```

此脚本会扫描 `~/.qwenpaw/` 目录下的所有 metadata 文件，识别孤儿沙箱（owner 进程已不存在），并执行完整的清理流程。

---

## 十一、常见问题

### Q: 开启 Sandbox 后命令执行变慢了？

首次创建沙箱可能需要几秒钟（特别是 Windows 平台需要设置 ACL）。后续执行的额外开销很小（Linux/macOS < 50ms）。

### Q: 命令报 "Permission denied" 但我确定路径是安全的？

这说明该路径未在沙箱的可访问列表中。解决方案：

1.  添加一条策略规则明确允许访问该路径（命令将绕过沙箱直接执行）
2.  在沙箱违规时选择"批准"以本次无沙箱执行

### Q: 关闭 Sandbox 后安全性如何？

Sandbox 是安全体系的一环。关闭后仍有以下保护：

- Phase 0-2 保护正常工作（秘密文件检测、危险命令阻断、规则匹配）
- 原本会进入沙箱的命令改为弹出审批提示，由你手动决定

### Q: 我的 Linux 系统没有 Bubblewrap 也没有 Landlock，怎么办？

如果两者都不可用，沙箱会降级为 `NONE` 模式。此时原本会进入沙箱的命令会弹出审批提示（不会无条件执行）。建议安装 `bubblewrap` 以获得最佳隔离体验。

### Q: 沙箱内的命令能访问网络吗？

当前版本默认允许完整网络访问。这是因为 `pip install`、`git clone`、`npm install` 等常用操作需要联网。未来版本计划支持更精细的网络控制。

### Q: Sandbox 能否防止 Agent 执行 `rm -rf /`？

这类极端危险命令在 Phase 1.5（危险命令关键词检测）就会被直接拒绝，**早于 Sandbox 介入**。Sandbox 保护的是"看起来正常但可能触及敏感数据"的命令。

---

## 十二、功能总结

| 功能                | 状态        | 说明                                                  |
| ------------------- | ----------- | ----------------------------------------------------- |
| 文件系统读写隔离    | ✅ 已支持   | 白名单模式，只有授权路径可访问                        |
| 敏感路径自动屏蔽    | ✅ 已支持   | 20+ 个常见凭据路径默认屏蔽                            |
| 环境变量清洗        | ✅ 已支持   | API Key 等自动清空                                    |
| 命令超时强制终止    | ✅ 已支持   | 默认 60 秒，超时即杀                                  |
| 违规检测与审批升级  | ✅ 已支持   | 违规时弹出明确的用户确认                              |
| 跨平台自动适配      | ✅ 已支持   | Linux/macOS/Windows 自动选择最佳隔离方案              |
| REPL 代码强制沙箱化 | ✅ 已支持   | 模型生成的代码必须在沙箱内执行                        |
| 策略规则联动        | ✅ 已支持   | 沙箱权限根据治理规则动态编译                          |
| 配置指纹复用        | ✅ 已支持   | 相同配置免重建（Windows）                             |
| 全局开关            | ✅ 已支持   | 可随时开关，fail-safe 设计                            |
| 网络精细控制        | 🚧 部分支持 | Linux Landlock v4 支持端口级控制；其他平台仅全开/全关 |
| 进程数/内存限制     | 🚧 有限支持 | 仅 Windows Job Object 原生支持                        |
| 域名级网络过滤      | 📋 计划中   | 需代理层支持                                          |
