# QwenPaw 环境变量统一管理与 Console 重设计

## 1. 状态与范围

- 状态：实现完成，自动化验证通过
- 分支：`refactor/env-json-os-environ`
- 范围：现有 `envs.json`、`EnvVarLoader`、环境变量 API、MCP stdio
  子进程、LLM stream timeout、Console `/environments`
- 不包含：全局 RunningConfig、Provider 凭据与模型配置、修改宿主机环境、
  热切换工作目录、热修改已经显式保存的 Agent 配置

## 2. 最终架构结论

本期不新增 `qwenpaw.envs` 文件，不新增 version 2 schema，不新增环境变量读取
模块，也不创建第二份运行时配置缓存。

复用项目已有能力：

1. `constant.py` 启动时使用 `python-dotenv` 加载项目根目录和用户目录的
   `.env`。
2. `SECRET_DIR/envs.json` 继续使用现有 flat 加密格式，仅保存用户通过
   QwenPaw 显式配置的覆盖值。
3. `os.environ` 是进程内唯一运行时环境状态。
4. `EnvVarLoader` 是 QwenPaw 核心代码已有的无缓存、类型化
   `os.environ` 读取器。
5. 插件、Skill 和普通扩展可继续直接调用 `os.getenv()`。
6. 环境管理上层只负责 catalog、校验、权限、来源和生效策略，不接管业务
   配置对象。

Provider 的 API Key、Base URL 和模型列表继续由 `ProviderManager` 管理并保存到
`SECRET_DIR/providers/**/*.json`。它们不是进程环境变量，不进入 `envs.json`，也
不会由环境管理功能自动写入 `os.environ`。

```text
system environment + .env
             │
             ▼
        os.environ
             ▲
             │ override / restore
 encrypted flat envs.json
             │
             ├── EnvVarLoader.get_*()  (QwenPaw typed reads)
             ├── os.getenv()           (plugins and extensions)
             └── future subprocesses   (MCP, Skill, CLI)
```

## 3. 为什么不新增环境读取模块

`EnvVarLoader.get_bool/get_int/get_float/get_str` 每次调用都会读取当前
`os.environ`，已经满足动态读取和类型校验需要。

不能热更新的根因通常不是 `EnvVarLoader`，而是读取结果被模块级常量固化：

```python
VALUE = EnvVarLoader.get_float("QWENPAW_VALUE", 30.0)
```

上面的表达式只在模块 import 时执行一次。支持热更新的 consumer 必须在一次
操作开始时调用 `EnvVarLoader`，并把结果保存在本次操作的局部变量中。

因此不增加 `access.py`、typed snapshot、global running config 或 managed env
cache。插件和 QwenPaw 核心虽然分别使用 `os.getenv()` 与 `EnvVarLoader`，但读取
的是同一个底层状态。

## 4. 上层统一管控模型

环境变量 catalog 根据读取生命周期展示三类设置。

### 4.1 动态读取

当前仅包括：

- `QWENPAW_LLM_STREAM_FIRST_CONTENT_TIMEOUT`
- `QWENPAW_LLM_STREAM_IDLE_TIMEOUT`

保存后立即更新当前 QwenPaw 进程。每个新 stream 开始时通过
`EnvVarLoader.get_float()` 读取一次；已有 in-flight stream 保持自己的局部值。

### 4.2 初始化默认值

LLM retry、backoff 和 rate-limit 相关环境变量只为未显式配置的
`AgentsRunningConfig` 提供默认值。

`AgentsRunningConfig` 不再通过 `constant.py` 模块级常量间接获取这些默认值，
而是使用 Pydantic `default_factory` 调用 `EnvVarLoader`。优先级为：

```text
agent.json 显式字段 > 构造配置时的 os.environ > 代码默认值
```

环境页展示这些变量，但不允许运行期间修改，因为更新环境不应覆盖已经持久化的
Agent 配置。页面明确说明它们只影响后续构造且缺少显式字段的配置。

### 4.3 启动期设置

工作目录、secret 目录、配置文件名、容器模式等启动拓扑变量在 catalog 中展示，
但不可修改。它们必须在启动 QwenPaw 前通过系统环境或 `.env` 配置。

### 4.4 自定义变量

用户可以添加合法的非内部变量，例如 `TAVILY_API_KEY`、`HTTP_PROXY` 或某个
CLI 所需的变量。保存后：

- 当前 QwenPaw 中的 `os.getenv()` 立即可见；
- 之后启动的普通子进程自动继承；
- MCP stdio 显式取得 env store 中的变量，绕过 MCP SDK 的继承白名单；
- 已经运行的外部子进程不会被操作系统原地修改。

## 5. 持久化与优先级

继续使用现有 `SECRET_DIR/envs.json`：

- 文件保持 flat key/value 逻辑结构；
- value 使用现有 secret store 加密；
- 不改变文件名；
- 不新增格式版本；
- 不增加本分支新格式的兼容或迁移代码；
- 文件保持稀疏，缺失时继续视为 `{}`，不物化代码默认值。

运行优先级：

```text
QwenPaw envs.json 显式值 > system/.env > code default
```

启动加载 `envs.json` 时，显式值覆盖当前进程中的同名值。覆盖前记录继承值；用户
删除或重置覆盖项时，恢复该继承值。如果启动前不存在同名值，则从
`os.environ` 删除。

这一行为只修改当前 QwenPaw 进程及其未来子进程，不会修改父进程、shell profile、
Windows Registry、launchd、systemd 或机器级环境。

## 6. API

### `GET /api/envs`

返回 `envs.json` 中用户显式配置的稀疏值。

### `GET /api/envs/catalog`

返回已知变量的默认值、有效值、来源、类型、分类、是否可编辑和只读原因。

来源含义：

- `user`：存在于 `envs.json`；
- `system`：不存在用户覆盖，但当前 `os.environ` 中存在；
- `default`：两者都不存在，展示代码默认值。

### `PATCH /api/envs`

增量 upsert 请求中出现的 key。未提交的已有 key 保持不变；校验、merge 和写盘在
同一文件锁内完成。写盘成功后同步 `os.environ`。

### `PUT /api/envs`

保留项目已有的全量替换接口供已有调用方使用。新 Console 不再调用它。

### `DELETE /api/envs/{key}`

删除自定义变量并恢复继承环境值。

### `POST /api/envs/{key}/reset`

删除一个可动态修改的已知变量覆盖，并恢复 system/.env 或代码默认行为。

## 7. Console

页面分为：

1. 可实时修改的 QwenPaw 设置；
2. 初始化期与启动期只读的 QwenPaw 设置；
3. 用户显式添加的插件、Skill、CLI 和子进程变量。

LLM 分类只表示 QwenPaw 自身的 LLM 运行参数，不表示 Provider 凭据。Provider
凭据仍在模型服务配置页面中管理。

页面使用 QwenPaw 现有语义色，保持浅色/深色主题一致；状态通过文字、边框和 Lucide
图标表达，不引入其他图标库。所有新增文案覆盖 `en`、`zh`、`ja`、`ru`、
`pt-BR`、`id` 和 `vi`。

## 8. 验收 checklist

- [x] 回退此前新增的 version 2 schema、typed access 和 apply service
- [x] 不新增 `qwenpaw.envs` 或 `QWENPAW_ENVS_FILE`
- [x] 保留现有 flat 加密 `envs.json`
- [x] 新增原子增量更新能力
- [x] 用户持久化值覆盖 system/.env
- [x] 删除用户覆盖时恢复继承值
- [x] stream timeout 在每次新 stream 开始时通过 `EnvVarLoader` 读取
- [x] `AgentsRunningConfig` 使用 `default_factory + EnvVarLoader`
- [x] MCP stdio 注入受管自定义环境
- [x] Provider 凭据与模型配置不进入环境变量 catalog 或 `os.environ`
- [x] Console 分开展示动态、自定义和只读设置
- [x] Console 将全部 QwenPaw 设置连续展示，自定义变量置于其后
- [x] Console 不再调用全量 PUT 保存单项修改
- [x] 后端单元与集成测试通过
- [x] 前端页面与 locale 测试通过
- [x] Python pre-commit、前端 lint 和生产构建通过
