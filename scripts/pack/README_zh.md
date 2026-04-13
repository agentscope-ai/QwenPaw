# QwenPaw Desktop 打包脚本

一键打包：脚本会先运行 `scripts/wheel_build.sh` 构建 **wheel**
（包含 console 前端产物），再用 **临时 conda 环境** + **conda-pack**
（不依赖当前开发环境）。依赖以 `pyproject.toml` 为准。

- **Windows**: wheel → conda-pack → 解压 → NSIS 安装包 (`.exe`)
- **macOS**: wheel → conda-pack → 解压到 `.app` → 可选打 zip

## 系统要求

- **Windows**: Windows 10 或更高版本
- **macOS**: macOS 14 (Sonoma) 或更高版本，推荐 Apple Silicon (M1/M2/M3/M4) 以获得 MLX 支持

## 前置

- **conda**（Miniconda/Anaconda）在 PATH
- **Node.js / npm**（用于构建 console 前端）
- （仅 Windows）**NSIS**：`makensis` 在 PATH
- **图标**：预生成的 `icon.ico` (Windows) 和 `icon.icns` (macOS) 已包含在 `scripts/pack/assets/` 中

## 一键打包

在**仓库根目录**执行：

**macOS**
```bash
bash ./scripts/pack/build_macos.sh
# 产出: dist/QwenPaw.app

CREATE_ZIP=1 bash ./scripts/pack/build_macos.sh   # 同时生成 .zip
```

**Windows (PowerShell)**
```powershell
./scripts/pack/build_win.ps1
# 产出: dist/QwenPaw-Setup-<version>.exe
# 创建两个启动器：
#   - QwenPaw Desktop.vbs (静默启动，无终端窗口)
#   - QwenPaw Desktop (Debug).bat (显示终端，便于调试)
```

## 从终端启动并查看日志（macOS）

如果双击 .app 会闪退，可以在终端里运行以查看完整报错和日志：

```bash
# 在仓库根目录执行，强制只用打包环境（不用系统 conda / PYTHONPATH）。路径按需改。
APP_ENV="$(pwd)/dist/QwenPaw.app/Contents/Resources/env"
PYTHONPATH= PYTHONHOME="$APP_ENV" "$APP_ENV/bin/python" -m qwenpaw desktop
```

所有标准输出和错误（包括 Python traceback）都会打在终端里；可加 `--log-level debug` 查看更详细日志。

若**双击** .app 没有任何窗口出现，启动器会把 stderr/stdout 写入 `~/.qwenpaw/desktop.log`，可打开该文件查看报错。

首次打开时，macOS 可能弹出「请求访问桌面的文件」：请点**允许**，否则部分功能可能不可用或窗口会关闭。

## macOS：提示「无法验证开发者」/ Gatekeeper 拦截时怎么打开

用户从 Release 等渠道下载的 QwenPaw macOS 应用（zip 内的 .app）未经过 Apple 公证，可能看到「Apple 无法验证“QwenPaw”是否包含可能危害 Mac 安全或泄漏隐私的恶意软件」。可按以下方式打开：

- **右键打开（推荐）**
  在 QwenPaw 应用上 **右键（或 Control + 点击）** → 选 **「打开」** → 在弹窗里再点一次 **「打开」**。即表示你确认运行该应用，Gatekeeper 会放行，之后双击即可正常打开。

- **在系统设置里放行**
  若仍被拦截，进入 **系统设置 → 隐私与安全性**，往下找到类似「已阻止使用 QwenPaw，因为无法验证开发者」的提示，点 **「仍要打开」** 或 **「允许」** 即可。

- **用终端去掉隔离属性（不推荐普通用户）**
  在终端执行：`xattr -cr /Applications/QwenPaw.app`（或解压后 .app 的实际路径）。会去掉「从互联网下载」的隔离标记，一般就不再弹恶意软件提示，但不如「右键 → 打开」安全、可控。

## CI

`.github/workflows/desktop-release.yml`：

- **触发**: Release 发布 或 手动 workflow_dispatch
- **Windows**: 构建 console → 临时 conda 环境 + conda-pack → NSIS → 上传 artifact
- **macOS**: 构建 console → 临时 conda 环境 + conda-pack → .app → zip → 上传 artifact
- **Release**: 若由 release 触发，则把 Windows 安装包与 macOS zip 上传到该 Release 的附件

## 脚本说明

| 文件 | 说明 |
|------|------|
| `build_common.py` | 创建临时 conda 环境，从 wheel 安装 `qwenpaw[full]`，conda-pack 产出归档 |
| `build_macos.sh` | 一键：构建 wheel → build_common → 解压到 QwenPaw.app；可选打 zip |
| `build_win.ps1` | 一键：构建 wheel → build_common → 解压 → 创建 VBS/BAT 启动器 → makensis 安装包 |
| `desktop.nsi` | NSIS 脚本：打包 `dist/win-unpacked`，添加图标，创建快捷方式 |
| `assets/icon.ico` | 预生成的 Windows 图标（安装包和快捷方式使用） |
| `assets/icon.icns` | 预生成的 macOS 图标（应用包使用） |
