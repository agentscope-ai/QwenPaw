# Windows Sandbox (WSL2 委托执行) — 设计与测试指南

> 临时文档，供 Windows 测试人员参考。

## 1. 设计概述

### 架构

```
Windows Host                         WSL2 Linux (Ubuntu 22.04+)
┌─────────────────────┐              ┌─────────────────────────────┐
│  QwenPaw Agent      │              │  python3 landlock_script.py  │
│                     │   wsl.exe    │                             │
│  WindowsSandbox     │─────────────▶│  1. prctl(NO_NEW_PRIVS)    │
│  - path translation │              │  2. landlock_create_ruleset │
│  - script generation│              │  3. add_path rules          │
│  - result parsing   │              │  4. restrict_self           │
│                     │◀─────────────│  5. exec /bin/sh -c <cmd>  │
│  ExecutionResult    │   stdout/err │                             │
└─────────────────────┘              └─────────────────────────────┘
```

### 核心思路

在 Windows 上没有 Seatbelt / Landlock 等内核隔离机制，因此将命令委托给 WSL2 Linux 子系统执行，
在 WSL2 内利用 Landlock LSM (Linux 5.13+) 实现文件系统级隔离。

### 执行流程

1. **探测 WSL2 可用性** — `probe_wsl2_availability()`
   - 检查 `wsl.exe` 是否在 PATH
   - 列出 WSL2 发行版 (`wsl --list --verbose`)
   - 验证 python3 可用
   - 验证 Landlock ABI 版本

2. **路径转换** — `win_to_wsl_path()`
   - `C:\Users\foo\project` → `/mnt/c/Users/foo/project`
   - `~/.ssh` → `/home/<wsl_user>/.ssh` (WSL 内 HOME)

3. **脚本生成** — `_generate_wsl_sandbox_script()`
   - 生成 Python 脚本，内含 Landlock syscall 调用
   - 授权系统路径 (只读)、workspace (读写)、/tmp (读写)
   - deny_paths 通过 HOME 子目录枚举排除

4. **执行** — 通过 `wsl -d <distro> -- python3 /tmp/script.py`
   - 脚本 apply Landlock → exec 目标命令
   - 捕获 stdout/stderr
   - 检测 "Permission denied" → `sandbox_violation`

### 文件改动

| 文件 | 改动 |
|------|------|
| `src/qwenpaw/sandbox/windows_sandbox.py` | **新增** — WSL2 sandbox 核心实现 |
| `src/qwenpaw/sandbox/config.py` | 增加 `_probe_windows_wsl2()` |
| `src/qwenpaw/sandbox/local_sandbox.py` | factory 接入 WSL2 |
| `src/qwenpaw/sandbox/__init__.py` | 导出 `WindowsSandbox` |
| `tests/unit/sandbox/test_windows_sandbox.py` | **新增** — 单元测试 |

---

## 2. 前置条件

### Windows 系统要求
- Windows 10 21H2+ 或 Windows 11
- WSL2 已启用 (`wsl --install`)

### WSL2 发行版要求
- Ubuntu 22.04+ (推荐) 或任何 kernel >= 5.13 的 WSL2 distro
- 已安装 python3: `sudo apt install python3`

### 验证步骤

```powershell
# 1. 检查 WSL2
wsl --status

# 2. 检查发行版
wsl --list --verbose
# 应该看到至少一个 VERSION=2 的发行版

# 3. 进入 WSL 检查 python3
wsl -d Ubuntu -- python3 --version

# 4. 检查 Landlock 支持
wsl -d Ubuntu -- python3 -c "
import ctypes, ctypes.util
libc = ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6', use_errno=True)
libc.syscall.restype = ctypes.c_long
abi = libc.syscall(ctypes.c_long(444), None, ctypes.c_size_t(0), ctypes.c_uint32(1))
print(f'Landlock ABI version: {abi}')
assert abi > 0, 'Landlock not supported!'
"
```

---

## 3. 单元测试

### 运行方式

```powershell
# 在项目根目录 (Windows)
cd QwenPaw

# 安装依赖 (首次)
pip install -e ".[dev]"

# 运行 Windows sandbox 单元测试
python -m pytest tests/unit/sandbox/test_windows_sandbox.py -v

# 运行所有 sandbox 单元测试
python -m pytest tests/unit/sandbox/ -v
```

### 测试覆盖

| 测试类 | 说明 |
|--------|------|
| `TestPathTranslation` | Windows ↔ WSL 路径转换 (11 cases) |
| `TestProbeWSL2` | WSL2 可用性探测 mock 测试 |
| `TestWSLScriptGeneration` | Landlock 脚本生成逻辑 |
| `TestWindowsSandboxExecution` | execute() 方法 mock 测试 (成功/violation/timeout) |
| `TestFactoryWSL2` | create_sandbox() 正确路由到 WindowsSandbox |
| `TestConfigProbeWindows` | probe_sandbox_support() Windows 路由 |

> 单元测试全部使用 mock，**不依赖 WSL2 实际安装**，macOS/Linux 也能运行。

---

## 4. E2E 测试 (需要 Windows + WSL2 环境)

### 4.1 基础可用性测试

```powershell
# 在 Python 中运行
python -c "
from qwenpaw.sandbox import probe_sandbox_support
cap = probe_sandbox_support()
print(f'Supported: {cap.supported}')
print(f'Mode: {cap.mode}')
print(f'Reason: {cap.reason}')
print(f'ABI version: {cap.landlock_abi_version}')
"
```

**期望输出**: `Supported: True`, `Mode: SandboxMode.WSL2`, ABI version >= 1

### 4.2 正常命令执行

```python
import asyncio
from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec

async def test_basic():
    config = SandboxConfig(
        mode=SandboxMode.WSL2,
        workspace_dir="C:\\Users\\<你的用户名>\\projects\\test",
        mounts=[MountSpec(path="C:\\Users\\<你的用户名>\\projects\\test", writable=True)],
        deny_paths=["~/.ssh", "~/.aws"],
    )
    sandbox = create_sandbox(config)
    
    # 测试 1: 基本命令
    result = await sandbox.execute("echo hello from WSL2 sandbox")
    print(f"[Test 1] exit={result.exit_code}, stdout={result.stdout.strip()}")
    assert result.exit_code == 0
    assert "hello" in result.stdout
    
    # 测试 2: 读 workspace（应该成功）
    result = await sandbox.execute("ls /mnt/c/Users/<你的用户名>/projects/test")
    print(f"[Test 2] exit={result.exit_code}, stdout={result.stdout[:100]}")
    assert result.exit_code == 0
    
    print("✅ Basic tests passed!")

asyncio.run(test_basic())
```

### 4.3 敏感路径拒绝测试

```python
import asyncio
from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec

async def test_deny():
    config = SandboxConfig(
        mode=SandboxMode.WSL2,
        workspace_dir="C:\\Users\\<你的用户名>\\projects\\test",
        mounts=[MountSpec(path="C:\\Users\\<你的用户名>\\projects\\test", writable=True)],
        deny_paths=["~/.ssh"],
    )
    sandbox = create_sandbox(config)
    
    # 测试: 读 ~/.ssh 应该被 Landlock 拒绝
    result = await sandbox.execute("cat ~/.ssh/id_rsa")
    print(f"exit={result.exit_code}")
    print(f"stderr={result.stderr}")
    print(f"violation={result.sandbox_violation}")
    
    assert result.exit_code != 0
    assert result.sandbox_violation is not None
    assert "permission denied" in result.sandbox_violation.lower()
    
    print("✅ Deny test passed! ~/.ssh was blocked by Landlock.")

asyncio.run(test_deny())
```

### 4.4 写保护测试

```python
import asyncio
from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec

async def test_write_protection():
    config = SandboxConfig(
        mode=SandboxMode.WSL2,
        workspace_dir="C:\\Users\\<你的用户名>\\projects\\test",
        mounts=[MountSpec(path="C:\\Users\\<你的用户名>\\projects\\test", writable=True)],
    )
    sandbox = create_sandbox(config)
    
    # 测试 1: workspace 内写入（应该成功）
    result = await sandbox.execute("echo test > /mnt/c/Users/<你的用户名>/projects/test/sandbox_test.txt")
    print(f"[Write workspace] exit={result.exit_code}, violation={result.sandbox_violation}")
    assert result.exit_code == 0
    
    # 测试 2: workspace 外写入（应该被拒绝）
    result = await sandbox.execute("echo hack > /mnt/c/Users/<你的用户名>/Desktop/hacked.txt")
    print(f"[Write outside] exit={result.exit_code}, violation={result.sandbox_violation}")
    assert result.exit_code != 0
    
    print("✅ Write protection test passed!")

asyncio.run(test_write_protection())
```

### 4.5 超时测试

```python
import asyncio
from qwenpaw.sandbox import create_sandbox, SandboxConfig, SandboxMode, MountSpec

async def test_timeout():
    config = SandboxConfig(
        mode=SandboxMode.WSL2,
        workspace_dir="C:\\Users\\<你的用户名>\\projects\\test",
        mounts=[MountSpec(path="C:\\Users\\<你的用户名>\\projects\\test", writable=True)],
        timeout_seconds=3,
    )
    sandbox = create_sandbox(config)
    
    result = await sandbox.execute("sleep 100")
    print(f"timed_out={result.timed_out}, exit={result.exit_code}")
    assert result.timed_out is True
    
    print("✅ Timeout test passed!")

asyncio.run(test_timeout())
```

---

## 5. 常见问题

### Q: WSL2 发行版内核太旧怎么办？
```bash
# 在 WSL2 内检查
uname -r
# 如果 < 5.13, 更新 WSL
# 在 Windows PowerShell (管理员):
wsl --update
```

### Q: Landlock ABI version 返回负数？
说明 WSL 内核不支持 Landlock。需要更新 WSL 内核:
```powershell
wsl --update
wsl --shutdown
wsl  # 重新启动
```

### Q: `wsl --list --verbose` 编码问题？
WSL2 的 `--list` 输出是 UTF-16LE 编码。代码已处理此情况。

### Q: 命令在 WSL 内找不到文件？
确保用 WSL 路径格式。Windows 路径 `C:\foo` 在 WSL 内是 `/mnt/c/foo`。

---

## 6. 预期行为总结

| 场景 | 预期结果 |
|------|----------|
| `echo hello` | exit=0, stdout="hello\n" |
| 读 workspace 文件 | exit=0, 正常输出 |
| 写 workspace 文件 | exit=0, 文件创建成功 |
| 读 ~/.ssh | exit≠0, sandbox_violation 包含 "Permission denied" |
| 写 workspace 外 | exit≠0, sandbox_violation 包含 "Permission denied" |
| 超时命令 | timed_out=True, exit=-1 |
| WSL2 不可用 | probe 返回 supported=False |
