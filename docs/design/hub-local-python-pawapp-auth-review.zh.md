# Hub Local Python、环境变量与 PawApp 授权边界

> 已按用户确认的边界收敛实现。问题复现与修复对照见 [Local CLI 补充审查](pr-7833-local-cli-review.zh.md)。

## 最终决策（2026-09-17）

本节取代本分支此前的每用户 venv 和完整 Python 隔离方案。用户已确认：Local 取消用户 venv，共享宿主 Python 和对应 CLI，依赖由管理员统一安装；用户环境变量保持独立持久化。需要自行管理依赖或独立 Python 环境的用户应使用 Docker。

## Local 的执行与依赖模型

Hub 使用自身的 Python 解释器启动每个用户的 QwenPaw runtime。Local 不创建、复制或维护用户 Python 环境，也不为本分支旧 venv 格式增加迁移或兼容层。已存在的旧目录不自动删除，但不再激活或使用。

PATH 由当前解释器目录、sysconfig 对应的 scripts 目录及必要的系统目录生成，所以该安装环境中的 qwenpaw CLI 可被 shell 找到。不会复制宿主完整 PATH；其他目录中的外部 CLI 不保证可用。开发 checkout 的 Python 源码路径由当前程序位置生成，不继承宿主 PYTHONPATH。

每个用户 runtime 是常驻 QwenPaw 进程。它在启动前建立唯一的用户级 OS 沙箱；工具执行复用继承的边界，不再创建嵌套 OS 沙箱。治理检查、环境过滤、审计和命令超时继续保留。Agent 间独立 OS 隔离不是本需求。外层沙箱建立失败时不启动 runtime。

框架内部使用 python -P -m 启动，避免工作目录中的同名模块遮蔽 QwenPaw；不改变用户普通 Python 命令的导入语义。

普通 shell/Python 命令仍启动普通子进程，不会额外启动完整 QwenPaw 服务。显式执行 qwenpaw CLI 时，才运行相应 CLI 进程。

基础解释器、标准库、QwenPaw 及安装依赖共享宿主安装，按既有 OS 沙箱权限读取/执行，宿主安装不向用户开放写权限。**Local 不承诺宿主 Python 禁读/禁执行，也不是完整 Python 或依赖隔离。** venv 本身也不是安全边界。共享宿主包及其启动行为是此方案接受的边界。

插件缺少依赖时，Local 的自动安装入口明确报错，提示管理员安装 requirements，或切换 Docker；不会自动调用 pip/uv 改动共享环境。Docker 和独立运行模式保留原有依赖安装流程。此限制不是对任意用户代码自行下载包的全面检测机制。

## 用户环境变量

启动环境按以下来源构建：

1. 少量必要的系统/locale 变量；Windows 保留运行所需的系统路径配置。
2. runtime 生成的 HOME、临时目录、Windows 用户目录、PATH、Python 源码路径和内部控制参数。
3. 该用户的凭据以及已有加密环境变量存储。

宿主设置的任意 XXX、业务密钥、代理配置、CONDA、PIP、UV 或 shell 启动变量不会直接继承给用户 runtime。其新启动的 Bash/Python 子进程继承用户 runtime 的环境。必要的 OS 变量以及明确生成的内部变量不是用户私有业务配置。

继续复用设置页、环境变量 API/CLI 和每个 runtime 的 secrets/envs.json，不新增持久化格式。Local 禁用系统 keyring，使用各自 secrets 目录中的密钥。managed env CLI 通过当前 runtime 的 API 操作，保存后更新服务的 os.environ，后续子进程可见；重启后重新加载。运行时不可达时命令失败，不回退到离线写文件。managed 插件命令同样使用 runtime API，依赖由管理员管理。

managed 启动不加载项目或用户 .env，也不迁移共享安装中的历史 envs.json，避免绕过用户环境变量存储的控制项校验。standalone 保持原有行为。

临时 shell export 不会自动写入持久化存储；已经运行的子进程不会被追溯更新。PATH、HOME、Python/pip/动态加载器及内部 runtime 控制变量不能通过用户环境配置或凭据覆盖；已知且允许编辑的 QwenPaw 业务选项按原有注册表处理。

这里的环境变量隔离指受控的启动和配置行为，不承诺阻止任意恶意代码通过共享解释器或其他 OS 机制观察宿主信息。需要更强边界时使用适当配置的 Docker/容器隔离。

## PawApp 浏览器授权

OS 桌面与普通入口使用相同 PawAppAccessGate：浏览器会话准备好后再挂载应用，账号 token 变化时重新授权。

Cookie 名使用 app ID 的摘要，避免将合法 manifest ID 错误限制为短横线格式。SDK 独立运行模式不请求 Hub 会话；Hub 模式对 URL 中的 ID 编码。

Hub 按应用实际注册的 API prefix 签发只读会话。转发时清除外部伪造的内部 token 和应用范围头，使用内部 token 携带受限应用范围。runtime 根据实际首个匹配路由的归属再次检查，只允许目标应用自己的 GET/HEAD API 和静态资源。核心 API、其他应用、写操作及路由碰撞不能通过应用 Cookie 获得访问权限。

## I/O 与平台边界

不再有 runtime 启动时创建 venv、安装 pip 或复制 Python 的阻塞和存储开销。保留既有 runtime 生命周期在线程池中执行的路径；依赖安装仍使用已有后台线程入口，Local 在运行包管理器前拒绝。

使用 pathlib 和 os.pathsep 构建路径；Windows 使用原有 AppContainer/桥接进程，不假设 Bash 存在，macOS/Linux 沿用 Seatbelt/bubblewrap。当前机器能原生验证 macOS；Windows/Linux 的模拟或单元测试不能代替目标平台的原生验收。

## 验收清单

- [x] 移除每用户 venv 模块和治理层可写挂载。
- [x] 使用共享解释器及其 CLI，禁止 Local 自动安装插件依赖。
- [x] 最小启动环境、用户变量持久化、控制变量保护。
- [x] PawApp 桌面 gate、manifest ID、实际路由归属校验。
- [x] 完成后端回归与 macOS E2E；格式检查纳入提交前检查。
