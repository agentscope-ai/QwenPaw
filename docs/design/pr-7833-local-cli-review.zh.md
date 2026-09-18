# PR #7833：Local Hub 与 CLI 补充审查

日期：2026-09-17。审查对象是当前分支及本轮尚未提交的修改，而非只审查原 PR。本文保留补充审查时的复现记录；用户随后已确认方案并授权修复、commit 和 push。

## 结论

审查时确认取消每用户 venv 的方向可以保留，但实现仍有以下遗漏；现已按文末对照修复。仅将 Python 所在目录加入 PATH，不能保证 CLI 的运行、命令语义和隔离边界正确。

推荐：**管理员维护一套专用 QwenPaw 安装环境，所有 Local 用户只读共享；每用户一个常驻 runtime 和一层 OS 沙箱；日常管理 CLI 通过当前 runtime 的 API 操作；独立 HOME、临时目录和持久化环境变量。**

“专用安装环境”可以是现有 conda/uv/venv 安装，不是给每个用户创建一套，也不要求在现有安装之上再复制一套。不要随意共享管理员日常开发所用、装有无关软件的 Python。需要不同依赖版本或更强隔离的用户使用 Docker；容器同样需要正确配置挂载、凭据及权限。

一个轻量 venv 本身通常不是主要成本；之前变重的是复制解释器/全部依赖及维护完整隔离的方案。venv 也不天然导致 CLI 缺失，安装对应 console script 可以解决，但会增加依赖管理分支，无法解决本报告中的沙箱和 CLI 状态同步问题。

## 已确认的问题

### 1. P1：外层 Local 沙箱与内层工具沙箱冲突

位置：hub/process_isolation.py 的 MacOSSeatbeltIsolator、agents/tools/shell.py 的 _execute_in_sandbox、sandbox/macos_sandbox.py。

在真实 macOS 上启动外层 Local Seatbelt，再使用现有 create_sandbox(SEATBELT) 执行以下命令：

- qwenpaw --version：退出码 71。
- qwenpaw env set REVIEW_NESTED_VALUE test：退出码 71。
- stderr 均为 sandbox-exec: sandbox_apply: Operation not permitted。

治理层会生成工具沙箱配置；shell 在收到配置时继续创建内层沙箱，没有识别 Local 已有的外层边界。此前“外层沙箱里直接调用 CLI”成功的测试，没有覆盖这条路径。

影响不局限 CLI：走相同内层沙箱入口的普通 shell 命令也可能失败。Windows/Linux 的嵌套行为不能由 macOS 结果推断，需要各自验证。

建议将 Local 的硬隔离粒度明确为用户 runtime。治理层仍做命令授权、路径检查、审计、超时和环境过滤；Local 工具进程继承已验证的外层 OS 沙箱，不再创建第二层。不允许在外层建立失败时静默退回无沙箱。

用户已明确：隔离单位是用户；Agent 间独立 OS 隔离不是需求。实现复用用户 runtime 的 OS 边界。

### 2. P1：清理启动环境后，dotenv 仍能重新注入配置

位置：constant.py 顶部的项目 .env 加载及 WORKING_DIR/.env 加载。

真实 macOS Local 沙箱复现：在用户 working/.env 写入 PIP_TARGET，启动环境没有该变量，导入 qwenpaw.constant 后该变量出现。用户配置 API 中的控制变量保护未覆盖该入口。

使用临时源码布局也复现了项目根 .env 加载宿主业务变量。实际部署中是否泄漏取决于该文件是否位于外层沙箱可读范围，不能宣称所有部署必然泄漏；但只过滤 os.environ 无法建立完整的启动配置契约。

另外，envs/store.py 仍有从共享源码目录 envs.json 迁移到用户 secrets 的路径。是否有历史文件、能否解密取决于部署，应在 managed runtime 禁止共享来源迁移，而非依赖文件恰好不存在。

建议：managed runtime 不加载项目/用户 .env，不从共享安装迁移用户配置，统一使用该 runtime 的受控加密存储。standalone 保持原有行为。

### 3. P2：CLI 环境变量命令写盘成功，但 runtime 仍使用旧值

位置：cli/env_cmd.py；envs/store.py 的进程内 os.environ 同步。

复现步骤：

1. 模拟常驻 runtime 进程，将 REVIEW_USER_VALUE 设置为 before。
2. 子进程执行 qwenpaw env set REVIEW_USER_VALUE after，退出码为 0。
3. 读取持久化文件得到 after，但父进程 os.environ 仍为 before。

因此，随后由常驻 runtime 启动的 Bash/Python 仍继承旧值，直到 runtime 重载。这不是“已有子进程不会被更新”的正常限制，而是发起后续命令的服务自身未更新。

建议：managed CLI 的 env list/set/delete 调用当前 runtime 已有 API，由服务写盘并更新环境；不在 CLI 子进程直接维护另一份进程状态。运行时不可达时明确失败，不默默回退到离线写文件。standalone 保留离线命令。

### 4. P2：Windows 不能用解释器父目录代表 CLI 目录

位置：hub/local_provisioner.py 的 PATH 构建。

当前只加入 Path(sys.executable).parent。Windows 普通安装/conda 的 python.exe 可以位于安装根目录，console scripts 则在 Scripts。此时 Python 可用，而 qwenpaw.exe 不在 PATH。Windows venv 的路径布局又不同，不能统一拼接 Scripts/Scripts。

此项是代码及 Python 安装布局审查结论，尚未在 Windows 原生复现。

建议使用当前安装的 sysconfig scripts 路径与解释器目录，去重后生成 PATH；检查实际 CLI 入口存在。原生 Windows 还需验证该发行版的 DLL 搜索和 AppContainer ACL，不能只测试 where qwenpaw。不应为了修复 DLL 问题重新继承全部宿主 PATH。

### 5. P2：工作目录可遮蔽框架的模块入口

位置：hub/local_provisioner.py 使用 python -m qwenpaw，cwd 为用户可写 working。

已复现：在 working 写入 qwenpaw.py 后，用当前 provisioner 生成的环境执行同一命令，运行的是该文件，未加载框架。生成可信 PYTHONPATH 并不能阻止 -m 默认将 cwd 放到更前面。

这发生在用户 runtime 的启动边界内，当前证据不代表逃逸到 Hub。直接影响是框架启动被遮蔽、健康检查失败或加载错误模块。

建议仅对框架受控启动使用 -P/安全的受控入口，并保证已安装模块或开发源码路径明确。不要对所有用户 Python 命令全局施加忽略 cwd 的行为，否则普通项目 import 会改变。Python 官方文档说明 -P 针对 -m 不前置 cwd，-I 还会忽略 PYTHON* 环境变量，不能不加区分替换。

### 6. P2：Local 的依赖安装限制只覆盖 PluginLoader，遗漏 CLI

位置：plugins/loader.py、cli/plugin_commands.py 的 _install_requirements_cli。

已使用 mock 包管理器复现：QWENPAW_RUNTIME_PROVISIONER=local 时，CLI 安装函数仍调用 python -m pip。没有实际安装任何包。

CLI 有在线 API 安装和离线安装两条路径；在线检测仍通过 read_last_api/TCP 探测，不能把在线路径假设为永远成立。该遗漏会违反“Local 不自动安装依赖”的约定，通常最终遭遇共享目录只读失败；不能据此声称已能修改宿主安装。

建议 managed plugin 命令统一调用 runtime API，不走离线安装回退；安装能力检查也应覆盖所有受支持入口，避免维护两套 Local 规则。

## 还需明确的功能边界

- CLI 不是单一 HTTP 客户端。agents create 等命令仍直接修改本地配置；env 命令已证实存在运行中状态同步问题，其他直接写配置命令需按现有加载机制逐项验证，不能假设一律热更新或一律失效。
- update、uninstall、hub、daemon、desktop 等属于宿主管理/服务生命周期功能。用户 runtime 中不应以“完整 CLI 可用”笼统承诺支持这些操作；应明确报错引导管理员处理，不能仅等待 OS 权限失败。
- 保留已实现的同源 token 注入和回环代理绕过。CLI 应连接本用户 runtime；更换 URL、跨源重定向不得携带内部 token。现有 runtime_api.py 已有相应限制。
- runtime token 是该用户服务权限，不是每工具的细粒度权限。允许 shell 使用它意味着 shell 能调用该用户的 API，不应再宣称仅靠 shell 文件沙箱可限制所有同用户 API 操作。
- 最小 PATH 也会让 Homebrew、Node 等外部工具不可见。需要区分“禁止继承宿主业务环境变量”和“允许管理员提供可信只读工具链路径”；不能靠复制整个管理员 PATH 解决。
- 共享 site-packages 的 .pth/sitecustomize 属于共享安装的可信代码。只读共享不会消除其启动行为；Local 的可信前提是管理员维护该安装。
- 本轮未确认新的 Local 生命周期事件循环阻塞问题。取消 venv 确实消除了其创建成本，但不应将此等同于所有同步 I/O 已解决；例如既有插件依赖检测仍需在异步入口中关注文件/metadata 检查。

## 方案比较

| 方案 | 用户增量成本 | CLI/依赖管理 | 隔离与适用性 |
| --- | --- | --- | --- |
| 共享受控安装 + 每用户一层 OS 沙箱 | 一个常驻 runtime 和用户数据，无依赖复制 | 管理员统一依赖；managed CLI 通过用户 API | 推荐 Local；用户之间隔离，同用户 Agent 共用信任边界 |
| 每用户轻量 venv + 共享基础包 | venv、用户安装包及维护成本 | 需处理 CLI 入口、依赖版本覆盖与升级 | 有依赖区分，不替代 OS 沙箱；不解决嵌套和状态同步 |
| 每用户完整 Python/依赖副本 | 磁盘和升级成本明显增加 | 独立依赖，但维护复杂 | 与轻量 Local 目标不符 |
| Docker runtime | 容器管理；macOS/Windows 还涉及虚拟机 | 可独立镜像/依赖 | 更适合自管理依赖及更强隔离，需正确配置 |

## CLI 正确运行的验收契约

“CLI 正常”必须同时满足：入口可发现、解释器和模块版本正确、当前 runtime 地址正确、认证同源、配置属于当前用户、写操作由服务生效、错误退出码正确、实际治理工具链可执行。

修复对照：

- [x] 用户级 OS 沙箱由 Local provisioner 建立；工具 factory 及 capability probe 复用已有边界。
- [x] managed 模式停止 dotenv 加载和旧共享环境迁移。
- [x] CLI 路径加入当前安装 scripts；框架启动使用 -P。
- [x] env CLI 通过服务 API 更新持久化与运行中环境，不离线回退。
- [x] managed 插件 CLI 不回退离线安装；Local 两个安装入口均拒绝自动安装。
- [x] 增加实际工具执行入口、CLI API、dotenv、模块遮蔽及迁移回归。
- [x] 保留 PawApp 授权修复、现有当前 runtime 同源认证与模型默认值行为。

未扩展范围：没有新增 CLI 代理服务、宿主管理命令白名单、依赖环境复制或管理员工具链配置产品。已有 update/daemon 等命令仍受既有 OS 权限约束，本次不承诺把所有 standalone 宿主管理命令改造成用户 API。也没有借此重构其他命令的本地配置加载机制。

验证：CLI/插件/治理/沙箱/环境回归 1861 passed、7 skipped；前端 176 passed；macOS runtime E2E 与启动边界测试 6 passed。另有 Hub/PawApp 及实际 shell 调用路径回归通过。Windows/Linux 原生验收未在本机执行，不能以模拟测试代替。

参考：[Python 命令行与 -P/-I](https://docs.python.org/3.12/using/cmdline.html)、[CPython sysconfig 安装路径](https://github.com/python/cpython/blob/main/Doc/library/sysconfig.rst)。
