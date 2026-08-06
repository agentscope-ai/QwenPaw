# QwenPaw 统一 Project Directory 改造方案

> 状态：Draft
> 交付范围：需求与技术方案，不包含产品代码实现
> 关联原型：[mockup.html](./mockup.html)

## 0. 实施 Checklist

- [x] 明确 `workspace_dir` 与 `project_dir` 的职责边界
- [x] 将 `project_dir` 推广到普通模式
- [x] 明确 Coding Mode 仅保留 UI、代码能力与 Git watchdog 差异
- [x] 定义 Agent 默认目录与 Session 覆盖优先级
- [x] 设计旧版 `coding_mode.project_dir` 配置迁移
- [x] 设计文件工具、Shell、Prompt 和 Governance 的目录解析
- [x] 设计 Chat 窗口的 Session 级目录切换
- [x] 给出后端、前端、测试与验收清单
- [x] 提供响应式 HTML mock
- [x] 需求评审
- [x] 拆分开发任务
- [x] 产品代码实现

---

## 1. 可直接提交的 GitHub Issue

### Title

feat: decouple agent workspace from project directory and support session-level project overrides

### Summary

QwenPaw 当前将 Agent 的 `workspace_dir` 同时用于内部数据存储和工具默认工作目录。Coding Mode 虽然引入了 `coding_mode.project_dir`，但该目录尚未成为所有模式共用的一等运行时概念，部分工具仍然以 `workspace_dir` 解析相对路径。

希望引入统一的 `project_dir`：

- `workspace_dir` 只负责保存 Agent 配置、记忆、会话、技能、缓存等内部数据。
- `project_dir` 是 Agent 真正执行任务的目录，普通模式和 Coding Mode 共用。
- Agent 可以配置默认 `project_dir`。
- Chat Session 可以临时覆盖默认 `project_dir`，类似 Codex 在单个会话中选择工作目录。
- Coding Mode 不再拥有独立的目录配置；它只增加 Coding UI、代码分析工具、Coding Prompt 和 Git watchdog。

### Motivation

一个长期运行的 Agent 通常需要稳定的配置与记忆空间，但它处理的项目可能频繁变化。将两者绑定会产生以下问题：

1. Agent 为了处理外部项目，被迫把内部 workspace 指向业务仓库。
2. 普通模式无法自然地在指定目录中读取文件或执行命令。
3. Coding Mode 的 `project_dir` 成为特殊分支，文件工具和 Shell 仍需依赖 Prompt 传绝对路径或显式 `cwd`。
4. 同一 Agent 的多个 Session 无法同时处理不同项目。
5. 配置、记忆与业务文件的安全边界不清晰。

### Proposed behavior

目录职责：

| 概念 | 用途 | 生命周期 |
| --- | --- | --- |
| `workspace_dir` | Agent 配置、memory、sessions、skills、cache、media 等内部数据 | Agent 级、长期稳定 |
| `project_dir` | 文件工具相对路径基准、Shell 默认 cwd、代码分析、Git 操作和项目绑定的隐藏运行文件 | Agent 默认值，可被 Session 覆盖 |

运行时优先级：

```text
有效 project_dir
  = Session project_dir
  ?? Agent project_dir
  ?? workspace_dir
```

普通模式与 Coding Mode 使用相同的有效 `project_dir`。Coding Mode 仅额外启用：

- Coding Mode 页面与 IDE 布局；
- LSP、AST 等代码理解能力；
- Coding Mode 专用系统提示；
- 当前有效项目的 Git watchdog；
- 其他明确属于 Coding Mode 的代码工作流 UI。

### Session behavior

- Chat 顶部或输入区显示当前项目目录。
- 用户可为当前 Session 选择目录。
- Session 选择持久化在服务端，刷新页面或换浏览器后仍有效。
- 用户可选择“继承 Agent 默认目录”，清除 Session 覆盖。
- 同一 Agent 的不同 Session 可以同时绑定不同项目目录。
- 目录变化从下一次 Agent turn 开始生效，不在执行中的 turn 中途切换。

### Backward compatibility

旧配置：

```json
{
  "coding_mode": {
    "enabled": true,
    "project_dir": "/repos/qwenpaw"
  }
}
```

启动迁移后：

```json
{
  "project_dir": "/repos/qwenpaw",
  "coding_mode": {
    "enabled": true
  }
}
```

迁移规则：

1. 顶层 `project_dir` 已存在时，以顶层值为准。
2. 顶层值不存在且旧 `coding_mode.project_dir` 有效时，将旧值迁移到顶层。
3. 成功持久化新配置后删除旧字段，避免长期维护双格式运行分支。
4. 路径不存在时保留迁移值并在 UI 标记为不可用，不静默回退或删除用户配置。
5. 迁移必须幂等，并通过现有配置写入锁和原子写机制落盘。

### Acceptance criteria

- 普通模式的相对文件操作默认基于有效 `project_dir`。
- 未传 `cwd` 的 Shell 命令默认在有效 `project_dir` 执行。
- Agent 内部配置、记忆、Session 和 Skill 继续保存在 `workspace_dir`。
- Session 配置覆盖 Agent 配置，清除覆盖后立即恢复继承。
- Coding Mode 开关不改变当前项目目录。
- 旧 `coding_mode.project_dir` 可自动迁移且不丢失。
- Governance 同时识别内部 workspace 和有效项目目录。
- Windows、Linux 和 macOS 路径均经过统一规范化与验证。
- 桌面端、平板和移动端均能查看并切换 Session 项目目录。

---

## 2. 核心设计决策

### 2.1 Project Directory 与 Mode 解耦

`project_dir` 不属于 Coding Mode。它是每次 Agent 运行都需要的基础上下文，与当前界面模式正交。

```text
                         +----------------------+
Agent workspace -------->| config / memory /    |
                         | sessions / skills    |
                         +----------------------+

Agent project_dir -------+
                         |
Session project_dir -----+--> Effective project_dir
                                  |
                   +--------------+--------------+
                   |              |              |
               File tools     Shell cwd      Governance
                   |              |              |
            Normal Mode      Coding Mode + Git watchdog
```

切换 Coding Mode 时：

- 不修改 Agent `project_dir`；
- 不修改 Session `project_dir`；
- 不复制或移动项目；
- 只改变 UI、工具集合、Prompt contributor 和 Git watchdog 生命周期。

### 2.2 配置结构

实际 Agent 完整配置位于 `workspace_dir/agent.json`。根 `config.json` 继续只保存 Agent 引用与 `workspace_dir`，不复制完整 Agent 配置。

建议的新 Agent 配置：

```json
{
  "id": "default",
  "workspace_dir": "/home/user/.qwenpaw/workspaces/default",
  "project_dir": "/home/user/repos/qwenpaw",
  "coding_mode": {
    "enabled": false
  }
}
```

字段规则：

- `project_dir: string | null`；
- 保存为规范化绝对路径；
- `null` 表示回退到 `workspace_dir`；
- `coding_mode.project_dir` 在迁移完成后从 schema 中移除。

不建议把通用目录继续留在 `coding_mode` 下，否则普通模式仍会依赖 Coding Mode 的配置语义。

### 2.3 Session 数据

Session 覆盖建议保存在 `ChatSpec.meta` 的受控命名空间中：

```json
{
  "meta": {
    "runtime_context": {
      "project_dir": "/home/user/repos/temporary-task"
    }
  }
}
```

选择受控命名空间而不是开放任意 `meta` 更新，避免前端覆盖其他系统元数据。

推荐提供专用接口：

```http
PUT /chats/{chat_id}/project-dir
Content-Type: application/json

{
  "project_dir": "/home/user/repos/temporary-task"
}
```

清除覆盖：

```http
DELETE /chats/{chat_id}/project-dir
```

接口响应应同时返回来源，便于 UI 明确展示继承关系：

```json
{
  "project_dir": "/home/user/repos/temporary-task",
  "source": "session",
  "agent_project_dir": "/home/user/repos/qwenpaw",
  "exists": true
}
```

新会话在获得真实 `chat_id` 前，可在首次请求中携带待绑定目录。服务端创建 Chat 后完成校验和持久化，前端不应长期依赖临时 localStorage。

### 2.4 Runtime Context

新增独立的请求上下文值：

```text
current_workspace_dir  -> 仅表示 Agent 内部空间
current_project_dir    -> 当前 turn 的有效工作目录
```

在 PRE_DISPATCH 阶段计算一次有效目录，并在整个 turn 内保持不变：

```text
session override
  -> agent config
  -> workspace fallback
  -> normalize / validate
  -> current_project_dir ContextVar
```

不要继续通过改写 `current_workspace_dir` 来模拟项目切换，否则 memory、skills、cache、approval 和审计等内部能力可能错误地写入业务仓库。

Session context 覆盖 Agent 配置只作用于本次运行快照，不回写 Agent 的默认 `project_dir`。

### 2.5 工具目录解析

以下用户工作工具的相对路径基准改为 `current_project_dir`：

- `read_file`
- `write_file`
- `edit_file`
- `append_file`
- `list_directory`
- `grep_search`
- `glob` 或其他文件搜索工具
- `execute_shell_command` 未显式传 `cwd` 时
- LSP、AST 和 Git 工具
- 其他声明为“项目文件工具”的插件工具

以下内部能力继续使用 `workspace_dir`：

- Agent 配置读取与写入
- memory
- Session state 与 Chat registry
- skills 与 skill manifest
- tool result cache 和 dialog archive
- media、driver、credentials、jobs
- access control 配置与内部审计归属

绝对路径保持原语义，不强制拼接 `project_dir`，但仍必须经过 Governance 和 sandbox 校验。

### 2.6 Prompt 与环境信息

所有模式都应注入清晰但简短的目录说明：

```text
Project directory: /home/user/repos/qwenpaw
Agent workspace: /home/user/.qwenpaw/workspaces/default
Relative file paths and shell commands resolve from the project directory.
The agent workspace stores internal QwenPaw state.
```

Coding Mode Prompt 不再要求每个文件工具都传绝对路径，也不再提示 Shell 默认落在 workspace。它只补充代码任务规则、LSP/AST 优先级、Git 行为和 IDE 交互。

### 2.7 Governance 与 Sandbox

现有 `WORKSPACE_DIR` 和 `CODING_PROJECT_DIR` 占位符可以演进为：

```text
WORKSPACE_DIR -> Agent 内部目录
PROJECT_DIR   -> 当前 Session 的有效项目目录
```

迁移阶段可以在内部重命名 `coding_project_dir` 参数为 `project_dir`。规则持久化格式如需变更，应通过一次性迁移完成，不保留长期双字段分支。

每个请求创建或解析 Governor 时必须使用当前有效 `project_dir`，不能只使用 Agent 启动时的全局目录。审计事件应同时记录：

- `workspace_dir`
- `project_dir`
- `project_dir_source`: `session | agent | workspace_fallback`
- `agent_id`
- `session_id`

### 2.8 Coding Mode 与 Git Watchdog

Coding Mode 的目录来源同样是当前有效 `project_dir`。开启 Coding Mode 后：

1. 检测该目录是否为 Git repository。
2. 若是仓库，为当前 Session 启动或复用对应的 Git watchdog。
3. Session 切换目录时停止旧目录绑定，并为新目录建立绑定。
4. 关闭 Coding Mode 时解除当前 Session 的 watchdog 绑定。
5. 普通模式不启动 watchdog，但仍可在相同 `project_dir` 使用基础文件和 Shell 工具。

如果 watchdog 是共享资源，建议以规范化后的项目路径为 key，并使用引用计数：

```text
(agent_id, normalized_project_dir) -> watcher + session references
```

这样多个 Session 指向同一仓库时不会重复监听；不同 Session 指向不同仓库时也不会互相覆盖。

### 2.9 ACP、Fork、Cron 与非 Chat 渠道

建议统一使用相同的 resolver：

```text
resolve_effective_project_dir(
    workspace_dir,
    agent_project_dir,
    session_project_dir,
    trusted_request_override,
    fork_project_dir,
)
```

优先级需要明确区分安全来源：

```text
validated fork project override
  > active mode runtime override
  > trusted ephemeral request override
  > persisted Chat Session override
  > Agent project_dir
  > workspace_dir
```

- Fork project override 必须保持最高优先级，避免子 Agent 越出系统分配的
  项目目录。
- Mission 等模式可以提供经过系统校验的运行目录覆盖，但不能改写
  Session 或 Agent 保存的 `project_dir`。
- ACP 可以把外部 project path 作为受信请求覆盖，但不应自动写入 Agent 默认配置。
- Cron 没有 Chat Session 时使用任务级目录；未指定则继承 Agent 默认目录。
- IM 等非 Chat UI 渠道默认继承 Agent 目录，后续可通过命令或渠道元数据扩展。

### 2.10 Mission Mode

Mission 不能被当作“工具 base dir 改完后自动生效”的模块。当前实现显式使用
`ctx.workspace_dir`：

- 在 `<workspace_dir>/missions/<mission_id>` 创建 `loop_config.json`、
  `prd.json`、`progress.txt` 和 `task.md`；
- 使用 `workspace_dir` 做 Git repository 检测；
- 把 `workspace_dir` 写进 Mission Prompt，作为需要探索的源项目；
- `/mission status` 和 `/mission list` 从 workspace 下扫描任务。

因此统一 `project_dir` 时需要主动调整 Mission 的目录模型。

#### 目录分类

建议保留三类目录，并把 Mission 运行状态放在项目内的隐藏目录：

| 目录 | 用途 | 建议位置 |
| --- | --- | --- |
| `mission_state_dir` | PRD、进度、任务描述、恢复状态和运行配置 | `<project_dir>/.qwenpaw/missions/<mission_id>` |
| `source_project_dir` | Mission 启动时绑定的用户项目 | 启动时的有效 `project_dir` |
| `mission_run_dir` | Worker 实际修改文件的项目目录 | 固定为 Mission 启动时的 source project |

`loop_config.json`、`prd.json`、`progress.txt` 和 `task.md` 属于当前项目的
Mission 运行上下文，统一放进项目的 `.qwenpaw/missions/<mission_id>/`。
这样 Agent 的文件工具以 `project_dir` 为 base 时，可以直接使用相对路径：

```text
.qwenpaw/missions/<mission_id>/loop_config.json
.qwenpaw/missions/<mission_id>/prd.json
.qwenpaw/missions/<mission_id>/progress.txt
.qwenpaw/missions/<mission_id>/task.md
```

Agent 级 Mission 默认参数 `running.loop.mission` 仍属于 Agent 配置，继续
保存在 workspace 下的 `agent.json`；只有一次 Mission 的实例状态跟随项目。

Mission 配置建议记录：

```json
{
  "workspace_dir": "/home/user/.qwenpaw/workspaces/default",
  "source_project_dir": "/home/user/repos/qwenpaw",
  "mission_state_dir": ".qwenpaw/missions/mission-001",
  "mission_run_dir": "/home/user/repos/qwenpaw",
  "session_id": "console:user:session",
  "current_phase": "execution"
}
```

`mission_state_dir` 建议持久化为相对 `source_project_dir` 的路径。这样项目
目录整体移动后，Mission 状态仍可解析；`workspace_dir` 只用于标识 Agent，
不作为 Mission 文件工具的路径基准。

#### 生命周期

1. `/mission` 启动时解析一次有效 `project_dir`，保存为
   `source_project_dir`。
2. Git 检测、仓库根目录识别和初始代码探索使用
   `source_project_dir`，不再使用 `workspace_dir`。
3. Mission 状态文件写入
   `<source_project_dir>/.qwenpaw/missions/<mission_id>`。
4. `mission_run_dir` 固定等于 `source_project_dir`，不再创建其他项目副本
   或额外执行目录。
5. Worker 的文件工具和 Shell 默认目录使用 `mission_run_dir`。
6. Controller 以 `source_project_dir` 为工具 base，通过
   `.qwenpaw/missions/<mission_id>/...` 相对路径访问 PRD 和进度文件，
   不要求 Agent 拼接 workspace 绝对路径。
7. `/mission status` 和 `/mission list` 在当前有效项目的
   `.qwenpaw/missions` 下扫描；跨项目历史应由单独的 Agent 索引记录，而
   不是重新扫描 workspace 下的旧 Mission 目录。
8. Mission 恢复时从 `loop_config.json` 恢复固定的
   `source_project_dir` 和 `mission_run_dir`，不能重新读取 Session
   当前目录后静默切换项目。

#### 隐藏目录与 Git

`.qwenpaw/` 虽然是隐藏目录，仍然会出现在 Git untracked 状态中。创建首个
Mission 时必须避免反复污染仓库状态。建议按以下顺序处理：

1. 如果仓库自己的 `.gitignore` 已包含 `.qwenpaw/`，不做任何修改。
2. 默认优先写入仓库本地的 `.git/info/exclude`，加入 `.qwenpaw/`，避免
   修改用户受版本控制的 `.gitignore`。
3. 非 Git 项目不需要 ignore 操作。
4. 如果 `.git/info/exclude` 不可写，在 UI 和 Mission 启动响应中明确提示，
   不静默修改 `.gitignore`。

`.qwenpaw/` 中不得存放凭据、Agent memory 或其他跨项目隐私数据；它只保存
与该项目 Mission 直接相关、用户可以检查和删除的运行文件。

#### Session 切换约束

运行中的 Mission 必须固定项目快照。用户在 Mission 活跃时切换 Session
目录有两种产品选择：

- 推荐：允许修改 Session 的“下一次默认目录”，但当前 Mission 继续使用
  已固定的 source/run dir，并在 UI 明确提示 Mission 不受影响；
- 更保守：Mission 活跃时禁用目录切换，要求先停止 Mission。

不允许正在执行的 Mission 在下一 turn 静默跳到另一个项目。Mission 结束后，
后续普通 turn 恢复使用最新的 Session `project_dir`。

用户删除 `.qwenpaw/missions/<mission_id>` 等同于删除该 Mission 的项目侧
运行状态。恢复流程必须把“状态已删除”作为明确终止状态，不能回退到另一个
项目或 workspace 中同名的 Mission。

---

## 3. 前端方案

### 3.1 Chatbox 入口

在 Chatbox 输入区的操作栏显示紧凑目录标签，放在附件等上下文操作旁边：

```text
[folder] qwenpaw  [Session]
```

- 显示目录 basename，完整路径放在 Tooltip。
- `Session` 表示当前会话覆盖。
- `Agent default` 表示继承 Agent 配置。
- 路径失效时显示错误状态，但不静默切换目录。
- 目录标签描述下一条消息的执行上下文，因此不放在右上角 Header。
- Chat Header 只保留会话标题、Coding Mode 和全局会话操作。

点击目录标签打开选择面板：

1. 继承 Agent 默认目录；
2. 为当前 Session 指定目录；
3. 最近使用的目录；
4. 浏览本地目录；
5. 应用或取消。

### 3.2 Coding Mode

Coding Mode Toggle 与目录选择器彼此独立：

- 切换 Mode 不改变目录标签。
- Coding Mode 中目录面板额外显示 Git repository 状态。
- 非 Git 目录允许继续使用 Coding Mode，只是不启动 Git watchdog。

### 3.3 响应式

- Desktop：目录标签位于 Chatbox 左下方的操作栏。
- Tablet：目录标签保留 basename，隐藏来源文字。
- Mobile：Chatbox 保留文件夹图标和 basename；选择面板改为底部抽屉。
- 路径文本必须允许中间省略，不能撑破 Chatbox。

### 3.4 可访问性

- 所有图标使用 Lucide React。
- 目录标签使用真实 `button`。
- 面板支持键盘导航、Escape 关闭和焦点回收。
- 状态不能只依靠颜色，必须同时显示文字或图标。
- 不使用 emoji 作为状态或操作图标。

---

## 4. 后端改造点

以下是后续实现时的建议落点，不代表本次已修改代码。

| 模块 | 改造 |
| --- | --- |
| `config/config.py` | 在 Agent 配置增加顶层 `project_dir`，移除 Coding Mode 内的目录语义 |
| 配置 migration | 将旧 `coding_mode.project_dir` 一次性迁移到顶层 |
| `config/context.py` | 新增 `current_project_dir` ContextVar |
| request setup hook | 解析 Session、Agent、ACP 和 fork 的有效目录 |
| `runtime/builder.py` | 所有模式使用统一目录；Coding Mode 仅决定附加能力 |
| `agents/tools/file_io.py` | 相对路径改为基于 `current_project_dir` |
| `agents/tools/file_search.py` | 搜索基准改为有效项目目录 |
| `agents/tools/shell.py` | 默认 cwd 改为有效项目目录 |
| Governance | 使用每次请求的 workspace + project 双目录上下文 |
| Chat models/repository | 持久化 Session project override |
| Chat API | 增加受控的目录查询、设置和清除接口 |
| Console request | 服务端将 Session 目录合并进可信 runtime context |
| Coding Mode | 移除独立目录配置，只保留 UI、代码工具、Prompt 与 watchdog |
| Mission Mode | 状态写入 project 的隐藏目录，直接在启动时固定的 source project 工作 |
| Frontend Chat | 增加目录标签、选择面板和失效状态 |

---

## 5. 配置迁移细节

伪代码：

```python
if config.project_dir is None and config.coding_mode.project_dir:
    config.project_dir = normalize(config.coding_mode.project_dir)

remove config.coding_mode.project_dir
persist_atomically(config)
```

必须覆盖以下情况：

| 顶层值 | 旧值 | 结果 |
| --- | --- | --- |
| 无 | 有效路径 | 迁移旧值 |
| 无 | 当前不存在路径 | 迁移并标记 unavailable |
| 有 | 有 | 保留顶层值，删除旧字段并记录迁移日志 |
| 有 | 无 | 保持不变 |
| 无 | 无 | `null`，运行时回退 workspace |

迁移只负责配置结构，不创建、复制或删除项目目录。

---

## 6. 测试计划

### 6.1 Python 单元测试

- Agent `project_dir` 的序列化与反序列化。
- 旧 Coding Mode 配置的迁移矩阵。
- resolver 的完整优先级矩阵。
- 不存在、文件而非目录、相对路径和跨平台路径处理。
- File I/O 相对路径基于 project，内部存储仍基于 workspace。
- Shell 默认 cwd 与显式 cwd。
- Session 设置、清除和继承。
- Governance 同时获得 workspace 与 effective project。
- Coding Mode 开关不修改目录。
- Git watchdog 按目录共享、切换和释放。
- Fork project override 不被 Session override 覆盖。
- Mission 的 Git 检测和代码探索使用 source project，而不是 workspace。
- Mission 状态文件保存在 source project 的 `.qwenpaw/missions`。
- Mission 状态文件可通过 project-relative path 访问，无需 workspace 绝对路径。
- Mission 恢复后继续使用启动时固定的 source/run dir。
- Mission 活跃期间修改 Session 目录不会让正在运行的任务跨项目跳转。
- Git 项目通过 `.git/info/exclude` 忽略 `.qwenpaw/`，不默认修改
  `.gitignore`。

### 6.2 集成测试

- 两个 Session 使用同一 Agent、不同项目并发执行。
- Session override 在服务重启后仍存在。
- 新会话首次请求携带目录并成功持久化。
- Agent 默认目录变化不影响已有 Session override。
- 清除 override 后继承最新 Agent 默认值。
- 普通模式与 Coding Mode 对同一相对路径得到相同文件。
- Mission 从 Session project 启动，在项目隐藏目录保存状态并可正确恢复。
- ACP 和 Cron 使用各自的有效目录。

### 6.3 前端测试

- 目录来源与标签展示。
- Session override 设置、清除和错误回滚。
- 临时会话 ID 到真实 Chat ID 的目录选择迁移。
- Coding Mode Toggle 不改变目录。
- 路径失效状态。
- Desktop、Tablet、Mobile 布局。
- 键盘操作与焦点管理。

---

## 7. 分阶段实施建议

### Phase 1：配置和 Resolver

- 新增顶层 `project_dir`。
- 完成旧配置一次性迁移。
- 建立统一 resolver 和 `current_project_dir`。

### Phase 2：工具与安全层

- 切换文件、搜索与 Shell 的默认目录。
- 更新 Prompt、Governor、sandbox 和审计。
- 完成普通模式回归。

### Phase 3：Session Override

- 扩展 Chat 持久化与专用 API。
- 将 Session 配置注入每个 turn。
- 处理新会话首次发送。

### Phase 4：Coding Mode 收敛

- 删除 Coding Mode 独立目录逻辑。
- 保留 UI、代码工具、Prompt 和 Git watchdog。
- 调整 watchdog 为 Session 有效目录感知。

### Phase 5：Frontend

- 实现 Chat 目录标签与选择面板。
- 补齐响应式、错误状态和可访问性。

---

## 8. 风险与处理

| 风险 | 处理 |
| --- | --- |
| 把 workspace ContextVar 直接替换成 project | 新增独立 ContextVar，内部存储显式使用 workspace |
| 任意客户端伪造目录 | Session 值由服务端持久化并注入；临时覆盖需要可信来源和校验 |
| Session 切换时正在执行 | 当前 turn 使用不可变快照，下一 turn 生效 |
| Mission 跨 turn 时 Session 已切换目录 | Mission 启动时固定 source/run dir，结束后才恢复 Session 最新目录 |
| 旧路径失效导致静默写错位置 | UI 标记 unavailable，禁止静默回退 |
| Governor 在 Agent 启动时固化目录 | 按 request/session 构建或解析项目策略 |
| 多 Session 重复 Git 监听 | 规范化路径作为 key，并使用引用计数 |
| `.qwenpaw/` 污染 Git 状态 | 优先写入 `.git/info/exclude`，不默认修改项目 `.gitignore` |
| 项目移动导致绝对状态路径失效 | `mission_state_dir` 保存为相对 source project 的路径 |
| 用户删除项目侧 Mission 状态 | 明确终止该 Mission，不跨项目或回退 workspace 查找 |
| Windows 路径与大小写差异 | 使用平台感知的规范化和比较，不使用字符串前缀判断父子关系 |
| 配置长期双格式 | 只做一次性迁移，迁移后使用单一新 schema |

---

## 9. Definition of Done

- [x] Issue 需求获得确认
- [x] 旧配置迁移具有单测并可幂等执行
- [x] 普通模式与 Coding Mode 共用统一有效项目目录
- [x] Coding Mode 只保留 UI、代码工具、Prompt 和 Git watchdog 差异
- [x] 所有项目文件工具和 Shell 使用正确基准目录
- [x] Agent 内部数据未写入 project directory
- [x] Session override 可设置、持久化、清除和跨重启恢复
- [x] Mission 状态位于 project 隐藏目录，并可通过相对路径访问和恢复
- [x] Governance、sandbox、audit 获得正确的双目录上下文
- [ ] Windows、Linux、macOS 测试通过
- [ ] Python 单测通过率 100%
- [ ] 前端单测、构建和响应式检查通过
