# PR #7833 修复方案与 checklist

用户已授权直接修改、commit 并 push 当前分支。最终确认：共享管理员维护的 QwenPaw 安装；每用户一个常驻 runtime、一层 OS 沙箱、独立目录与持久化环境变量。不要求 Agent 间独立 OS 隔离。

详细边界见 [设计文档](hub-local-python-pawapp-auth-review.zh.md)，复现记录见 [补充审查](pr-7833-local-cli-review.zh.md)。

- [x] 撤回完整 Python 隔离、复制与每用户 venv；删除相关可写挂载，不增加旧格式兼容层。
- [x] 共享解释器与 scripts 路径，框架启动防止 cwd 模块遮蔽。
- [x] Local 子进程继承外层沙箱，不重复初始化或探测嵌套沙箱。
- [x] 独立环境持久化、控制项校验，managed 模式禁用 dotenv 与共享配置迁移。
- [x] managed env CLI 使用 runtime API，即时更新服务环境；失败不离线回退。
- [x] 插件 CLI 使用 runtime API，Local 缺依赖提示管理员安装，Docker 保留自动安装。
- [x] PawApp 桌面 gate、合法 ID、Cookie 范围及实际路由归属校验。
- [x] 后端/前端回归、真实 macOS 工具 shell → CLI → runtime 和重启持久化测试。
- [x] 最终格式检查（mypy、Black、flake8、pylint、Prettier）及类型检查。

提交与推送执行结果以 Git 提交记录和远端分支为准。


## 测试精简（2026-09-18）

- [x] 删除手写 Python -P 调用及内部沙箱类型断言，保留真实工具 shell → CLI → runtime 回归。
- [x] 删除重复的存储重载/子进程环境继承用例，保留真实 runtime 重启持久化 E2E。
- [x] 合并 PawApp 路由碰撞测试的重复搭建，保留核心 API、其他应用、写操作和碰撞拒绝断言。
- [x] 精简 CLI、manifest ID 和依赖安装参数组合；保留关键错误路径。
- [x] 受影响后端 37 项、前端 4 项通过；格式检查通过。


## 运行实例筛选交互

- [x] 状态和运行方式下拉框添加明确的“全部”选项，选中后清除对应查询条件。
- [x] 所有者为可清空文本框，沿用现有行为。
- [x] 所有者名称旁显示管理员标记；接口批量返回角色，避免逐条查询。
- [x] 现有 Hub 后端 61 项、前端 22 项测试及生产构建通过；部署沿用原服务器服务。


## 镜像立即拉取

- [x] 管理员拉取按镜像地址校验，不受尚未保存的默认运行来源影响。
- [x] 创建运行实例继续校验配置来源；拉取去重继续保留。
- [x] 现有 Docker/Hub 回归 69 项及格式检查通过；部署沿用现有服务。


## 镜像下载状态一致性

- [x] 统一 Docker Hub 完整地址和简写的匹配，并匹配本地镜像 digest。
- [x] Tag 下拉框与详情卡片使用同一个本地镜像匹配结果。
- [x] 相关 Hub 测试 33 项及生产构建通过；服务器仅更新前端产物。


## 主机资源容量说明

- [x] 内存、数据盘显示已用、总量和可用容量。
- [x] 仅采样当前 Hub 用户数据根目录所在文件系统，展示解析后的路径，不汇总磁盘。
- [x] 容量和路径相关后端 52 项、前端 22 项与 TypeScript 检查通过。

## Local 用户初始化

- [x] Local 沙箱内首次启动复用 init --defaults --accept-security。
- [x] 已有配置只补齐技能与缺失文件，成功后标记，重启不重复初始化。
- [x] 相关后端 69 项、前端 22 项、生产构建和代码检查通过；临时目录实测新用户初始化、已有配置保留和重启幂等。Docker 沿用现有入口。

## Local Linux 持久化进程文件系统

现场会话日志确认 11:36 Bash 可读文件、11:37 Python 可读文件，11:38 Hub 部署重启后两者均不可读。原因是原沙箱根目录为匿名 tmpfs，而非工具之间用了不同文件系统。

- [x] 每用户独立持久化沙箱根目录；系统工具和共享 Python 继续只读挂载，不复制安装。
- [x] 用户工作目录挂载到 /workspace，统一 HOME、cwd、QwenPaw 数据目录。用户自行创建的任意目录保存在其沙箱根目录中，不特殊处理 /home。
- [x] Linux 实机验证文件工具、Bash、Python 共享内容、runtime 重启持久化与跨用户不可见；未改动工具实现。
- [x] 服务器已备份并一次性更新 24 个 Local 配置文件和 2 份治理策略路径；未添加旧宿主路径兼容挂载。两个运行实例的 Agent API 均返回 /workspace/workspaces/default。
- [x] 本地相关回归 70 项通过，2 项平台限定跳过；代码检查通过。macOS/Windows 保持原生目录语义。

`/tmp`、`/dev`、`/proc` 保持临时或系统挂载语义；用户工作区和沙箱根目录的用户文件持久化。共享安装的只读路径保持原样。

本次部署备份位于服务器 `/mnt/weirui/qwenpaw-deploy-backups/pre-persistent-root-20260918`，包含原数据及仍存活的匿名根文件系统中的用户内容快照。

## CI 与 Copilot 复核

- [x] 补齐五种语言新增 Hub 翻译，修复旧集成测试参数与格式。
- [x] PawApp URL 统一编码，跨源会话创建和清理携带凭据，Hub 使用显式 CORS 来源。
- [x] 继承 Local 沙箱前验证内核提供的隔离状态，不仅依赖环境标记。
- [x] 核对 CodeQL：17 项已存在于 main；新增 Cookie 告警验证签名和编码边界。
- [x] 完成相关回归、完整前端测试和代码检查，修复纳入本分支提交。


### CodeQL 告警归因

逐项对照主分支的告警实例，17 项高危告警（51、50、49、48、47、46、35、34、32、31、30、29、28、27、26、25、24）均已存在于 main，涉及未被本 PR 修改的 `backup/_utils/safe_swap.py` 和 `backup/_utils/_mount_swap.py`。例如 [告警 51](https://github.com/agentscope-ai/QwenPaw/security/code-scanning/51) 的 main 实例可用于核对，不能把检查摘要中的 “new” 直接解释为本 PR 引入。

[告警 587](https://github.com/agentscope-ai/QwenPaw/security/code-scanning/587) 为 `py/cookie-injection`：app ID 流入签名令牌后传给 `set_cookie`。人工核验判断为误报：值是 URL-safe Base64 编码的 JSON 加 HMAC-SHA256 十六进制签名，cookie 名是 app ID 的 SHA256，路径和属性固定，原始输入无法插入 cookie 分隔符。读取时验证签名和有效期。现有测试补充了含分号的 app ID、单一 Set-Cookie 头及令牌篡改拒绝断言。未抑制规则或自动关闭告警；CodeQL 门禁仍需结合扫描结果与告警归因判断。

### 本轮验证与边界

- 完整前端覆盖率测试：385 个文件、3859 项通过；TypeScript 检查通过。
- 相关后端回归：92 项通过、1 项平台限定跳过；包含 macOS 原生沙箱 CLI 验证。
- Linux 独立工作树实测：文件工具、Bash、Python 共享内容，重启持久化、CLI 可用、不同用户文件隔离通过。
- 全量 pre-commit 定位的格式和导入顺序问题已修正；修改文件的全部 hooks 复验通过，前端 Prettier 通过。
- Windows 使用进程令牌的 AppContainer 标志核验边界，本轮没有 Windows 实机验证。
- Hub 的跨源凭据仅向 `QWENPAW_CORS_ORIGINS` 显式来源开放；cookie 保持 SameSite=Strict，适用于同站跨源部署（例如同主机不同端口），不承诺跨站嵌入。
- 环境标记之外，Linux 检查用户命名空间、能力与挂载布局；macOS 检查 Seatbelt 是否生效；Windows 检查 AppContainer。平台检查不等同于重新审计每项沙箱规则。


## Docker 启动失败与重试循环复核

2026-09-18 远程运行实例反复报 Hub 模型连接校验失败。容器实际导入 `/app/venv/lib/python3.11/site-packages/qwenpaw`，该镜像的 providers 路由没有 `/api/models/hub-status`；宿主的新协议不能由仅更新宿主代码带入既有镜像。

- [x] 核查同步边界：Docker SDK 启动在 lifecycle executor，镜像拉取在独立执行器，状态刷新通过 `run_in_threadpool`；现场轻量接口仍能快速响应，未证实持续的全局事件循环阻塞。
- [x] 保留 Docker 启动失败状态和错误，避免正常退出的残留容器把 FAILED 覆盖成 STOPPED，进而触发健康检查重新启动。
- [x] 普通代理请求遇到 FAILED 立即返回 503；重试由显式启动、重启或重建触发。
- [x] 旧镜像缺少模型探测接口（404/405）或返回 SPA HTML 时跳过可选探测并记录日志，不阻止启动；接口存在时的鉴权失败与连接错误仍然报错。
- [x] 未分配端口时不生成 `http://127.0.0.1:0`，界面显示占位符。
- [x] 107 项后端回归通过，覆盖慢启动时控制面响应、失败后不重复启动、失败状态保持和协议错误分类。

旧镜像可以启动，但跳过探测并不会给旧镜像补上 Hub 模型功能。远程服务和镜像尚未在本轮排查中更新。


## Docker 预览与生命周期补充修复计划

#7766 的预览查询 token 鉴权已在本分支，位于 Hub 代理前，与 provisioner 无关。补充修复聚焦真实文件路径和旧镜像协议：

- [x] 新增用户 `profile.workspace_dir`，默认 `/workspace`；Docker 与 Linux Local 的挂载、环境、Agent 配置和预览共同使用用户设置。旧用户缺字段时补写默认值，保留自定义值及其他 profile 字段。
- [x] Docker 使用 Hub 专属 bridge，关闭容器互通，并通过该网桥的宿主地址访问模型服务。
- [x] start 在生命周期锁内检查当前运行状态，避免重复创建容器。
- [x] 缺失 browser_prefixes 的旧镜像只发放应用静态资源权限，不猜测动态接口前缀。
- [x] 回归覆盖 Hub 预览鉴权到真实文件路由、路径拒绝、旧版 PawApp 与 Docker 启动参数；154 项相关测试通过，增补用户 profile 接口与平台检查 18 项通过，Linux 自定义 `/data/member` 实机验证通过。

远程 Docker 实测使用已有旧版 latest 镜像和临时数据：真实文件路由预览成功，关闭 ICC 后容器间连接拒绝，宿主到容器的发布端口访问成功。测试资源已清理，未挂载生产用户目录。预览路由改为同步 FastAPI 路由，文件元数据检查和配置读取由线程池执行。

目录统一不搬迁 Local 沙箱根目录中工作区之外的任意文件，也不改写历史消息里的绝对路径。旧镜像的动态 PawApp API 仍需升级镜像才能提供路由归属校验；缺失能力时仅授权应用静态资源。Docker 网桥隔离针对容器间流量，不宣称阻止宿主进程访问其发布端口。

管理员通过用户更新接口提交 `{"profile":{"workspace_dir":"/data/member"}}`，重启实例后生效。字段保存在既有 `profile_json` 中，不新增数据库列；Hub 启动时仅补齐缺失字段。运行实例保存启动时的 profile 快照，用于下一次目录变更时更新受管配置中的目录引用，不搬迁用户文件。macOS/Windows Local 保持原生宿主路径语义，Docker 的容器内路径在各宿主平台一致。
