# 安全

QwenPaw 内置了安全功能，保护你的 Agent 在运行过程中产生的不安全行为和不安全技能的影响。这些功能在控制台 **设置 → 安全** 中配置，也可以通过 `config.json` 进行设置。

## 概述

QwenPaw 的安全系统由三个核心安全层组成:

```
安全架构:
├─ 工具守卫 (Tool Guard) — 运行时工具调用检测
│  基于正则表达式检测危险命令模式、注入攻击和恶意操作
│
├─ 文件防护 (File Guard) — 敏感文件访问控制
│  阻止 Agent 访问受保护的文件和目录
│
└─ 技能扫描器 (Skill Scanner) — 技能安全预检
   在技能启用前扫描恶意代码、硬编码密钥和安全威胁
```

**附加功能**: Web 登录认证 — 为控制台提供可选的身份验证保护

**核心概念**:

- **工具守卫** 在执行前实时检查工具调用，使用正则规则检测危险模式
- **文件防护** 独立运行，保护敏感文件和目录免受未授权访问
- **技能扫描器** 在技能启用前运行，检测恶意代码和安全威胁
- **Web 登录认证** (可选) 控制对控制台界面的访问

---

## 工具守卫

**工具守卫**在 Agent 调用工具**之前**扫描工具参数,检测危险命令、路径遍历、数据外泄等危险模式,阻止潜在的恶意操作。

### 工作原理

1. 当 Agent 调用工具时,工具守卫会检查相关参数。内置正则规则主要针对 **`execute_shell_command`**。
2. 使用正则表达式规则检测危险模式,例如:
   - `rm -rf /` — 危险的文件删除
   - SQL 注入相关片段
   - 命令替换 `$(...)` 或 `` `...` ``
   - 路径遍历 `../`
   - 特权提升 `sudo`、`su`
   - 反向 Shell、Fork 炸弹等
     (具体覆盖范围以内置规则与自定义规则为准。)
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
      "disabled_rules": []
    }
  }
}
```

| 字段             | 说明                                                                                                                         |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `enabled`        | 启用或禁用工具守卫。也可通过环境变量 `QWENPAW_TOOL_GUARD_ENABLED` 设置(优先级高于配置文件)。                                 |
| `guarded_tools`  | 指定守护范围:<br>• `null`(默认) — 守护所有内置工具<br>• `[]` — 不守护任何工具<br>• `["tool_a", "tool_b"]` — 仅守护列出的工具 |
| `denied_tools`   | 无条件阻止的工具列表:列在其中的工具**无论参数如何**均不可调用(自动拒绝,不提供审批)。                                         |
| `custom_rules`   | 用户自定义正则规则(格式见下文)。                                                                                             |
| `disabled_rules` | 要禁用的内置规则 ID 列表。                                                                                                   |

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

| 规则 ID                    | 严重级别 | 检测目标                        | 说明                   |
| -------------------------- | -------- | ------------------------------- | ---------------------- |
| `TOOL_CMD_PIPE_TO_SHELL`   | CRITICAL | `curl/wget ... \| bash/sh` 模式 | 下载并立即执行远程脚本 |
| `TOOL_CMD_OBFUSCATED_EXEC` | HIGH     | `base64 -d \| bash` 模式        | 执行 base64 编码的命令 |

**权限提升（CRITICAL/HIGH）：**

| 规则 ID                         | 严重级别 | 检测目标                                     | 说明                               |
| ------------------------------- | -------- | -------------------------------------------- | ---------------------------------- |
| `TOOL_CMD_PRIVILEGE_ESCALATION` | CRITICAL | `sudo`、`su`、`doas`、`pkexec`               | 使用提权命令执行操作               |
| `TOOL_CMD_SYSTEM_TAMPERING`     | HIGH     | `crontab`、`authorized_keys`、`/etc/sudoers` | 访问定时任务、SSH 密钥或 sudo 配置 |

**网络滥用（CRITICAL）：**

| 规则 ID                  | 检测目标                           | 说明                      |
| ------------------------ | ---------------------------------- | ------------------------- |
| `TOOL_CMD_REVERSE_SHELL` | `/dev/tcp`、`nc -e`、`socat EXEC:` | 建立反向 Shell 或网络隧道 |

**使用建议**:

- CRITICAL 级别规则建议保持启用,这些是最危险的操作
- HIGH 级别规则可根据实际使用场景调整,某些合法操作可能触发
- 可通过 `disabled_rules` 配置禁用不适用的规则
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
- **保存配置** — 修改后点击"保存"按钮持久化到 `config.json`;**更改立即生效**
- **重置更改** — 点击"重置"恢复到上次保存的状态

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
5. **本地 CLI 认证** — 受保护的本地请求不再跳过认证。启用 Web 认证后,CLI 命令(`qwenpaw app`、`qwenpaw chat` 等)会在回环地址上自动附加专用的本地 CLI 令牌,因此本地自动化仍可工作,无需手动设置 `QWENPAW_API_TOKEN`(兼容旧的 `COPAW_API_TOKEN`)

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
docker run -p 127.0.0.1:8088:8088 -v qwenpaw-data:/app/working -v qwenpaw-secrets:/app/working.secret agentscope/qwenpaw:latest
```

### 重置密码

如果忘记密码,使用 CLI 命令重置:

```bash
qwenpaw auth reset-password
```

该命令会:

1. 显示当前注册的用户名
2. 提示输入新密码(隐藏输入,需确认两次)
3. 轮换 `auth.json` 中的 JWT 签名密钥和本地 CLI 令牌,**使所有现有会话失效** — 所有已登录设备和本地 CLI 自动化都需重新认证

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
| 本地 CLI 认证  | 回环地址上的 CLI 请求使用自动附加的本地 CLI 令牌；localhost 流量不会跳过认证          |
| CORS 预检      | `OPTIONS` 请求无需认证直接放行                                                        |
| WebSocket 认证 | 令牌通过查询参数传递，仅限升级请求                                                    |
| 受保护路由     | 仅 `/api/*` 路由需要认证                                                              |
| 公开路由       | `/api/auth/login`、`/api/auth/register`、`/api/auth/status`、`/api/version`、静态资源 |
