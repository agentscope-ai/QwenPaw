# 安全

QwenPaw 内置了安全功能，保护你的 Agent 在运行过程中产生的不安全行为和不安全技能的影响。这些功能在控制台 **设置 → 安全** 中配置，也可以通过 `config.json` 进行设置。

## 概述

QwenPaw 的安全系统由五个核心安全层组成:

```
安全架构:
├─ 工具守卫 (Tool Guard) — 运行时工具调用检测
│  基于 YAML 正则规则与引号感知的 Shell 规避守卫检测危险命令、注入与恶意操作
│
├─ 文件防护 (File Guard) — 敏感文件访问控制
│  阻止 Agent 访问受保护的文件和目录
│
├─ 沙箱隔离 (Sandbox) — 操作系统内核级执行隔离
│  利用平台原生机制 (Seatbelt / bubblewrap / Landlock / AppContainer) 将 Shell 命令
│  限制在受限的文件系统视图内执行
│
├─ 技能扫描器 (Skill Scanner) — 技能安全预检
│  在技能启用前扫描恶意代码、硬编码密钥和安全威胁
│
└─ 访问策略 (Access Policy) — 声明式访问策略
   控制谁可以在什么条件下调用哪些能力
   支持工具级粒度和来源感知规则
```

**附加功能**: Web 登录认证 — 为控制台提供可选的身份验证保护

**核心概念**:

- **工具守卫** 在执行前实时检查工具调用，结合 YAML 正则规则与专用的 Shell 规避守卫检测危险模式
- **文件防护** 独立运行，保护敏感文件和目录免受未授权访问
- **沙箱隔离** 在操作系统内核强制的隔离边界内执行 Shell 命令，将文件系统访问限制为仅已声明的路径
- **技能扫描器** 在技能启用前运行，检测恶意代码和安全威胁
- **访问策略** 对每次能力调用评估其来源、身份和目标——最终决定放行(allow)、拒绝(deny)或请求人工审批(ask)
- **Web 登录认证** (可选) 控制对控制台界面的访问

---

## 工具守卫

**工具守卫**在 Agent 调用工具**之前**扫描工具参数,检测危险命令、路径遍历、数据外泄等危险模式,阻止潜在的恶意操作。

### 工作原理

1. 当 Agent 调用工具时,工具守卫会检查相关参数。检测主要针对 **`execute_shell_command`**：内置 **YAML 规则**(正则签名)与 **`ShellEvasionGuardian`**(针对混淆与解析差异的引号状态分析)。
2. 二者共同识别危险模式,例如:
   - `rm -rf /` — 危险的文件删除
   - SQL 注入相关片段
   - 命令替换 `$(...)` 或 `` `...` ``(Shell 规避守卫还会在单引号外分析此类模式)
   - 路径遍历 `../`
   - 特权提升 `sudo`、`su`
   - 反向 Shell、Fork 炸弹、标志位混淆、Unicode 空白绕过等
     (具体覆盖范围以内置 YAML 规则、Shell 规避守卫与自定义规则为准。)
3. 每条规则有独立的严重级别(CRITICAL、HIGH、MEDIUM、LOW、INFO)
4. 当发现 CRITICAL 或 HIGH 级别问题时:在控制台等带会话的交互环境中,工具调用会进入待审批流程,由你选择批准或拒绝;在无会话上下文的场景下,发现会记入日志,调用仍可能继续执行 — 若需更严格限制,可使用 `denied_tools` 禁止特定工具或调整规则。

### 配置

在 `config.json` 中:

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "guarded_tools": null,
      "denied_tools": [],
      "custom_rules": [],
      "disabled_rules": [],
      "shell_evasion_checks": {
        "command_substitution": false,
        "obfuscated_flags": false,
        "backslash_escaped_whitespace": false,
        "backslash_escaped_operators": false,
        "newlines": false,
        "comment_quote_desync": false,
        "quoted_newline": false
      }
    }
  }
}
```

| 字段                   | 说明                                                                                                                                                                                                                                                                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `enabled`              | 启用或禁用工具守卫。也可通过环境变量 `QWENPAW_TOOL_GUARD_ENABLED` 设置(优先级高于配置文件)。                                                                                                                                                                                                                                               |
| `guarded_tools`        | 指定守护范围:<br>• `null`(默认) — 守护所有内置工具<br>• `[]` — 不守护任何工具<br>• `["tool_a", "tool_b"]` — 仅守护列出的工具                                                                                                                                                                                                               |
| `denied_tools`         | 无条件阻止的工具列表:列在其中的工具**无论参数如何**均不可调用(自动拒绝,不提供审批)。                                                                                                                                                                                                                                                       |
| `custom_rules`         | 用户自定义正则规则(格式见下文)。                                                                                                                                                                                                                                                                                                           |
| `disabled_rules`       | 要禁用的内置 YAML 规则 ID 列表(仅作用于 `TOOL_CMD_*` 规则)。                                                                                                                                                                                                                                                                               |
| `shell_evasion_checks` | Shell 规避守卫的逐项开关。字典类型,key 为检查名,value 为 `true`/`false`。**默认全部关闭(`false`)。** 可在控制台 设置 → 安全 → 工具防护 中切换,也可在此处配置。可用的 key:`command_substitution`、`obfuscated_flags`、`backslash_escaped_whitespace`、`backslash_escaped_operators`、`newlines`、`comment_quote_desync`、`quoted_newline`。 |

#### 自定义规则格式

每条自定义规则是一个包含以下字段的 JSON 对象:

```json
{
  "id": "CUSTOM_RULE_ID",
  "tools": ["execute_shell_command"],
  "params": ["command"],
  "category": "command_injection",
  "severity": "HIGH",
  "patterns": ["pattern1", "pattern2"],
  "exclude_patterns": ["safe_pattern"],
  "description": "规则检测内容的简要描述",
  "remediation": "如何修复或避免此问题"
}
```

| 字段               | 类型            | 必填   | 说明                                                    |
| ------------------ | --------------- | ------ | ------------------------------------------------------- |
| `id`               | string          | **是** | 规则的唯一标识符(建议使用大写字母加下划线)              |
| `tools`            | string 或 array | 否     | 规则适用的工具名称。空数组或省略表示"所有工具"          |
| `params`           | string 或 array | 否     | 要扫描的参数名称。空数组或省略表示"所有字符串参数"      |
| `category`         | string          | **是** | 威胁类别(见下文可用类别)                                |
| `severity`         | string          | **是** | 严重级别: `CRITICAL`、`HIGH`、`MEDIUM`、`LOW` 或 `INFO` |
| `patterns`         | array           | **是** | 用于匹配危险模式的正则表达式(不区分大小写)              |
| `exclude_patterns` | array           | 否     | 排除的正则表达式(不应触发规则的安全模式白名单)          |
| `description`      | string          | 否     | 威胁的可读描述                                          |
| `remediation`      | string          | 否     | 如何修复或避免该问题的指导                              |

**可用威胁类别**: `command_injection`、`data_exfiltration`、`path_traversal`、`sensitive_file_access`、`network_abuse`、`credential_exposure`、`resource_abuse`、`prompt_injection`、`code_execution`、`privilege_escalation`

**自定义规则示例**:

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "custom_rules": [
        {
          "id": "BLOCK_PRODUCTION_DB_ACCESS",
          "tools": ["execute_shell_command"],
          "params": ["command"],
          "category": "sensitive_file_access",
          "severity": "CRITICAL",
          "patterns": ["psql.*prod", "mysql.*production"],
          "description": "防止直接访问生产数据库",
          "remediation": "改用只读副本或测试数据库"
        },
        {
          "id": "WARN_NPM_GLOBAL_INSTALL",
          "tools": ["execute_shell_command"],
          "params": ["command"],
          "category": "resource_abuse",
          "severity": "MEDIUM",
          "patterns": ["npm\\s+install\\s+-g", "npm\\s+i\\s+-g"],
          "exclude_patterns": ["npm\\s+install\\s+-g\\s+(typescript|eslint)"],
          "description": "警告全局 npm 安装",
          "remediation": "在项目依赖中本地安装包"
        }
      ]
    }
  }
}
```

### 执行级别（approval_level）

每个 Agent 都有一个 `approval_level` 字段(在 `agent.json` 中),控制工具守卫对发现的处理方式:

| 级别       | 行为                                         |
| ---------- | -------------------------------------------- |
| **STRICT** | 所有工具调用执行前均需人工审批               |
| **SMART**  | 低风险工具调用自动放行,高风险调用需审批      |
| **AUTO**   | 仅被守卫规则标记的工具调用需审批(默认)       |
| **OFF**    | 该 Agent 的工具守卫关闭,所有工具调用直接执行 |

在 `agent.json` 中配置:

```json
{
  "approval_level": "AUTO"
}
```

也可以在控制台 **设置 → 智能体** 中对应 Agent 的配置卡片中修改。

### 控制台管理

在控制台 **设置 → 安全 → 工具防护** 标签页中,你可以:

![tool guard](https://img.alicdn.com/imgextra/i1/O1CN01aAqcPv290Ldjj8NNi_!!6000000008005-2-tps-3822-2070.png)

- **启用/禁用工具守卫** — 总开关,关闭后所有工具调用不做检查
- **选择守护范围** — 留空守护所有工具,或指定需要守护的工具列表
- **设置禁止工具** — 配置无条件阻止的工具,这些工具完全不可调用
- **管理规则** — 查看、添加、编辑、禁用规则:
  - **内置规则** — 系统预设的安全规则,可以单独禁用某条规则
  - **自定义规则** — 添加组织特定的检测规则,支持正则表达式、严重级别设置
  - **规则预览** — 点击预览查看规则的详细模式和说明
- **保存配置** — 修改后点击"保存"按钮持久化配置;**更改立即生效无需重启**

### 内置规则列表

工具守卫包含以下内置检测规则(针对 `execute_shell_command` 工具):

**命令注入与文件操作（HIGH）：**

| 规则 ID                       | 检测目标                 | 说明                               |
| ----------------------------- | ------------------------ | ---------------------------------- |
| `TOOL_CMD_DANGEROUS_RM`       | `rm` 命令                | 检测可能导致数据丢失的文件删除操作 |
| `TOOL_CMD_DANGEROUS_MV`       | `mv` 命令                | 检测可能移动或覆盖文件的操作       |
| `TOOL_CMD_UNSAFE_PERMISSIONS` | `chmod -R 777`、`chattr` | 全局权限变更或设置不可变标志       |

**低级别磁盘操作（CRITICAL）：**

| 规则 ID                   | 检测目标                          | 说明                           |
| ------------------------- | --------------------------------- | ------------------------------ |
| `TOOL_CMD_FS_DESTRUCTION` | `mkfs`、`dd of=/dev/`、块设备写入 | 检测低级别磁盘格式化或擦除命令 |

**资源滥用（CRITICAL/HIGH）：**

| 规则 ID                    | 严重级别 | 检测目标                                        | 说明                         |
| -------------------------- | -------- | ----------------------------------------------- | ---------------------------- |
| `TOOL_CMD_DOS_FORK_BOMB`   | CRITICAL | Fork 炸弹 `:(){ :\|:& };:`、`kill -9 -1`        | 检测 Fork 炸弹和批量进程终止 |
| `TOOL_CMD_SYSTEM_REBOOT`   | CRITICAL | `reboot`、`shutdown`、`halt`、`init 0/6`        | 终止主机系统                 |
| `TOOL_CMD_SERVICE_RESTART` | HIGH     | `systemctl restart/stop`、`service ... restart` | 管理或中断系统服务           |
| `TOOL_CMD_PROCESS_KILL`    | HIGH     | `pkill`、`killall`、`kill`（排除 `kill $$`）    | 终止可能关键的进程           |

**代码执行（CRITICAL/HIGH）：**

| 规则 ID                       | 严重级别 | 检测目标                                                                       | 说明                                                      |
| ----------------------------- | -------- | ------------------------------------------------------------------------------ | --------------------------------------------------------- |
| `TOOL_CMD_PIPE_TO_SHELL`      | CRITICAL | `curl/wget ... \| bash/sh` 模式                                                | 下载并立即执行远程脚本                                    |
| `TOOL_CMD_OBFUSCATED_EXEC`    | HIGH     | `base64 -d \| bash` 模式                                                       | 执行 base64 编码的命令                                    |
| `TOOL_CMD_IFS_INJECTION`      | HIGH     | `$IFS`、`${...IFS...}`                                                         | 利用字段分隔符拆分 token,绕过简单词边界类检测             |
| `TOOL_CMD_CONTROL_CHARS`      | CRITICAL | 不可见控制字符(含 NUL 等)                                                      | 可能在简单扫描下隐藏元字符                                |
| `TOOL_CMD_UNICODE_WHITESPACE` | HIGH     | NBSP、表意空格等 Unicode 空白                                                  | 解析器与 Bash 对空白处理不一致时的绕过面                  |
| `TOOL_CMD_PROC_ENVIRON`       | HIGH     | `/proc/self/environ`、`/proc/<pid>/environ`                                    | 读取进程环境块(密钥、令牌),常与执行或外泄链配合           |
| `TOOL_CMD_JQ_SYSTEM`          | HIGH     | 含 `system(` 的 `jq`                                                           | 在 jq 程序中嵌入 Shell 执行                               |
| `TOOL_CMD_JQ_FILE_FLAGS`      | HIGH     | `jq` 的 `-f`/`--from-file`、`--rawfile`、`--slurpfile`、`-L`、`--library-path` | 任意读文件或加载外部 jq 代码路径                          |
| `TOOL_CMD_ZSH_DANGEROUS`      | HIGH     | `zmodload`、`emulate ... -c`、`sysopen`/`zpty`/`ztcp`、`zf_*`、`fc ... -e` 等  | zsh 内建提供的原始 I/O、网络或执行能力,绕过常见路径型检查 |

**权限提升（CRITICAL/HIGH）：**

| 规则 ID                         | 严重级别 | 检测目标                                     | 说明                               |
| ------------------------------- | -------- | -------------------------------------------- | ---------------------------------- |
| `TOOL_CMD_PRIVILEGE_ESCALATION` | CRITICAL | `sudo`、`su`、`doas`、`pkexec`               | 使用提权命令执行操作               |
| `TOOL_CMD_SYSTEM_TAMPERING`     | HIGH     | `crontab`、`authorized_keys`、`/etc/sudoers` | 访问定时任务、SSH 密钥或 sudo 配置 |

**网络滥用（CRITICAL）：**

| 规则 ID                  | 检测目标                           | 说明                      |
| ------------------------ | ---------------------------------- | ------------------------- |
| `TOOL_CMD_REVERSE_SHELL` | `/dev/tcp`、`nc -e`、`socat EXEC:` | 建立反向 Shell 或网络隧道 |

### Shell 命令绕过守卫

引擎还会对 `execute_shell_command` 运行 **`ShellEvasionGuardian`**。它维护引号状态,弥补仅靠行级或纯正则易漏的混淆(例如单引号外的命令替换、`` ` ``、`$()`、Zsh 形式、`$'...'`/`$"..."` 技巧、反斜杠转义的空白或 shell 操作符——对常见 `find ... -exec ... {} \;` 有例外——可能拆分命令的裸换行或 `\r` 且跳过 heredoc、`#` 注释与引号状态不同步、引号内换行后接看似注释的行等)。上报的规则 ID(严重级别均为 **HIGH**):

| 规则 ID                              | 说明                                                    |
| ------------------------------------ | ------------------------------------------------------- |
| `SHELL_EVASION_COMMAND_SUBSTITUTION` | 单引号 `'`...`'` 外的反引号或命令/进程替换类写法        |
| `SHELL_EVASION_OBFUSCATED_FLAGS`     | ANSI-C/区域化引号、空引号标志位技巧或引号包裹的标志片段 |
| `SHELL_EVASION_BACKSLASH_WHITESPACE` | 引号外对空格或制表符的反斜杠转义                        |
| `SHELL_EVASION_BACKSLASH_OPERATOR`   | 引号外对 `; \| & < >` 前加反斜杠                        |
| `SHELL_EVASION_NEWLINE`              | 回车或未在引号内且后跟更多命令文本的换行                |
| `SHELL_EVASION_COMMENT_QUOTE_DESYNC` | 未在引号内的 `#` 注释行中出现引号字符,干扰引号跟踪      |
| `SHELL_EVASION_QUOTED_NEWLINE`       | 引号内换行且后续片段形如 `#` 注释行                     |

**配置说明:** `config.json` 中的 `disabled_rules` 仅作用于 YAML 规则 ID(一般为 `TOOL_CMD_*`),**不控制** `SHELL_EVASION_*`。Shell 规避检查通过 `shell_evasion_checks` 独立配置(见下文)。关闭工具守卫会一并停用所有守卫(含本守卫)。

**使用建议**:

- CRITICAL 级别规则建议保持启用,这些是最危险的操作
- HIGH 级别规则可根据实际使用场景调整,某些合法操作可能触发
- 可通过 `disabled_rules` 禁用不适用的 YAML `TOOL_CMD_*` 规则
- 可通过 `shell_evasion_checks` 逐个控制 Shell 规避检查的开关(默认全部关闭)
- 可通过 `custom_rules` 添加组织特定的安全规则

---

## 文件防护

**文件防护**阻止 Agent 工具访问敏感文件和目录。它在**每次工具调用**时自动运行,扫描所有文件路径相关参数,执行敏感路径的拒绝列表保护。

### 工作原理

文件防护作为"文件路径守卫者"运行于工具守卫引擎中,与规则守卫者协同工作:

1. **独立运行** — 即使工具守卫被禁用(`tool_guard.enabled = false`),只要 `file_guard.enabled = true`,文件防护仍会检查每个工具调用
2. **多场景检测** — 针对不同工具采用不同的路径提取策略:
   - **已知文件工具**(`read_file`、`write_file`、`edit_file` 等) — 直接检查 `file_path` 参数
   - **Shell 命令**(`execute_shell_command`) — 从命令字符串中提取文件路径,包括重定向目标(如 `>`、`>>`、`<`)
   - **其他工具** — 扫描所有看起来像文件路径的字符串参数
3. **路径规范化** — 自动处理相对路径、`~` 扩展,转换为绝对路径后匹配
4. **目录递归保护** — 以 `/` 结尾的路径视为目录,其下所有文件和子目录都会被递归阻止
5. **阻止机制** — 发现匹配时,工具调用以 HIGH 级别发现被阻止

**默认保护**: `{WORKING_DIR}.secret/` 目录(存储 API 密钥、认证凭据和提供商配置)默认包含在敏感文件列表中。默认情况下,`WORKING_DIR` 为 `~/.qwenpaw/`,完整路径为 `~/.qwenpaw.secret/`。

### 配置

在 `config.json` 中:

```json
{
  "security": {
    "file_guard": {
      "enabled": true,
      "sensitive_files": ["~/.ssh/", "/etc/passwd", "~/.qwenpaw.secret/"]
    }
  }
}
```

| 字段              | 说明                                                                                                                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `enabled`         | 启用或禁用文件防护(默认: `true`)。关闭后不再检查文件路径。                                                                                                                           |
| `sensitive_files` | 要阻止工具访问的文件/目录路径列表。支持:<br>• 绝对路径: `/etc/passwd`<br>• 相对路径: `secrets/api_keys.json`<br>• 用户目录: `~/.ssh/`<br>• 目录保护: 以 `/` 结尾表示递归保护整个目录 |

**路径处理规则**:

- 相对路径会相对于当前工作空间目录解析
- `~` 会自动展开为用户主目录
- 所有路径都会规范化为绝对路径进行匹配
- 目录路径(以 `/` 结尾)会递归保护其下所有内容

### 控制台管理

在控制台 **设置 → 安全 → 文件防护** 标签页中,你可以:

![file guard](https://img.alicdn.com/imgextra/i4/O1CN01EqUuWs1sPDgDvsbeV_!!6000000005758-2-tps-3822-2070.png)

- **启用/禁用文件防护** — 独立开关,可在不影响工具守卫其他功能的情况下单独控制文件保护
- **查看保护列表** — 表格形式展示所有受保护的路径:
  - 文件夹图标标识目录保护
  - 文件图标标识单文件保护
  - 橙色标签突出显示目录类型
- **添加保护路径**:
  - 在输入框中输入文件或目录路径
  - 支持绝对路径、相对路径、用户目录(`~`)
  - 以 `/` 结尾表示保护整个目录及其子内容
  - 按 Enter 键或点击"添加"按钮确认
- **移除保护** — 点击删除按钮移除不再需要保护的路径
- **保存配置** — 修改后点击“保存”按钮持久化到 `config.json`；**更改立即生效**
- **重置更改** — 点击“重置”恢复到上次保存的状态

---

## 沙箱隔离

**沙箱隔离**为 Shell 命令提供操作系统内核级别的执行隔离。当治理层决定某个工具调用应在沙箱中运行时，命令将在受限的文件系统视图中执行，只有明确声明的路径才可访问。

### 工作原理

沙箱位于治理决策与实际命令执行之间：

```
工具调用流程:
  1. 工具守卫  → 模式检测 (执行前检查，拦截已知危险模式)
  2. 治理引擎  → 策略评估 (ALLOW / DENY / ASK / SANDBOX_FALLBACK)
  3. 沙箱隔离  → 内核强制执行隔离 (运行时)
  4. 结果返回  → 违规检测 + 输出捕获
```

**职责分工**：

- **工具守卫** = 执行前静态模式匹配（基于正则，快速，无隔离）
- **文件防护** = 路径级访问控制（阻止特定文件/目录）
- **沙箱隔离** = 运行时内核隔离（命令在物理上无法看到或写入白名单之外的路径）

即使命令通过了工具守卫和文件防护的检查，沙箱仍然确保它无法在操作系统层面访问其声明的文件系统视图之外的任何内容。

### 支持平台

QwenPaw 在启动时自动检测最佳可用的沙箱后端：

| 平台    | 后端                   | 机制                                             | 检测方式                                             |
| ------- | ---------------------- | ------------------------------------------------ | ---------------------------------------------------- |
| macOS   | **Seatbelt**           | `sandbox-exec` + S-expression 策略文件           | PATH 上存在 `sandbox-exec`                           |
| Linux   | **Bubblewrap**（首选） | Mount namespace + User namespace + PID namespace | `bwrap` 二进制 + user namespace 支持                 |
| Linux   | **Landlock**（回退）   | Landlock LSM 内核模块 (5.13+)                    | 内核版本 + LSM 探测 + ABI 系统调用                   |
| Windows | **AppContainer**       | AppContainer profile + `icacls` ACL 强制访问控制 | Windows 10+（build 10240）+ PATH 上存在 `icacls.exe` |
| 所有    | **None**               | 无隔离（直接执行）                               | 无可用后端时使用                                     |

**Linux 探测优先级**：bubblewrap > Landlock > None。如果 `bwrap` 已安装且 user namespace 可用，则选择 bubblewrap。否则回退到 Landlock（如果内核支持）。

**能力对比**：

| 能力              | Seatbelt (macOS)  | Bubblewrap (Linux)    | Landlock (Linux) | AppContainer (Windows) |
| ----------------- | ----------------- | --------------------- | ---------------- | ---------------------- |
| 文件系统读控制    | 支持              | 支持                  | 支持             | 支持                   |
| 文件系统写控制    | 支持              | 支持                  | 支持             | 支持                   |
| deny_paths 不可见 | 否（访问拒绝）    | 是（未挂载）          | 否（访问拒绝）   | 否（访问拒绝）         |
| PID 命名空间隔离  | 否                | 支持                  | 否               | 否                     |
| 最小化 /dev       | 支持（白名单）    | 支持（合成 devtmpfs） | 否               | 不适用                 |
| 网络控制          | 支持（允许/拒绝） | 计划中                | 否（需 ABI v4）  | 支持（允许/拒绝）      |

### 隔离模型

沙箱使用 **默认拒绝 + 白名单** 模型：

1. **基础文件系统**：默认情况下，所有内容要么只读（`allow_read_all=True`），要么不可见（`allow_read_all=False`）
2. **可写路径**：只有明确声明的 `mounts`（`writable=True`）才可写入（通常仅为 workspace 目录）
3. **拒绝路径**：`deny_paths` 中的路径即使在其他情况下可读也会被阻止：
   - Bubblewrap：路径完全未挂载（不可见，`ls` 不显示任何内容）
   - Landlock/Seatbelt：访问返回 `Permission denied`
4. **最小化 /dev**：只提供必要的设备节点（`/dev/null`、`/dev/zero`、`/dev/urandom`、`/dev/tty`）
5. **PID 隔离**（仅 Bubblewrap）：沙箱内的进程无法看到宿主机 PID

### 配置

沙箱配置由治理策略引擎自动编译生成，用户通常无需手动设置。关键字段如下：

| 字段              | 类型   | 默认值                      | 说明                                                           |
| ----------------- | ------ | --------------------------- | -------------------------------------------------------------- |
| `mode`            | string | 自动检测                    | `seatbelt`、`bubblewrap`、`landlock`、`appcontainer` 或 `none` |
| `workspace_dir`   | string | Agent workspace             | 主工作目录（始终可写）                                         |
| `mounts`          | list   | 仅 workspace                | 已声明的文件系统路径及其权限                                   |
| `deny_paths`      | list   | `["~/.ssh", "~/.aws", ...]` | 需要阻止的敏感路径                                             |
| `allow_read_all`  | bool   | `true`                      | 为 true 时，默认整个文件系统可读（deny-list 模式）             |
| `network_allow`   | list   | `["*"]`                     | 网络访问策略（当前允许所有）                                   |
| `timeout_seconds` | int    | `30`                        | 最大执行时间，超时后终止                                       |
| `env_vars`        | dict   | `{}`                        | 沙箱进程的额外环境变量                                         |

**MountSpec** 条目：

| 字段         | 类型   | 默认值  | 说明                           |
| ------------ | ------ | ------- | ------------------------------ |
| `path`       | string | —       | 文件系统路径                   |
| `writable`   | bool   | `false` | 允许写入                       |
| `executable` | bool   | `true`  | 允许执行二进制文件（仅 macOS） |

### 违规检测

当沙箱内的命令尝试访问其允许视图之外的路径时，操作系统内核会阻止该操作。QwenPaw 通过匹配 stderr 模式来检测这些违规：

| 平台         | 检测模式                                                                                 |
| ------------ | ---------------------------------------------------------------------------------------- |
| Seatbelt     | `deny(N) file-read-data`、`Sandbox:`、`sandbox-exec:`、`Operation not permitted`         |
| Bubblewrap   | `Permission denied`、`bwrap:`、`Operation not permitted`、`EACCES`                       |
| Landlock     | `Permission denied`、`Operation not permitted`                                           |
| AppContainer | `Access is denied`、`error 5`、`0x80070005`、`Permission denied`、`拒绝访问`、`权限不足` |

检测到违规时：

1. 执行结果中的 `sandbox_violation` 字段会被填充
2. 治理层记录违规日志
3. 根据策略，Agent 可能会提示用户审批以扩展访问权限

### 当前限制

- **网络隔离**：当前版本未实现。所有沙箱进程均可完全访问网络，不受 `network_allow` 设置影响。网络命名空间隔离（bubblewrap 的 `--unshare-net`）已计划。
- **资源限制**：`max_processes` 和 `max_memory_mb` 字段存在于配置中，但当前无后端强制执行。
- **Windows AppContainer**：首次 ACL 设置需要管理员权限。AppContainer profile 会被保留以供相同配置的后续调用复用。
- **Windows 最低版本要求**：AppContainer 需要 **Windows 10 版本 1507（build 10240）** 或更高版本。更早的 Windows 版本（Windows 7、8、8.1）不支持 AppContainer 隔离机制，将回退到 `mode=none`（无隔离）。
- **Windows 系统目录 ACL 限制**：`icacls` ACL 设置无法修改某些受保护系统目录的权限，例如 `C:\Program Files`、`C:\Program Files (x86)`、`C:\Windows` 和 `C:\Windows\System32`。这些目录受 Windows 资源保护（WRP）和 TrustedInstaller 所有权保护。不过这通常不构成问题，因为 Windows 10+ 默认已为内置的 `ALL APPLICATION PACKAGES` SID（`S-1-15-2-1`）授予了这些路径的读取和执行权限，AppContainer 进程无需显式 ACL 授权即可读取系统二进制文件和库。
- **deny_paths 文件级别 (Bubblewrap)**：`deny_paths` 中的单个文件会显示为空（绑定到 `/dev/null`）而非不存在。目录级别的 deny 使用 `--tmpfs` 真正不可见。

### 故障排除

**macOS: `sandbox-exec` 报告语法错误**

Seatbelt 策略使用 S-expression 语法。如果看到 `expecting ')'` 错误，通常表示策略文件格式错误。检查 `deny_paths` 条目是否包含特殊字符（引号、换行符、反斜杠）。

**Linux: bwrap 探测失败**

Bubblewrap 需要 user namespace 支持。检查：

```bash
# 确认 bwrap 已安装
which bwrap

# 检查 user namespace 是否启用
cat /proc/sys/kernel/unprivileged_userns_clone
# 应输出: 1

# 手动探测
bwrap --ro-bind / / --dev /dev --unshare-user --unshare-pid --proc /proc -- /bin/echo OK
```

如果 user namespace 被禁用（Docker 容器、部分安全加固内核），QwenPaw 会自动回退到 Landlock。

**Windows: AppContainer ACL 设置失败**

AppContainer 的 `icacls` ACL 操作需要管理员权限。如果看到 ACL 设置失败的警告：

1. 以管理员身份运行 QwenPaw（右键 → 以管理员身份运行）
2. 确认 `icacls.exe` 在 PATH 中（所有 Windows 版本均自带）
3. 使用 `scripts/cleanup_windows_sandbox.py` 清理旧的 AppContainer profile 和 ACL

**Windows: 不满足最低版本要求**

AppContainer 需要 Windows 10（build 10240）或更高版本。如果探测输出中出现 `"AppContainer requires Windows 10+"` 消息，说明当前运行的 Windows 版本不受支持。请升级到 Windows 10 或更高版本以使用沙箱隔离。在旧版系统上，QwenPaw 将回退到 `mode=none`（无内核隔离）。

**Windows: 系统目录（如 Program Files）ACL 授权失败**

如果看到 `icacls` 对 `C:\Program Files` 或 `C:\Windows` 等路径报告警告，这是正常现象。这些目录由 TrustedInstaller 拥有并受 Windows 资源保护（WRP）——即使管理员也无法修改其 ACL。沙箱不需要对这些路径进行显式授权，因为 Windows 10+ 已通过内置的 `ALL APPLICATION PACKAGES` ACE 为所有 AppContainer 进程提供了读取+执行权限。如果你的工作流需要对 `Program Files` 下的路径进行写操作，请考虑使用其他工作目录，或添加一个指向用户拥有的位置的可写挂载点。

**确认沙箱是否激活**

检查治理日志（`qwenpaw.log`）中是否包含：

```
governance decision: tool=Bash target="..." action=sandbox_fallback sandbox=bubblewrap ...
```

`sandbox=` 字段显示实际使用的后端。如果显示 `-`，则该调用未启用沙箱。

---

## 技能扫描器

**技能扫描器**在技能被启用或安装前自动扫描安全威胁,检测命令注入、数据外泄、硬编码密钥、社会工程等风险模式,保护系统免受恶意技能影响。

### 工作原理

1. **触发时机** — 当执行以下操作时,扫描器会在激活技能前运行:
   - 创建新技能
   - 启用已禁用的技能
   - 从 Skill Hub 导入技能
2. **扫描机制**:
   - 使用 YAML 正则签名规则检测技能文件中的危险模式
   - 默认使用模式分析器(PatternAnalyzer),基于内置签名库
   - 支持自定义扫描策略(ScanPolicy)和规则
3. **智能缓存** — 扫描结果基于文件修改时间(mtime)缓存,未更改的技能不会重复扫描
4. **超时保护** — 可配置的超时时间(默认 30 秒)防止扫描无限阻塞
5. **文件安全**:
   - 自动跳过符号链接,防止路径遍历攻击
   - 验证所有文件真实路径在技能目录边界内
   - 默认跳过二进制和归档文件(图片、字体、压缩包等)

### 扫描模式

| 模式             | 行为                                                                     |
| ---------------- | ------------------------------------------------------------------------ |
| **拦截(Block)**  | 扫描并阻止不安全的技能。操作失败并显示详细错误,技能无法启用。            |
| **仅提醒(Warn)** | 扫描并记录发现,但允许技能继续使用。显示警告通知,记录到扫描告警中。(默认) |
| **关闭(Off)**    | 完全禁用扫描,所有技能直接通过。                                          |

**配置优先级**: 环境变量 `QWENPAW_SKILL_SCAN_MODE` > 控制台设置 > `config.json`

可选值: `block`、`warn`、`off`

### 扫描告警

所有扫描发现(拦截和提醒)都记录在**扫描告警**标签页中。在控制台你可以:

- **查看详细发现** — 点击"眼睛"图标查看每条告警的具体发现:
  - 发现标题和描述
  - 问题所在的文件路径和行号
  - 匹配的危险模式
- **加入白名单** — 点击"盾牌"图标将技能加入白名单,跳过该特定内容版本的后续扫描
- **删除告警** — 点击"垃圾桶"图标删除单条告警记录
- **清除全部** — 点击"清除全部"按钮批量删除所有告警记录

告警记录包含:

- 技能名称
- 操作类型(已拦截/已警告)
- 发现时间
- 详细发现列表

### 白名单

白名单中的技能跳过安全扫描。白名单机制基于**内容哈希验证**:

- 每条白名单记录包含:
  - 技能名称
  - SHA-256 内容哈希(基于技能所有文件内容计算)
  - 添加时间
- **版本锁定** — 如果技能文件发生任何变化,内容哈希改变,白名单条目失效,技能将被重新扫描
- **移除白名单** — 点击删除按钮移除白名单条目,系统会自动禁用该技能并提示重新扫描

白名单功能适用于:

- 已验证安全的自研技能
- 误报的技能(扫描器错误识别)
- 需要绕过特定检测的可信技能

### 控制台管理

在控制台 **设置 → 安全 → 技能扫描器** 标签页中,你可以:

![skill scanner](https://img.alicdn.com/imgextra/i4/O1CN01c4UGLh1Yd9PbL2bZC_!!6000000003081-2-tps-3822-2070.png)

**配置区**:

- **扫描模式** — 下拉选择"拦截"、"仅提醒"或"关闭"
- **超时时间** — 设置单个技能扫描的最大时长(5-300秒),超时后停止扫描

**扫描告警标签页** (有告警时显示数字角标):

![alarm](https://img.alicdn.com/imgextra/i1/O1CN013IUVEk26x1X9MtFen_!!6000000007727-2-tps-3822-2070.png)

- 查看所有拦截和警告记录
- 点击眼睛图标查看详细发现
- 点击盾牌图标将技能加入白名单
- 点击垃圾桶图标删除单条记录
- 使用"清除全部"按钮批量删除

**白名单标签页** (有条目时显示数字角标):

![white list](https://img.alicdn.com/imgextra/i3/O1CN01aQ0miE1kzO1vB34Vu_!!6000000004754-2-tps-3822-2070.png)

- 查看所有已加入白名单的技能
- 显示技能名称、内容哈希(前16字符)、添加时间
- 点击删除按钮移除白名单(会自动禁用技能)

**注意**: 扫描模式和超时的修改会自动保存并**立即生效**,无需点击额外的保存按钮。

### 自定义规则(高级)

对于需要深度定制的场景,扫描器支持编程方式配置:

扫描器使用 `src/qwenpaw/security/skill_scanner/rules/signatures/` 中的 YAML 规则文件。你可以通过 YAML 策略文件自定义扫描策略:

```python
from qwenpaw.security.skill_scanner import SkillScanner
from qwenpaw.security.skill_scanner.scan_policy import ScanPolicy

policy = ScanPolicy.from_yaml("my_org_policy.yaml")
scanner = SkillScanner(policy=policy)
```

内置签名类别:

- `command_injection` — 命令注入
- `data_exfiltration` — 数据外泄
- `hardcoded_secrets` — 硬编码密钥
- `prompt_injection` — 提示词注入
- `social_engineering` — 社会工程
- `supply_chain_attack` — 供应链攻击
- `obfuscation` — 代码混淆
- `resource_abuse` — 资源滥用
- `unauthorized_tool_use` — 未授权工具使用

#### YAML 签名格式

每个 YAML 签名文件包含一组检测规则:

```yaml
# my_custom_signatures.yaml
- id: CUSTOM_API_KEY_LEAK
  category: hardcoded_secrets
  severity: CRITICAL
  patterns:
    - "api_key\\s*=\\s*['\"][a-zA-Z0-9]{32,}['\"]"
    - "API_KEY\\s*=\\s*['\"][a-zA-Z0-9]{32,}['\"]"
  exclude_patterns:
    - "example"
    - "test_api_key"
    - "<your_api_key_here>"
  file_types: [python, javascript, typescript]
  description: "检测到代码中的硬编码 API 密钥"
  remediation: "使用环境变量或密钥管理系统"

- id: CUSTOM_DANGEROUS_NETWORK_CALL
  category: data_exfiltration
  severity: HIGH
  patterns:
    - "requests\\.post\\([^)]*attacker\\.com"
    - "urllib\\.request\\.urlopen\\([^)]*suspicious"
  file_types: [python]
  description: "可疑的网络请求到不可信域名"
  remediation: "审查并白名单允许的域名"
```

**字段说明**:

| 字段               | 类型   | 必填   | 说明                                                                      |
| ------------------ | ------ | ------ | ------------------------------------------------------------------------- |
| `id`               | string | **是** | 签名的唯一标识符(建议使用大写字母加下划线)                                |
| `category`         | string | **是** | 威胁类别(见上文列表)                                                      |
| `severity`         | string | **是** | 严重级别: `CRITICAL`、`HIGH`、`MEDIUM`、`LOW` 或 `INFO`                   |
| `patterns`         | array  | **是** | 用于匹配危险模式的正则表达式(不区分大小写)                                |
| `exclude_patterns` | array  | 否     | 要排除的模式(减少误报)                                                    |
| `file_types`       | array  | 否     | 要扫描的文件类型: `python`、`javascript`、`typescript`、`bash`、`json` 等 |
| `description`      | string | 否     | 威胁的可读描述                                                            |
| `remediation`      | string | 否     | 如何修复问题的指导                                                        |

**使用提示**:

- 部署前用真实代码样本测试模式
- 使用 `exclude_patterns` 过滤文档和测试中的误报
- 指定 `file_types` 以提高性能和减少误报
- 从 `severity: MEDIUM` 开始,观察结果后调整

### 配置

在 `config.json` 中：

```json
{
  "security": {
    "skill_scanner": {
      "mode": "block",
      "timeout": 30,
      "whitelist": []
    }
  }
}
```

---

## 访问策略

**访问策略**是一个声明式策略引擎，对每次能力调用裁定放行(allow)、拒绝(deny)或请求人工审批(ask)。每个服务客户端都拥有独立的访问策略，支持工具级粒度以及来源感知和身份感知的规则。当前已在 MCP 中实现，设计上可扩展到未来的其他协议集成。

### 工作原理

1. **独立策略配置** — 每个服务客户端(e.g. MCP client)拥有独立的访问策略。每次能力调用时都会评估策略。
2. **三种效果**：
   - `allow` — 调用立即执行
   - `deny` — 调用被阻止，Agent 收到错误
   - `ask` — 调用被挂起，等待用户在控制台中批准或拒绝
3. **两级粒度**：
   - **客户端级** — 默认效果应用于该客户端的所有能力
   - **工具级** — 为特定工具覆盖默认效果（例如大多数工具放行，但禁止 `dangerous_tool`）
4. **来源感知规则** — 规则可根据请求来源（如仅来自控制台、仅来自钉钉）和请求者身份（如特定用户）进行匹配
5. **优先级裁决** — 多条规则匹配时，最具体的规则优先（见下文[策略裁决](#策略裁决)）

### 策略模型

每个客户端的策略由 `default_effect` 和一组 `rules` 组成：

| 字段             | 说明                                                         |
| ---------------- | ------------------------------------------------------------ |
| `default_effect` | 无规则匹配时的效果：`allow`、`deny` 或 `ask`（默认: `deny`） |
| `rules`          | 按优先级评估的策略规则列表                                   |

**策略规则字段**：

| 字段        | 类型   | 说明                                                                                    |
| ----------- | ------ | --------------------------------------------------------------------------------------- |
| `subject`   | string | 调用者身份模式。类型前缀格式：`user:xxx`、`session:xxx`、`channel:xxx`、`*`（匹配所有） |
| `effect`    | string | `allow`、`deny` 或 `ask`                                                                |
| `target`    | object | `{ kind, name }` — 目标能力。`kind`: `"tool"` 或 `"*"`。`name`: 工具名 或 `"*"`         |
| `principal` | object | 来源匹配（可选，见下文）                                                                |

**Principal 字段**（来源感知匹配）：

| 字段            | 说明         | 示例                             |
| --------------- | ------------ | -------------------------------- |
| `source_type`   | 请求来自哪里 | `"channel"`                      |
| `source_value`  | 具体来源     | `"console"`、`"dingtalk"`、`"*"` |
| `subject_type`  | 来源内的范围 | `"all"`、`"user"`                |
| `subject_value` | 具体身份     | `"admin"`、`"*"`                 |

### 策略裁决

工具被调用时，策略引擎评估所有匹配规则并选择最具体的一条：

**匹配条件**（以下所有条件均需满足）：

1. 规则的 `subject` 匹配请求的任一身份（用户、会话、渠道）
2. 规则的 `principal` 匹配请求来源
3. 规则的 `target` 匹配被调用的工具

**优先级顺序**（从高到低）：

| 优先级 | 维度      | 更具体者优先                                            |
| ------ | --------- | ------------------------------------------------------- |
| 1      | 目标名称  | 精确工具名 > 通配符 `*`                                 |
| 2      | 目标类型  | `"tool"` > `"*"`                                        |
| 3      | Principal | 指定字段越多 > 指定字段越少                             |
| 4      | Subject   | 精确（`user:admin`）> 类型通配（`user:*`）> 全局（`*`） |
| 5      | 严格程度  | `deny` > `ask` > `allow`                                |

若无规则匹配，则应用 `default_effect`。

**示例**：

| 请求                        | 结果  | 原因                          |
| --------------------------- | ----- | ----------------------------- |
| `user:admin` 调用任意工具   | ALLOW | 精确 subject 匹配（优先级 4） |
| 任何人调用 `dangerous_tool` | DENY  | 精确目标名称（优先级 1）      |
| 控制台用户调用 `safe_tool`  | ALLOW | 目标名称 + principal 双重匹配 |
| 钉钉用户调用 `other_tool`   | ASK   | 无规则匹配 → `default_effect` |

### 审批流程

当策略裁决结果为 `ask` 时：

1. 工具调用被**挂起** — Agent 暂停执行
2. 控制台中出现**审批卡片**，显示：
   - 工具名称和参数
   - 调用者身份和来源渠道
   - 服务客户端名称
3. 用户可以**批准**或**拒绝**：
   - **批准** → 工具调用正常执行
   - **拒绝** → Agent 收到权限被拒绝的错误，向用户解释原因
4. 若超时未响应，调用将被拒绝

> **提示**: 个人使用的可信客户端，可设置 `default_effect: allow` 跳过审批。对于共享或敏感场景的部署，建议使用 `ask` 作为默认值，并显式 `allow` 可信来源。

### 在 MCP 中使用

访问策略当前可用于 MCP 客户端。每个 MCP 客户端的策略存储在其 YAML 配置文件中：

```yaml
# drivers/mcp/hello-mcp.yaml
name: hello-mcp
protocol: mcp
endpoint:
  transport: stdio
  command: python
  args: ["./mcp_servers/hello_server.py"]
  env:
    ECHO_SECRET:
      source: credential
      credential: static
      field: ECHO_SECRET
config:
  display_name: Hello MCP
  description: 本地 stdio MCP 演示服务，提供 print_content 和 get_secret_status 两个工具
enabled: true
policy:
  default_effect: ask
  rules:
    - subject: "*"
      effect: deny
      target: { kind: tool, name: get_secret_status }
```

#### 控制台管理

在控制台 **智能体 → MCP** 页面中，点击任意 MCP 客户端卡片上的**工具&权限**即可打开访问策略面板：

![access policy](https://img.alicdn.com/imgextra/i1/O1CN01HJgGjv1cQZ0TKGnfC_!!6000000003595-0-tps-3838-2076.jpg)

- **设置默认效果** — 选择客户端级别的默认策略：询问（黄色）、放行（绿色）或拒绝（红色）
- **添加客户端级规则** — 为特定来源或用户覆盖默认策略：
  - 选择来源渠道（控制台、钉钉、Telegram 等）
  - 可选限定到特定用户
  - 为该来源/用户组合设置效果
- **工具级默认** — 为单个工具设置不同的默认效果
- **工具级规则** — 为工具级默认追加来源/用户特定的覆盖规则
- **保存** — 点击"保存"持久化配置；**更改立即生效无需重启**

> **注意**: 通过 YAML 文件创建的使用高级 subject 模式（如 `user:admin`、`session:xxx`）的规则会被保留，但无法在控制台中编辑。当存在此类规则时，弹窗会显示"未管理规则"计数。

---

## 完整配置示例

以下是包含所有安全功能的完整 `config.json` 配置示例:

```json
{
  "security": {
    "tool_guard": {
      "enabled": true,
      "guarded_tools": null,
      "denied_tools": ["execute_shell_command"],
      "custom_rules": [
        {
          "id": "CUSTOM_DANGEROUS_PATTERN",
          "tools": ["write_file"],
          "params": ["content"],
          "category": "data_exfiltration",
          "severity": "HIGH",
          "patterns": ["secret_key.*=", "password.*="],
          "description": "检测文件内容中的硬编码密钥",
          "remediation": "使用环境变量或密钥管理系统"
        }
      ],
      "disabled_rules": ["TOOL_CMD_PROCESS_KILL"]
    },
    "file_guard": {
      "enabled": true,
      "sensitive_files": [
        "~/.ssh/",
        "~/.qwenpaw.secret/",
        "/etc/passwd",
        "/etc/shadow",
        ".env",
        "secrets/"
      ]
    },
    "skill_scanner": {
      "mode": "warn",
      "timeout": 30,
      "whitelist": []
    }
  }
}
```

**注意**:

- 大部分配置修改立即生效(无需重启)
- 环境变量会覆盖配置文件值(详见各章节说明)
- Docker 部署时,将配置文件挂载到 `/app/working/config.json`

---

## Web 登录认证

QwenPaw 支持可选的 Web 登录认证,保护控制台免受未授权访问。认证**默认关闭**,需要通过 `QWENPAW_AUTH_ENABLED` 环境变量显式启用。

![login](https://img.alicdn.com/imgextra/i4/O1CN01VdXCuP1tWpsl0TlQ5_!!6000000005910-2-tps-3822-2070.png)

### 工作原理

1. **启用认证** — 设置 `QWENPAW_AUTH_ENABLED=true` 并启动 QwenPaw
2. **注册流程**:
   - 首次访问时,控制台显示**注册页面**
   - 创建唯一的管理员账户(用户名 + 密码)
   - 系统采用单用户模式,专为个人使用设计
3. **登录流程**:
   - 注册完成后,后续访问显示**登录页面**
   - 输入凭据后,生成签名令牌(有效期 7 天)
   - 令牌存储在浏览器 localStorage,自动附加到所有 API 请求
4. **自动注册**(可选):
   - 设置 `QWENPAW_AUTH_USERNAME` 和 `QWENPAW_AUTH_PASSWORD` 环境变量
   - QwenPaw 启动时自动创建管理员账户,跳过网页注册
   - 适用于 Docker、Kubernetes、服务器管理面板等自动化部署场景
5. **本地免认证** — 来自本地(`127.0.0.1` / `::1`)的请求自动跳过认证,CLI 命令(`qwenpaw app`、`qwenpaw chat` 等)无需令牌即可正常工作

**安全特性**:

- 密码加盐 SHA-256 哈希存储,不存储明文
- HMAC-SHA256 签名令牌,7 天自动过期
- 仅使用 Python 标准库(`hashlib`、`hmac`、`secrets`),无外部依赖
- `auth.json` 文件以 `0o600` 权限保护(仅所有者可读写)

### 环境变量

| 变量                    | 说明                         | 是否必填 |
| ----------------------- | ---------------------------- | -------- |
| `QWENPAW_AUTH_ENABLED`  | 设为 `true` 启用认证         | **是**   |
| `QWENPAW_AUTH_USERNAME` | 自动注册时预设的管理员用户名 | 可选     |
| `QWENPAW_AUTH_PASSWORD` | 自动注册时预设的管理员密码   | 可选     |

### 认证豁免主机白名单

在 `config.json` 中,`security.allow_no_auth_hosts` 字段指定即使启用了认证也可以无需认证访问 API 的客户端 IP 地址:

```json
{
  "security": {
    "allow_no_auth_hosts": ["127.0.0.1", "::1"]
  }
}
```

| 字段                  | 类型          | 默认值                 | 说明                                                         |
| --------------------- | ------------- | ---------------------- | ------------------------------------------------------------ |
| `allow_no_auth_hosts` | array[string] | `["127.0.0.1", "::1"]` | 允许无需认证令牌即可访问 `/api/*` 路由的客户端 IP 地址列表。 |

也可以在控制台 **设置 → 安全** 中管理。

> **安全提示**: 向此列表添加非 localhost 地址意味着这些 IP 可以无需凭据访问完整 API。请谨慎使用,仅用于私有网络中的可信主机。

**配置说明**:

- `QWENPAW_AUTH_ENABLED=true` 是启用认证的唯一必需变量
- `QWENPAW_AUTH_USERNAME` 和 `QWENPAW_AUTH_PASSWORD` 成对使用:
  - 两者都设置 → 启动时自动创建管理员账户(适用于自动化部署)
  - 不设置或只设置其一 → 首次访问通过网页注册(交互式部署)
- 如果已有注册用户,自动注册环境变量会被忽略

### 启用认证

#### 脚本安装 / pip 安装

在启动前设置环境变量:

**Linux / macOS:**

```bash
# 基础启用(网页注册)
export QWENPAW_AUTH_ENABLED=true
qwenpaw app

# 或: 自动注册模式
export QWENPAW_AUTH_ENABLED=true
export QWENPAW_AUTH_USERNAME=admin
export QWENPAW_AUTH_PASSWORD=mypassword
qwenpaw app
```

如需永久生效,将 `export` 行添加到 `~/.bashrc`、`~/.zshrc` 或等效文件中。

**Windows (CMD):**

```cmd
set QWENPAW_AUTH_ENABLED=true
rem 可选: 自动注册
rem set QWENPAW_AUTH_USERNAME=admin
rem set QWENPAW_AUTH_PASSWORD=mypassword
qwenpaw app
```

**Windows (PowerShell):**

```powershell
$env:QWENPAW_AUTH_ENABLED = "true"
# 可选: 自动注册
# $env:QWENPAW_AUTH_USERNAME = "admin"
# $env:QWENPAW_AUTH_PASSWORD = "mypassword"
qwenpaw app
```

#### Docker

通过 `-e` 传递环境变量(推荐使用自动注册):

```bash
docker run -e QWENPAW_AUTH_ENABLED=true \
  -e QWENPAW_AUTH_USERNAME=admin \
  -e QWENPAW_AUTH_PASSWORD=mypassword \
  -p 127.0.0.1:8088:8088 \
  -v qwenpaw-data:/app/working \
  -v qwenpaw-secrets:/app/working.secret \
  -v qwenpaw-backups:/app/working.backups \
  agentscope/qwenpaw:latest
```

> **提示**: 不使用自动注册时,移除 `QWENPAW_AUTH_USERNAME` 和 `QWENPAW_AUTH_PASSWORD`,首次通过浏览器注册。

#### docker-compose.yml

```yaml
services:
  qwenpaw:
    image: agentscope/qwenpaw:latest
    ports:
      - "127.0.0.1:8088:8088"
    environment:
      - QWENPAW_AUTH_ENABLED=true
      - QWENPAW_AUTH_USERNAME=admin
      - QWENPAW_AUTH_PASSWORD=mypassword
    volumes:
      - qwenpaw-data:/app/working
      - qwenpaw-secrets:/app/working.secret
      - qwenpaw-backups:/app/working.backups
```

#### 环境文件 (.env)

也可以使用 `.env` 文件：

```
QWENPAW_AUTH_ENABLED=true
QWENPAW_AUTH_USERNAME=admin
QWENPAW_AUTH_PASSWORD=mypassword
```

然后通过 `--env-file .env` 传递给 Docker，或在运行 `qwenpaw app` 前在 shell 中 source 该文件。

### 关闭认证

移除或取消环境变量并重启 QwenPaw：

```bash
# Linux / macOS
unset QWENPAW_AUTH_ENABLED
qwenpaw app

# Docker — 移除 -e 参数即可。以下示例包含用于持久化的卷。
docker run -p 127.0.0.1:8088:8088 -v qwenpaw-data:/app/working -v qwenpaw-secrets:/app/working.secret -v qwenpaw-backups:/app/working.backups agentscope/qwenpaw:latest
```

### 重置密码

如果忘记密码,使用 CLI 命令重置:

```bash
qwenpaw auth reset-password
```

该命令会:

1. 显示当前注册的用户名
2. 提示输入新密码(隐藏输入,需确认两次)
3. 轮换 JWT 签名密钥,**使所有现有会话失效** — 所有已登录设备需使用新密码重新登录

**Docker 部署**:

```bash
docker exec -it <容器名> qwenpaw auth reset-password
```

**替代方案**:

如需完全重置认证系统:

```bash
# 删除认证文件
rm ~/.qwenpaw.secret/auth.json  # 或 $WORKING_DIR.secret/auth.json
# 重启 QwenPaw,下次访问时重新注册
qwenpaw app
```

### 退出登录

在控制台侧边栏底部点击**退出登录**按钮:

- 清除浏览器 localStorage 中的令牌
- 自动跳转到登录页面
- 需要重新输入凭据才能访问

**自动退出**:

- 令牌过期(7 天后)
- 令牌失效(密码重置或签名密钥轮换)
- 服务端返回 401 未授权响应

### 安全细节

| 特性           | 说明                                                                                  |
| -------------- | ------------------------------------------------------------------------------------- |
| 密码存储       | 加盐 SHA-256 哈希存储在 `auth.json` 中（不存储明文）                                  |
| 令牌格式       | HMAC-SHA256 签名载荷，7 天过期                                                        |
| 令牌存储       | 浏览器 localStorage，退出登录或收到 401 响应时清除                                    |
| 外部依赖       | 无 — 仅使用 Python 标准库（`hashlib`、`hmac`、`secrets`）                             |
| 文件权限       | `auth.json` 以 `0o600` 权限写入（仅所有者可读写）                                     |
| 本地免认证     | 来自 `127.0.0.1` / `::1` 的请求跳过认证（CLI 访问不受影响）                           |
| CORS 预检      | `OPTIONS` 请求无需认证直接放行                                                        |
| WebSocket 认证 | 令牌通过查询参数传递，仅限升级请求                                                    |
| 受保护路由     | 仅 `/api/*` 路由需要认证                                                              |
| 公开路由       | `/api/auth/login`、`/api/auth/register`、`/api/auth/status`、`/api/version`、静态资源 |
