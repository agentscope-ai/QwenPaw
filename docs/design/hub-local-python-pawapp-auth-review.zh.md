# Hub Local Python 环境与 PawApp 浏览器鉴权修复方案

状态：方案已确认，按用户最终要求直接在 `feat/fix_hub` 实施。
基线：`feat/fix_hub` / `46829e2b8`。
范围假设：local 指 Hub 为用户分配的 `local` runtime，不是 Agent 单次工具调用的 `NoneSandbox`。以下为当前源码链路定位，尚未启动真实 Hub / 安装 Creator 做端到端复现。用户已确认实际现象：点击 QwenPaw Creator 打开后显示 `{"detail":"Not authenticated"}`；具体失败请求 URL 尚未取得。

## 1. 定位结论

### P1：Local runtime 没有自己的 Python 依赖环境

- `src/qwenpaw/hub/local_provisioner.py:162`：用 Hub 的 `sys.executable -m qwenpaw` 启动每个用户 runtime，没有创建用户 venv。
- 同文件 `runtime_environment()`（约 330 行）继承宿主 PATH、VIRTUAL_ENV、CONDA_PREFIX、PYTHONPATH，改变 HOME 不等于改变 Python 安装目标。
- `src/qwenpaw/plugins/loader.py:940` 起：普通 Python 部署用 `sys.executable -m pip install -r ...`；uv fallback 也明确指定同一解释器。
- `src/qwenpaw/hub/process_isolation.py:112` / `:175`：Linux 将宿主 Python 环境只读挂载，仅 runtime root 可写；macOS 同样只允许 runtime root 文件写入（约 322 行）。
- Creator 的 requirements 包括 oss2、imageio-ffmpeg、pypdfium2、playwright 等。宿主未预装这些依赖时，现有链路没有可靠的可写安装环境。

结果：具体错误取决于 pip 和宿主环境，可能写只读环境失败，也可能退回用户 site。即使某台机器恰好可用，也没有明确、可验证的依赖隔离契约。不能通过放开宿主 Python 写权限解决。

### P1：点击打开 QwenPaw Creator 显示 Not authenticated

用户已确认：点击打开 App 就出现原始 JSON `{"detail":"Not authenticated"}`，不是仅在使用媒体或事件流时失败。验收必须从 App 打开入口开始，不能只修 Creator 内部 API。

当前点击链路：`AppCard → AppCenter.handleAppClick → loadPawApp → 注册/选择 App 路由 → CreatorFrame → 浏览器导航加载 App HTML`。

- `console/src/pages/AppCenter/index.tsx:198`：点击先 await `loadPawApp()`，随后 pushState 并设置 activeApp；pushState 本身不发送页面请求。入口脚本已注册时 loader 还可能直接返回，因此“路由加载成功”不是资源认证成功。
- 同文件 `:149`：深链接/刷新通过 effect 直接设置 activeApp；不能只在点击 handler 里准备认证，否则刷新仍会失败。
- `console/src/pages/Settings/PawApps/index.tsx:43` / `:130`：另一入口直接用静态资源 URL 加载 iframe 或 `window.open`，同样不能携带 fetch 的 Authorization。这是源码识别出的同类缺口，不代表已确认用户走的是该入口。

以下证据说明当前 Creator iframe 导航足以造成点击后看到这段 JSON。该字符串同时存在于 Hub `require_user()` 和单机 `AuthMiddleware`，仅凭报错文本不能证明用户现场具体由哪一层返回；实施复现时必须记录失败 URL、状态码和返回层，不能把它直接判断为账号 token 已过期，也不能无证据当作另一个独立根因。

- `console/src/plugins/usePluginLoader.ts:40`：入口 JS 用携带 Bearer 的 fetch 下载，能够通过 Hub。
- `plugins/apps/qwenpaw-creator/ui/plugin-entry.js:46`：iframe 指向 `/api/frontend_plugin/qwenpaw-creator/files/ui/dist/app/index.html`，只有构建版本参数，没有凭据；浏览器 iframe 导航不会继承前一次 fetch 的 Authorization。
- `src/qwenpaw/hub/control_app.py:279`：个人 runtime 代理要求 Bearer，仅对 GET/HEAD 的 `files/preview/` 接受 query token。

因此入口 JS 成功并不代表 App 能打开。给 iframe URL 单独追加 token 仍不能覆盖 HTML 内的 JS/CSS、动态 import 和图片，它们不会继承父 URL 的 query。

### P1：SSE 与媒体的 token 契约和 Hub 不一致

- `plugins/apps/qwenpaw-creator/ui/src/api/creator/client.ts:46`：`creatorAuthenticatedUrl()` 给 EventSource 和媒体 URL 加 `?token=`。
- `src/qwenpaw/app/auth.py:774`：单机 AuthMiddleware 接受该 token。
- Hub 的上述代理只对文件预览接受 query token，所以 Creator 的事件流、图片/视频及 Range 请求即使携带有效用户 token，也会在 Hub 被拒绝。

普通 Creator fetch 已发送 Bearer，不能把问题概括为“Creator 所有请求都没带 token”。

### 已有的正确边界

`RuntimeBoundaryMiddleware`（`src/qwenpaw/app/auth.py:784`）已经保护 managed runtime 的所有 HTTP / WebSocket 路径。Hub 代理（`control_app.py:1397`）在认证用户、选择个人 runtime 后注入内部 token。应保留这条链路，不能把内部 token 发给浏览器，也不需要在 Creator 后端重复写鉴权。

### Bash / Shell 同样受影响：解释器与依赖必须沿子进程链一致

- `src/qwenpaw/agents/tools/shell.py:1344`：执行 shell 前复制 runtime 环境，并调用 `shell_execution_path()` 重建 PATH。
- `src/qwenpaw/utils/shell_normalization.py:10`：该函数把当前 `sys.executable` 所在目录放在 PATH 最前。因此只设置 VIRTUAL_ENV 或只给 PATH 加用户 venv 不够；如果 runtime 仍由宿主 Python 启动，shell 工具会再次把宿主 Python 提到最前。
- `shell.py:1141`：POSIX 直接执行使用 `shell -c` 并传入 env；`:951` 起会将调整后的 PATH 传给工具沙箱，但显式 sandbox policy PATH 优先。
- 各平台工具沙箱通常从 `os.environ` 重建环境，再应用 `SandboxConfig.env_vars`。因此需要同时验证直接执行和工具沙箱两条路径，不能只测 PluginLoader。
- `src/qwenpaw/agents/skill_system/registry.py:1235` 的 skill CLI 依赖检测也复用 `shell_execution_path()`，需要与实际执行保持一致。

这里需要的是用户独立的 shell **执行环境**。Bash/sh 可继续使用系统只读二进制，无需给每个用户复制 Bash；用户目录、PATH、Python 包、pip 安装出的 CLI 和子进程应属于自己的 runtime。venv 只管理 Python 依赖，文件和进程隔离仍由既有 OS 沙箱负责。

## 2. 推荐设计

### A. 一个 runtime 一个 venv，复用只读基础运行环境

新增小模块 `src/qwenpaw/hub/python_environment.py`，只负责 Python 环境的创建、校验、解释器路径和进程环境变量。由 `LocalProcessProvisioner.start()` 在 sandbox launch 前调用。

目录约定：`<runtime-root>/python/`，与 working、secrets、logs 同级，不进用户工作区。Windows 使用 `Scripts/python.exe`，POSIX 使用 `bin/python`；不可 resolve 掉 venv 解释器符号链接后再启动。

采用独立 venv，通过仅包含路径的 `.pth` 显式追加 Hub 的基础包目录及本仓库源码：只读复用 QwenPaw 和基础框架，用户新增包写入自己 venv。不启用 `system-site-packages`，避免执行宿主 `.pth` 而带入无关 editable 项目。真实 macOS 沙箱测试发现此类路径会让 pip 扫描失败，因此收紧了最初的实现选项。用户 runtime 本身由这个 venv 的 Python 启动，PluginLoader 原有 `sys.executable` 安装和进程内 import 自然落在同一环境，无需增加插件专属安装分支。

环境契约：

- 设置 VIRTUAL_ENV；将该 venv 的 bin/Scripts 放在 PATH 最前；移除宿主 CONDA_PREFIX 等解释器选择残留。
- 设置 PYTHONNOUSERSITE，避免 pip 用户目录成为隐式第二套安装目标。
- PYTHONPATH 只保留经过明确约束的开发源码路径，不透传任意宿主路径，更不能把宿主 site-packages 放在用户 venv 之前。
- Hub 只创建初始环境、检查完成标记和基础解释器指纹，不在沙箱外运行用户可写的解释器。QwenPaw import/启动通过原有沙箱启动及 readiness 验证；pip、sys.prefix 和 CLI 一致性由真实环境测试覆盖。
- 同一 runtime 创建加锁；在最终路径创建，校验通过后写完成标记。不要先创建 venv 再改名，因为 pip 等脚本可能嵌入绝对路径。失败时清理本次不完整环境。
- 停止保留环境；记录基础解释器/环境版本指纹。基础环境不匹配时明确提示先停止 runtime，再删除其 `python/` 并启动重建，不静默继续或破坏性重建。现有 rebuild API 仅面向 Docker，本次不扩大该 API；runtime 数据保留/删除沿用现有生命周期策略。
- 依赖安装仍在 runtime 沙箱内执行；不能为了安装第三方包让 Hub 在沙箱外运行插件安装逻辑。

这是“基础依赖只读共享 + 用户依赖独立可写”，不是复制一整套 Python。它解决用户之间污染；同一个 runtime 内多个进程内插件依赖冲突仍属于现有架构边界。本次不引入每插件进程或每插件 venv，也不为新格式增加兼容层。

#### A.1 Shell 与子进程环境契约

同一条链路应自然成立：`Hub → 用户 venv Python → Agent / PawApp → shell → python / pip / Python CLI`。

1. runtime 必须使用自身 venv 解释器启动。沿用现有 `shell_execution_path()`，不另外建一套 Bash 专用 Python 选择逻辑，不在每条命令前拼接 `source activate`，也不修改用户命令文本。
2. Bash/sh 默认使用非登录、非交互启动，保持现有 `-c` 行为；不额外读取宿主 profile/conda 初始化脚本。环境构建不继承宿主 BASH_ENV、ENV、PYTHONHOME 等会改变执行环境的设置。用户命令显式激活自己的项目环境属于用户行为，不强行重写。
3. HOME、临时目录沿用用户 runtime 路径，cwd 沿用已授权工作目录。基础系统工具目录保持可读；用户 venv bin/Scripts 优先于宿主 Python/conda 工具目录。Windows PATH/Path 按大小写不敏感规则合并，避免同时生成两个冲突键；Windows 原生支持 cmd/PowerShell，不假设存在 Bash 或自动引入 WSL。
4. 默认 `python`、`python -m pip`、`pip` 及 pip 安装的 console scripts 指向用户 venv；POSIX 同时验证 `python3`。不承诺将显式 `/usr/bin/python`、Windows `py` launcher 或用户指定绝对路径重定向，它们不按此 PATH 契约选解释器。
5. 额外工具沙箱必须能够读取/执行 venv、基础解释器和依赖；只有治理策略允许安装依赖时才给用户 venv 写权限。不能为了 pip 可用扩大到整个 runtime root、secrets 或宿主环境。若策略自定义 PATH 或限制 venv 访问，明确诊断，不静默回退到宿主 Python，也不覆盖治理限制。
6. Skill 前置依赖检查与实际 shell 使用同一默认路径规则；插件派生进程继承 runtime 环境。凡自行替换 env 的调用点只做必要修正，不扩展为全项目 subprocess 重构。

模块分工保持简洁：`hub/python_environment.py` 管理 venv 及 runtime 启动环境；既有 shell normalization 管理 shell PATH；既有资源治理模块管理内层沙箱访问权限。没有证据需要修改的 shell 后端只补回归验证。

### B. 通用 PawApp 浏览器资源会话

推荐集中提供一个短期、按 app 限定的浏览器读取会话，使用 HttpOnly Cookie，使 iframe、JS/CSS、动态 import、EventSource、媒体自然携带认证。

模块职责：

1. `hub/pawapp_access.py`：会话签发、校验、路径范围策略与 Cookie 设置。复用 Hub 的签名和用户状态校验基础，不复制整套账号认证实现。
2. `hub/control_app.py`：增加 Bearer 保护的 `POST /api/hub/pawapps/{app_id}/session`；代理只委托会话策略解析凭据。
3. Console PawApp SDK：增加 `prepareBrowserSession(appId)`，在打开原生浏览器资源前 await；负责并发去重与到期续期。单机模式无需 Hub 会话。
4. Creator：入口挂载 iframe 前调用 SDK；Hub 模式下媒体/SSE 使用会话，不再把长期用户 token 放在资源 URL；普通 fetch 继续用 Bearer。

打开生命周期统一由宿主 PawApp 层编排：`准备浏览器会话 → 确认入口脚本/路由就绪 → 挂载 App 内容`。App Center 点击、深链接/刷新、前进后退、OS 模式恢复均走同一个准备逻辑；设置页静态入口和新窗口打开也复用 SDK。Creator 入口仅消费统一的就绪状态/SDK，不自行签发凭据。共享进行中的 Promise，避免宿主与插件重复准备；不能仅靠 loader 的“已注册路由”缓存跳过会话校验。

准备阶段显示宿主加载状态，失败则在宿主显示登录失效或启动失败及重试操作，不先把未认证 URL 塞进 iframe 让用户看到 JSON。错误展示是补充，实际 HTML、子资源和 API 认证通过才算修复。App 卡片图标也是原生 img 请求，应纳入资源验证；可复用宿主带 Bearer 的资源 fetch 或读取会话，不开放用户插件目录。新窗口优先打开宿主 `/apps/{app_id}` 入口，让新页面自行走统一准备流程。

会话约束：

- 声明 purpose、user_id、token_version、runtime_id、app_id、过期时间；只用于该 app 的浏览器读取，不能当成通用 Hub Bearer token 使用。
- 允许 GET/HEAD，严格匹配 `/api/frontend_plugin/{app_id}/files/...`、`/api/pawapps/{app_id}/static/...`、`/api/{app_id}/...`；处理编码、路径分隔符与 dot segment，不能用宽泛字符串前缀匹配。
- Cookie 使用每 app 独立名称、HttpOnly、SameSite=Strict、HTTPS 下 Secure、Path=/api/、不设置 Domain。Path 不是授权边界，服务端必须验证上述 app/runtime 范围。
- 每次读取复用现有用户禁用/删除/token_version 校验；与用户的当前个人 runtime 匹配。过期、换用户、换 runtime、删除 App 后不得访问原内容。
- 认证优先级明确：有 Bearer 时只校验 Bearer，错误 Bearer 不回退 Cookie；没有 Bearer 时，仅上述浏览器读取路径可用会话。写操作和 Hub 管理 API 不接受此会话。
- SDK 在宿主会话恢复和 App 打开时准备会话；长时间使用需在过期前续期，刷新失败则回到明确的登录状态。退出时清理读取 Cookie，账号切换先清理旧会话。
- Hub 完成校验后仍只代理到用户自身 runtime，并使用既有内部 token；不转发浏览器会话 Cookie 到 runtime，不输出 token 到日志或 URL。

不推荐只扩大所有 API 的 query-token 白名单：它无法单独解决 iframe 子资源，且把长期凭据扩散到资源 URL。也不推荐开放 Hub 下的 frontend_plugin：这些文件属于不同用户安装的插件，需要先确定用户 runtime。

## 3. 验证与验收

Python：创建/复用/创建失败重试、并发启动、路径带空格、Windows 路径、基础环境变更、pip 缺失、解释器符号链接；确认 runtime sys.prefix 属于自己。用本地测试 wheel 验证 A 安装后可 import，B 和 Hub 不可 import，宿主环境无写入。真实 Linux/macOS/Windows 沙箱集成验证分别执行，不能用 mock 代替平台验收。

Shell：通过真正的 Agent shell 工具分别执行直接路径和工具沙箱路径，检查 HOME/cwd、`python` 的 sys.executable/sys.prefix、`python -m pip --version`、`pip --version`；安装一个带 console script 的本地测试 wheel，确认 Python import、CLI 执行和 skill CLI 检测一致。验证 A 安装后 A 的后续 shell 调用可用，B 与 Hub 不可用；新 shell、嵌套子进程、runtime 重启后仍成立。覆盖 Bash/sh、cmd/PowerShell、带空格路径、PATH/Path 合并和显式治理 PATH。另测安装被策略拒绝时不会回退宿主环境，读取权限足够但写权限不足时给出明确错误。

鉴权：无凭据 401；有效 Bearer；错误 Bearer 不回退；正确读取 Cookie；过期/禁用/撤销/用户切换/runtime 变化/跨 app 拒绝；路径编码绕过拒绝；读取 Cookie 不能写入或调用 Hub 管理 API；浏览器直接访问 runtime 端口仍被拒绝。

浏览器端到端：Creator 打开 → iframe → JS/CSS/chunk → API → SSE → 图片/视频 → Range 206 → 刷新 → 超时续期 → 退出/换账号；同时验证两个 PawApp 和两个用户的隔离。Docker 共用 Hub 鉴权，也需回归；Python 环境变更仅影响 local。

打开入口专项：复现用户“点击 QwenPaw Creator 显示 Not authenticated”，记录首个 401 的 URL 和返回层；覆盖首次点击、路由已缓存后的再次点击、深链接刷新、历史导航、OS 模式及新窗口。有效登录时必须实际显示 Creator 内容，不出现认证 JSON；失效登录时由宿主处理并停止挂载。验证会话准备完成前不发出原生 App 资源请求，续期不被路由缓存跳过。

Creator 还有 jq、FFmpeg、Playwright 浏览器、模型/OSS 配置等独立运行前提。修好这两条链路不能被表述为已经验证所有生成能力。

## 4. Checklist

- [x] 定位 local 解释器、pip 目标与沙箱写边界。
- [x] 定位 PawApp 入口、iframe 子资源、SSE/媒体鉴权断点。
- [x] 明确保留既有 RuntimeBoundaryMiddleware。
- [x] 补充 Bash / Shell、skill CLI 检查及子进程的环境链路定位。
- [x] 记录用户点击 Creator 出现 Not authenticated 的现象，补充所有打开入口的统一会话准备方案。
- [ ] 现场复现并确认首个 401 请求的 URL、状态码及返回层。
- [x] 提交模块边界、修改范围与验收方案。
- [x] 用户 review：确认 venv 采用只读基础依赖共享，而非全量复制安装。
- [x] 用户 review：确认采用 app 范围浏览器读取会话。
- [x] 实现 Python 环境模块及 provisioner 接入。
- [x] 验证 shell / Python / pip / CLI 环境一致；保留显式内层沙箱治理限制。
- [x] 实现 Hub 会话策略、SDK 接入与 Creator 资源链路。
- [x] 在 conda QwenPaw 环境完成相关单测，新增/受影响测试全部通过。
- [x] 完成可用的 macOS 沙箱与浏览器验收；Linux/Windows 真实 OS 验收仍待对应 runner。

## 5. 实施与验证记录

- 按用户最终要求直接修改 `feat/fix_hub`，未使用 subagent。
- Python 环境模块显式共享基础包目录，移除宿主环境选择变量；初次创建失败可重试，完成环境复用，基础环境变化拒绝静默继续。Hub 不在隔离边界外执行已有用户 Python。
- Hub 复用原有 token 签名和用户撤销逻辑，签发 15 分钟的 App 读取 Cookie。读取响应设置 private/no-store，防止跨账号缓存复用；会话 Cookie 不传入 runtime。
- Console 统一挂载门禁覆盖点击、深链接及历史恢复，定时续期；会话 POST 与退出/换账号 Cookie 清理按序执行。App 图标通过 Bearer fetch 后使用 blob 展示。
- Creator 在 Hub 模式下使用原生 Cookie 资源请求，普通 API 仍使用 Bearer；单机模式保持既有资源鉴权契约。
- 已通过：真实 macOS Seatbelt 中 venv/pip/CLI 隔离测试；真实 Hub → local runtime 启动与 HTTP 代理端到端；Console 构建；Creator 类型检查、构建与打包检查。
- 浏览器验收使用真实 Hub、Chrome 和实际编译的 Console/Creator 前端，业务接口使用测试数据。点击 Creator、深链接刷新、原生 SSE、Range 206 均通过；截图确认首页及首次模型配置引导正常呈现，无 Creator 资源 4xx/5xx。
- Python pre-commit 全部通过。相关前端测试与类型/构建检查通过；对修改文件执行 ESLint 时，原有 `config.test.ts` 和 `hostExternals.ts` 的 9 处 `no-explicit-any` 错误及 2 条原有 warning 仍存在，本次未扩展修改这些既有代码。
- Windows/Linux 当前仅代码与相关单测覆盖，未在真实 OS 上运行平台验收；Creator 生成模型、OSS、jq 等业务依赖不属于本次浏览器鉴权验收。
