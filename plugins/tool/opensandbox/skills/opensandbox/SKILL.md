---
name: opensandbox
description: 判断何时使用 OpenSandbox 插件执行隔离命令。当命令应该运行在 Linux 沙箱而不是宿主机时使用，尤其适合不可信脚本、依赖安装实验、网络相关命令测试，或 Windows 宿主机上需要 Linux 运行时的任务。
---

# OpenSandbox 使用规则

当 QwenPaw 已启用 `execute_opensandbox_command` 工具时，使用本 skill 辅助判断是否应该把命令放进 OpenSandbox 沙箱执行。

OpenSandbox 是一个隔离的 Linux 沙箱，适合安全地探索命令和运行一次性实验。当前 MVP 不会自动把宿主机项目目录挂载或同步到沙箱内，因此不能默认把涉及宿主项目文件的任务放进沙箱。

## 适合使用 OpenSandbox 的场景

当用户需要做下面这些事情时，优先使用 `execute_opensandbox_command`：

- 执行不可信、不熟悉或由模型生成的 shell 命令。
- 尝试安装依赖、探测包管理器行为、做一次性 CLI 实验。
- 在 Windows 宿主机上检查 Linux 运行时行为。
- 执行不应该触碰宿主文件系统的命令。
- 执行简单验证命令，例如 `echo`、`pwd`、`uname -a`、`cat /etc/os-release`、`python3 --version` 或工具可用性检查。
- 测试网络相关命令，同时尽量减少对本机环境的影响。
- 在干净环境里复现 shell 行为。

## 不适合默认使用 OpenSandbox 的场景

如果命令必须满足下面条件，不要默认使用 OpenSandbox：

- 读取、编辑、构建或测试宿主机项目目录里的文件。
- 依赖 Windows 本地路径，例如 `D:\projects\...`。
- 使用本地凭证、SSH key、浏览器登录态、GUI 应用、硬件设备或宿主机专有服务。
- 生成必须直接出现在宿主项目目录里的产物。
- 需要多条命令之间保留状态，除非用户明确接受当前 MVP 每次调用都会创建新的 sandbox。
- 回答宿主机特定问题，例如 Windows 版本、本机 PATH、本地进程列表或本机工具安装状态。

遇到这些情况时，如果本地 shell 工具可用且符合安全策略，就使用本地工具；否则说明当前 OpenSandbox MVP 需要文件同步或目录挂载后才能操作宿主项目文件。

## 决策规则

选择 shell 工具前，按下面顺序判断：

1. 如果任务关注宿主机或宿主项目文件，不要选择 OpenSandbox，除非用户明确要求沙箱执行。
2. 如果任务有风险、不可信、Linux 特定，或只需要一次性可丢弃运行时，选择 `execute_opensandbox_command`。
3. 如果用户说“使用沙箱”“用 OpenSandbox 运行”“隔离执行”“不要在本机执行”，或英文表达如 "use sandbox"、"run in OpenSandbox"、"do not run locally"，选择 `execute_opensandbox_command`。
4. 如果本地 shell 已被禁用，只剩 OpenSandbox 可用，可以使用 OpenSandbox，但涉及宿主文件访问时必须提醒用户当前 MVP 无法直接访问宿主文件。

## 命令写法

优先从简单 Linux 命令开始验证：

```bash
echo Hello from OpenSandbox && pwd
```

再按需收集环境信息：

```bash
cat /etc/os-release
uname -a
python3 --version
```

不要把 Windows 路径作为 `cwd` 传给沙箱。除非用户已经明确完成文件同步或目录挂载，否则使用 `/workspace`。

## 回复要求

执行沙箱命令后，向用户说明关键事实：

- 命令是在 OpenSandbox 中执行的。
- sandbox id，如果工具输出里包含。
- exit code。
- 关键 stdout 或 stderr。
- 零核心 MVP 带来的限制，尤其是当前没有宿主目录自动同步。

## 安全注意事项

OpenSandbox 可以降低宿主机风险，但不代表可以盲目执行破坏性命令或可能泄露密钥的命令。对下载并执行远程脚本、打印环境变量、访问凭证的命令要格外谨慎。
