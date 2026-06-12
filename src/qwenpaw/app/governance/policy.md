# Governance Policy 设计文档

> 状态：设计中（2026-06-05）

## 一、设计目标

引入资源类型维度，让 policy 从一维规则列表变成 **类型感知的权限体系**：

- 不同资源类型（File / Network）有各自的默认权限
- 同一类型内，不同 tool 可以有不同的操作权限
- 支持按路径 pattern 做细粒度 override（如 memory/ 目录的特殊规则）

## 二、资源类型

三种真正不可归约的类型：

| 类型 | 代表什么 | 包含的 tool |
|------|---------|------------|
| **File** | workspace 内的文件/目录 | Read, Write, Edit, Append, Grep, Glob, SendFileToUser, ViewImage, ViewVideo, MaterializeSkill, DesktopScreenshot, SetUserTimezone |
| **Network** | 外部网络访问行为 | Browser |
| **Internal** | 内部操作，不涉及外部资源 | GetCurrentTime, GetTokenUsage, ListAgents, ChatWithAgent, SubmitToAgent, CheckAgentTask, DelegateExternalAgent |

> **Memory 和 Cache 不是独立类型** — 它们是 File 的路径子集（`memory/**`、`.cache/**`），
> 通过 File 类型内的 rules 实现不同的默认权限。

**Bash** 是特殊的 — 它可以同时操作 File 和 Network，统一走 sandbox，
在 sandbox 内同时应用文件权限和网络权限。

### 完整 Tool 清单（21 个）

| Tool | 类型 | 说明 |
|------|------|------|
| Read | File | 读取文件 |
| Write | File | 写入文件 |
| Edit | File | 编辑文件 |
| Append | File | 追加写入文件 |
| Grep | File | 文件内容搜索 |
| Glob | File | 文件名模式匹配 |
| SendFileToUser | File | 发送文件给用户（读取文件） |
| ViewImage | File | 查看图片（读取文件） |
| ViewVideo | File | 查看视频（读取文件） |
| MaterializeSkill | File | 技能物化（写入文件） |
| DesktopScreenshot | File | 桌面截图（写入截图文件） |
| SetUserTimezone | File | 设置时区（写入全局 config 文件） |
| Browser | Network | 浏览器访问 URL |
| GetCurrentTime | Internal | 获取当前时间（只读） |
| GetTokenUsage | Internal | 查询 token 用量统计（只读） |
| ListAgents | Internal | 列出可用 agent（只读） |
| ChatWithAgent | Internal | 与其他 agent 对话（下游有自己的 policy） |
| SubmitToAgent | Internal | 向其他 agent 提交后台任务（下游有自己的 policy） |
| CheckAgentTask | Internal | 检查后台任务状态（只读） |
| DelegateExternalAgent | Internal | 委托外部 ACP agent（config 层控制开关） |
| **Bash** | **Shell** | 执行 shell 命令（sandbox 兜底） |

### DelegateExternalAgent 说明

**DelegateExternalAgent** 启动外部 ACP agent（如 claude_code、qwen_code），这些外部 agent：
- 使用**自己的 tool 体系**，不经过我们的 policy 评估
- 可以执行任意文件/网络操作，我们**完全不可见**
- 只有 ACP permission request 会回调给我们

**权限控制不在 policy 层，而在 config 层**：

```
config 中 delegate_external_agent 默认 disabled
    → tool 根本不会注册，agent 无法调用
    → 不需要 policy 拦截

用户在 config 中显式 enabled
    → tool 注册，agent 可以调用
    → policy 层直接 allow（用户已经做了授权决定）
```

因此 DelegateExternalAgent 归入 **Internal 类型**，直接 allow，不走 policy 评估。
安全闸门在 config 的 enable/disable 开关，而不是 policy rules。

### 类型判定规则

类型判定由 **ToolRegistry**（第三节）负责，不再硬编码集合。
每个 tool 注册时声明自己的类型，`evaluate()` 通过 ToolRegistry 查询。

> **注意**：未注册的 tool 返回 `"unknown"` → deny（安全优先）。
> 新增 tool 时必须在 ToolRegistry 中注册，否则默认 deny。

### Internal 类型说明

以下 tool 不涉及文件路径或网络访问，属于内部操作，**直接 allow，不走 policy 评估**：

- `GetCurrentTime` — 获取当前时间（无参数，纯只读）
- `GetTokenUsage` — 查询 token 用量统计（只读 SQLite）
- `ListAgents` — 列出可用 agent（只读本地 API）
- `ChatWithAgent` — 与其他 agent 对话（下游 agent 有自己的 policy 拦截）
- `SubmitToAgent` — 向其他 agent 提交后台任务（下游 agent 有自己的 policy 拦截）
- `CheckAgentTask` — 检查后台任务状态（只读本地 API）
- `DelegateExternalAgent` — 委托外部 ACP agent（config 层控制开关，开启即 allow）

## 三、ToolRegistry — Tool 元数据注册表

ToolRegistry 是 tool 元数据的**单一真相源**，集中管理每个 tool 的类型、target 参数等信息。
替代目前散落在 `tool_adapter.py` 中的 `FILE_TOOLS`、`_TARGET_PARAM_MAP` 等多个硬编码映射。

### 3.1 核心接口

```python
class ToolRegistry:
    """Tool 元数据注册表。"""

    def register(
        self,
        tool_name: str,        # policy 层的 tool 名，如 "Read"
        tool_type: str,        # "file" | "network" | "shell" | "internal"
        target_param: str,     # target 参数名，如 "file_path"、"command"
    ) -> None:
        """注册一个 tool。"""

    def get_type(self, tool_name: str) -> str:
        """返回 tool 的类型。未注册返回 "unknown"。"""

    def get_target_param(self, tool_name: str) -> str:
        """返回 tool 的 target 参数名。"""

    def python_to_policy_name(self, python_name: str) -> str:
        """将 python 函数名映射为 policy tool 名。"""
```

### 3.2 注册示例

```python
registry = ToolRegistry()

# File 类
registry.register("Read",    "file", "file_path")
registry.register("Write",   "file", "file_path")
registry.register("Edit",    "file", "file_path")
registry.register("Append",  "file", "file_path")
registry.register("Grep",    "file", "pattern")
registry.register("Glob",    "file", "pattern")
registry.register("SendFileToUser", "file", "file_path")
registry.register("ViewImage",      "file", "file_path")
registry.register("ViewVideo",      "file", "file_path")
registry.register("MaterializeSkill", "file", "")
registry.register("DesktopScreenshot", "file", "path")
registry.register("SetUserTimezone",   "file", "timezone")

# Network 类
registry.register("Browser", "network", "url")

# Shell 类
registry.register("Bash", "shell", "command")

# Internal 类
registry.register("GetCurrentTime",        "internal", "")
registry.register("GetTokenUsage",         "internal", "")
registry.register("ListAgents",            "internal", "")
registry.register("ChatWithAgent",         "internal", "agent_id")
registry.register("SubmitToAgent",         "internal", "agent_id")
registry.register("CheckAgentTask",        "internal", "task_id")
registry.register("DelegateExternalAgent", "internal", "runner")
```

### 3.3 与评估流程的关系

ToolRegistry 不是绕过 governance 的后门，而是 **evaluate() 内部使用的辅助**。
所有 tool 都走 governance pipeline，evaluate() 内部通过 ToolRegistry 判断类型做快速路径：

```
evaluate(tool_name, target, ...):
    type = registry.get_type(tool_name)

    if type == "unknown":
        return DENY                    # 未注册的 tool → 安全优先

    if type == "internal":
        return ALLOW                   # 内部 tool → 快速路径，但仍经过 evaluate()

    # file / network / shell → 正常规则匹配
    ① builtin_rules → 命中则返回
    ② user_rules   → 命中则返回
    ③ 全局 fallback
```

**关键点**：Internal tools 也经过 evaluate()，只是 evaluate() 内部快速返回 ALLOW。
不存在绕过 governance pipeline 的路径。

### 3.4 替代现有硬编码

| 现有代码（tool_adapter.py） | ToolRegistry 替代 |
|---|---|
| `FILE_TOOLS` / `NETWORK_TOOLS` 等集合 | `register()` + `get_type()` |
| `_TARGET_PARAM_MAP` | `get_target_param()` |
| `_TOOL_NAME_OVERRIDES`（python 名 → policy 名） | `python_to_policy_name()` |
| `_python_name_to_policy_tool_name()` | `python_to_policy_name()` |
| `_extract_target()` | 内部调用 `get_target_param()` |

### 3.5 与 policy.yaml 的关系

```
ToolRegistry:  tool 是什么（类型、参数名）     → 静态，代码层注册
policy.yaml:   tool 能做什么（规则、默认权限）  → 动态，用户/approve 产生
```

两者解耦。ToolRegistry 告诉 evaluate() "这个 tool 是 file 类型，target 参数是 file_path"，
evaluate() 根据这个信息去匹配 policy.yaml 中的规则。

## 四、policy.yaml 结构

Policy 用**一个文件**，分两个 section：

```
~/.qwenpaw/policies/<workspace>/
└── policy.yaml
```

```yaml
version: "1.0"

# ═══════════════════════════════════════════════════
# Section 1: builtin_rules（系统内置，agent 不可修改）
# ═══════════════════════════════════════════════════
# 分两类：
#   资源保护：*(pattern) — 匹配所有 tool，action: ask
#   命令保护：Bash(pattern) — 只挡特定命令，action: deny
#
# 这段由系统初始化时写入，agent 的 add_rule / remove_rule
# 只能操作 user_rules，不能碰 builtin_rules。

builtin_rules:
  # ── 资源保护（任何 tool 触碰都要问）──
  - match: "*(.env*)"
    action: ask
    reason: "环境变量文件包含密钥/凭证"
  - match: "*(**/.ssh/**)"
    action: ask
    reason: "SSH 凭证目录"
  - match: "*(**/*.pem)"
    action: ask
    reason: "私钥文件"
  - match: "*(**/*.key)"
    action: ask
    reason: "私钥文件"

  # ── 高危命令（硬墙，不可放行）──
  - match: "Bash(rm -rf /)"
    action: deny
    reason: "根目录删除"
  - match: "Bash(sudo *)"
    action: deny
    reason: "禁止提权"
  - match: "Bash(chmod 777 *)"
    action: deny
    reason: "过度放开权限"


# ═══════════════════════════════════════════════════
# Section 2: user_rules（用户/approve 产生，可修改）
# ═══════════════════════════════════════════════════

user_rules:
  # memory 目录特殊规则
  - match: "Write(memory/**)"
    action: deny

  # cache 目录宽松规则
  - match: "*(.cache/**)"
    action: allow

  # 用户显式允许的路径
  - match: "Read(src/**)"
    action: allow
    grantee: default
    duration: permanent

  # 网络
  - match: "Browser(https://github.com/**)"
    action: allow
  - match: "Bash(git push *)"
    action: ask
```

> **`*(pattern)` 语法**：`*` 作为 tool 名，表示匹配所有 tool。
> 例：`*(.env*)` 会命中 `Read(.env)`、`Write(.env)`、`Bash(cat .env)` 等。
> 这样资源保护不会被换 tool 绕过。
>
> **builtin vs user_rules 的 ask 行为不同**：
>
> | 命中来源 | action | approve 后 |
> |---------|--------|-----------|
> | **builtin_rules** | ask | **不记规则**，下次还问 |
> | **builtin_rules** | deny | 硬墙，不可放行 |
> | **user_rules** | ask | 记 allow 规则（session/permanent），下次不问 |
> | **user_rules** | allow | 按规则执行 |
> | **user_rules** | deny | 除非用户手动写入，approve 流程不会自动产生 |
>
> builtin ask 每次都问，是因为这些是高风险资源 — 不应该被"记住了"就永久放行。
> 用户说"我就看一次"就放一次。
>
> **资源保护用 ask，不用 deny** — 用户可能需要一次性读 `.env` 确认配置，
> ask 允许每次手动确认，但**不自动记规则**（下次还问）。
>
> **命令保护用 deny** — `sudo`、`rm -rf /` 这类操作没有合理场景，硬墙。

### 4.1 Section 权限控制

| Section | 谁能写 | 说明 |
|---------|--------|------|
| `builtin_rules` | 系统初始化 | agent 的 add_rule / remove_rule 不可碰 |
| `user_rules` | 用户 / approve 流程 | agent approve 后的规则追加到这里 |

代码层面：`Policy.add_rule()` 只往 `user_rules` 追加，`builtin_rules` 是只读的。

### 4.2 冷启动初始化

当 `policy.yaml` 不存在或没有 `builtin_rules` / `user_rules` section 时，系统自动写入默认规则：

```
启动时：
  policy = load("policy.yaml")
  
  if not policy.builtin_rules:
      policy.builtin_rules = DEFAULT_BUILTIN_RULES  # 系统预置的保护规则
  
  if not policy.user_rules:
      policy.user_rules = DEFAULT_USER_RULES        # 系统预置的默认权限
  
  save(policy)
```

**DEFAULT_BUILTIN_RULES** 包含：
- 敏感文件保护（`.env`、`.ssh`、`.pem`、`.key`）→ ask
- 高危命令保护（`rm -rf /`、`sudo`、`chmod 777`）→ deny

**DEFAULT_USER_RULES** 包含：
- Internal 类 tool → allow（无副作用的内部操作）
- File 类 tool（workspace 内）→ allow（读写项目文件）
- Browser → allow（浏览器访问）

这样即使 `policy.yaml` 被用户删除或损坏，安全底线和基本可用性仍然生效。

### 4.3 默认 user_rules

当 `user_rules` 为空时，系统初始化以下默认规则：

```yaml
# ── Internal 类 tool（无副作用，永远可以执行）──
- match: "GetCurrentTime(*)"
  action: allow
- match: "GetTokenUsage(*)"
  action: allow
- match: "ListAgents(*)"
  action: allow
- match: "ChatWithAgent(*)"
  action: allow
- match: "SubmitToAgent(*)"
  action: allow
- match: "CheckAgentTask(*)"
  action: allow
- match: "DelegateExternalAgent(*)"
  action: allow

# ── File 类 tool（WORKSPACE_DIR 内文件操作，永远可以执行）──
- match: "Read(WORKSPACE_DIR/**)"
  action: allow
- match: "Write(WORKSPACE_DIR/**)"
  action: allow
- match: "Edit(WORKSPACE_DIR/**)"
  action: allow
- match: "Append(WORKSPACE_DIR/**)"
  action: allow
- match: "Grep(WORKSPACE_DIR/**)"
  action: allow
- match: "Glob(WORKSPACE_DIR/**)"
  action: allow

# ── Browser（暂且当做永远可以执行）──
- match: "Browser(*)"
  action: allow
```

**设计原则**：
- **Internal tool 永远可执行** — 获取时间、查询用量、列出 agent 等操作无副作用，不需要用户确认
- **File tool 限定 WORKSPACE_DIR** — 读写项目文件是 agent 的核心能力，但仅限 workspace 目录内；workspace 外的文件（如 `/etc/passwd`、`~/.bashrc`）仍走 builtin_rules 或 fallback
- **Browser 暂且永远可执行** — 后续可改为 ask 或更细粒度的域名白名单

**`WORKSPACE_DIR` 占位符**：
- 规则中 `WORKSPACE_DIR/**` 是占位符，在 `evaluate()` 时替换为实际的 workspace 路径
- `**` 表示递归匹配任意层级子目录（由 wcmatch GLOBSTAR 语义保证）
- 例：workspace 为 `/home/user/project` 时，`Read(WORKSPACE_DIR/**)` 匹配 `Read("/home/user/project/src/main.py")`
- 这样 File tool 默认规则只允许 workspace 内的文件操作，workspace 外的文件需要 builtin_rules 放行或走 fallback

**与 builtin_rules 的关系**：
- builtin_rules 优先评估，保护敏感资源（`.env`、`.ssh` 等）
- default user_rules 提供基本可用性，不会覆盖 builtin_rules 的保护
- 例：`Read(".env.production")` → builtin ask（builtin 先命中），不会被 default user_rules 的 `Read(WORKSPACE_DIR/**)` 覆盖（`.env.production` 虽在 workspace 内，但 builtin 优先级更高）

## 五、评估流程

```
Tool Call 进来
    │
    ▼
┌──────────────────────────┐
│  ① builtin_rules          │  内置保护（资源 ask / 命令 deny）
│  命中 → ASK 或 DENY        │
└─────────┬────────────────┘
          │ 未命中
          ▼
┌──────────────────────────┐
│  ② user_rules             │  用户自定义规则（含默认规则）
│  first-match-wins          │
└─────────┬────────────────┘
          │ 未命中
          ▼
┌──────────────────────────┐
│  ③ 全局 fallback           │
│  bash 类 tool → SANDBOX    │
│  其他 → ASK                │
└──────────────────────────┘
```

**优先级**：builtin_rules > user_rules > 全局 fallback

**默认 user_rules 的作用**：
- Internal 类 tool → user_rules 命中 `GetCurrentTime(*)` 等 → ALLOW
- File 类 tool → user_rules 命中 `Read(*)` / `Write(*)` 等 → ALLOW
- Browser → user_rules 命中 `Browser(*)` → ALLOW
- Bash → user_rules 无命中 → 全局 fallback → SANDBOX

### 5.1 详细流程示例

**示例 A：user_rules deny**  
`Write("memory/secret.md")`

```
① builtin_rules → 无命中（memory 路径不在内置保护中）
② user_rules   → 命中 "Write(memory/**)" → deny
→ PolicyDecision: DENY
```

**示例 B：default user_rules（File 类默认权限）**  
`Read("src/main.py")`（workspace 内）

```
① builtin_rules → 无命中
② user_rules   → 命中 "Read(WORKSPACE_DIR/**)" → allow（默认规则）
→ PolicyDecision: ALLOW
```

**示例 C：builtin ask（资源保护，防绕过）**  
`Read(".env.production")` 或 `Bash("cat .env")`

```
① builtin_rules → 命中 "*(.env*)" → ask
→ PolicyDecision: ASK（用户确认后放行，但不记规则，下次还问）
```

> `*` 匹配所有 tool（Read、Write、Bash 等），不会被换 tool 绕过。

**示例 D：builtin deny（硬墙）**  
`Bash("sudo rm -rf /")`

```
① builtin_rules → 命中 "Bash(sudo *)" → deny
→ PolicyDecision: DENY（硬墙，不可放行）
```

**示例 E：user_rules ask（可记录）**  
`Bash("git push origin main")`

```
① builtin_rules → 无命中
② user_rules   → 命中 "Bash(git push *)" → ask
→ PolicyDecision: ASK（用户确认后，记录 allow 规则，下次不问）
```

**示例 F：Bash sandbox fallback**  
`Bash("npm install")`

```
① builtin_rules → 无命中
② user_rules   → 无命中
③ 全局 fallback → bash 类 tool → SANDBOX_FALLBACK（进入 sandbox 执行）
```

## 六、Bash 的处理

Bash 不区分 File / Network 类型，统一走 sandbox：

```
Bash tool call 进来
    │
    ▼
  查 builtin_rules / user_rules 中有没有 Bash 的显式规则
    │
    ├─ 命中 → 按规则处理（allow / deny / ask）
    │
    └─ 无命中 → sandbox 兜底
                  ├─ 文件权限：由 compile_sandbox_config 编译
                  └─ 网络权限：由 sandbox_defaults 控制
```

```yaml
# 如果需要对 Bash 做显式控制，可以写在 builtin_rules 或 user_rules 中：
builtin_rules:
  - match: "Bash(rm -rf *)"
    action: deny

user_rules:
  - match: "Bash(curl *)"
    action: deny
  - match: "Bash(git push *)"
    action: ask
```

## 七、与现有实现的差异

| | 现状 (v1) | 新设计 (v2) |
|---|---|---|
| 规则结构 | 单一 `rules` 列表 | `builtin_rules` + `user_rules` 两层 |
| 默认行为 | 硬编码在 `evaluate()` 里 | builtin_rules 显式声明 + 全局 fallback |
| fallback | 全局 `SANDBOX_FALLBACK` / `ASK` | workspace 读写 ALLOW + Bash SANDBOX + 其他 ASK |
| memory/cache | 无特殊处理 | File 类型内的路径子集 |

## 八、从真实 policy.yaml 发现的问题

以下来自一份实际运行产生的 policy.yaml：

```yaml
rules:
- match: Bash(echo hello)
  action: allow, grantee: default, duration: session
- match: Bash(ls -lh)
  action: allow, grantee: default, duration: session
- match: Browser(https://www.google.com)
  action: allow, grantee: default, duration: session
- match: Browser()
  action: allow, grantee: default, duration: session
- match: Bash(npx playwright install chromium)
  action: allow, grantee: default, duration: session
- match: ViewImage()
  action: allow, grantee: default, duration: session
```

### 8.1 空 pattern = 安全漏洞

`Browser()` 和 `ViewImage()` 的 pattern 是空字符串。
用户 approve 了一次浏览器访问，系统把 `Browser()` 写进 policy —
等于对所有 URL 放行。`ViewImage()` 同理。

**修复**：approve 写入规则时，空 target 的 tool 不允许生成空 pattern 规则。
要么写精确 target，要么不写规则（下次继续 ask）。

### 8.2 精确匹配导致规则膨胀

`Bash(echo hello)` 只匹配这一条命令。用户想表达的是 "echo 类的都可以"，
但系统只记了精确的那一次。结果：

- `echo world` → 又问一次 → 又加一条规则 → policy.yaml 越来越长
- session 结束后全丢，下次重头来

**当前策略**：暂不做泛化，approve 时记录精确匹配，避免通配符带来的安全风险。
后续可根据实际使用反馈，按需开启泛化。

| 场景 | 当前行为 |
|------|---------|
| approve `echo hello` | 记 `Bash(echo hello)` |
| approve `ls -lh` | 记 `Bash(ls -lh)` |
| approve `curl https://api.example.com` | 记 `Bash(curl https://api.example.com)` |

泛化算法预留：取 target 的第一个 token 作为前缀，后面加 `*`。
高风险操作（rm、curl、git push）不泛化，保持精确。后续按需启用。

### 8.3 没有 deny 规则

6 条规则全是 allow，没有任何保护。`Write(.env*)`、`Bash(rm -rf *)` 这些
危险操作没有防御，完全靠 fallback 的 ASK 来兜底。

**修复**：policy.yaml 出厂时预置 deny 规则（built-in deny list）：

```yaml
builtin_rules:
  - match: "*(.env*)"
    action: ask
  - match: "Bash(rm -rf *)"
    action: deny
  - match: "Bash(sudo *)"
    action: deny
```

这些规则用户不能删除（或需要显式确认才能覆盖）。

### 8.4 全是 session 级，无 permanent 规则

6 条规则全是 `duration: session`，session 一结束就全丢了。
但用户的实际意图很可能是 "ls 这种命令永远不用问"。

**修复**：approve 时让用户选择 duration：

- **session** — 本次会话有效（当前默认）
- **permanent** — 持久化，下次不用再问

对于低风险高频操作（ls、cat、echo），可以默认 permanent。

### 8.5 v2 的改进总结

| 问题 | v1 行为 | v2 改进 |
|------|--------|--------|
| 空 pattern | 写入空规则，全放行 | 禁止空 pattern 规则 |
| 精确匹配 | 记原始 target | 暂记精确匹配，泛化预留 |
| 无 deny 规则 | 无预置保护 | 内置 deny list |
| 全 session | session 结束全丢 | 支持 permanent + 智能默认 |

## 九、待讨论

1. **Network 的 sandbox_defaults 粒度** — 只到端口够吗？需要域名白名单/黑名单吗？
2. **session 级规则的归属** — 用户 approve 后自动添加的规则放在 `user_rules` 中，按 tool 名区分即可
3. **compile_sandbox_config** — 现在需要同时编译文件权限和网络权限，接口需要调整
4. **规则泛化的边界** — 哪些操作可以泛化、哪些必须精确？需要一张高风险操作清单
5. **内置 deny list 的可覆盖性** — 用户能否 override 内置 deny？如果能，需要几级确认？
