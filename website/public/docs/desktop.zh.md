# QwenPaw Desktop 桌面应用版使用指南

> ⚠️ **Beta 版本说明**
>
> 桌面应用目前处于 Beta 测试阶段，存在以下已知限制：
>
> - **兼容性测试不完整**：未在所有系统版本和硬件配置上进行充分测试
> - **性能可能存在缺陷**：启动速度、内存占用等方面可能需要进一步优化
> - **功能持续完善中**：部分功能可能不稳定或缺失
>
> 欢迎反馈问题，帮助我们改进产品质量。

**下载地址**：[GitHub Releases][releases]

本文档说明如何在 Windows 和 macOS 系统上安装和使用 QwenPaw Desktop 桌面应用。

[releases]: https://github.com/agentscope-ai/QwenPaw/releases

## 特别说明

**首次启动可能需要较长时间（10-60秒不等，甚至可能更长），具体取决于您的系统配置。** 应用需要初始化 Python 环境、加载依赖库和启动 Web 服务，请耐心等待窗口出现。后续启动会更快。

## 目录

- [Windows 使用指南](#windows-使用指南)
- [macOS 使用指南](#macos-使用指南)
- [技术支持](#技术支持)

---

## Windows 使用指南

### 系统要求

- **操作系统**: Windows 10 或更高版本
- **架构**: x64 (64位)

### 安装步骤

1. **下载安装包**
   从 [Release 页面][releases]下载 `QwenPaw-Setup-<version>.exe` 文件

2. **运行安装程序**
   双击 `.exe` 文件，按照安装向导提示完成安装
   - 默认安装位置：`C:\Users\<你的用户名>\AppData\Local\QwenPaw`
   - 安装完成后会在桌面和开始菜单创建快捷方式

### 启动方式

安装完成后，您会看到**两个启动快捷方式**：

#### **QwenPaw Desktop** (推荐日常使用)

- **特点**: 静默启动，无终端窗口，界面简洁
- **适用场景**: 正常使用，不需要查看技术日志
- **启动方式**: 双击桌面或开始菜单的 "QwenPaw Desktop" 图标
- **技术说明**: 使用 VBScript 启动器，后台运行 Python 进程

#### **QwenPaw Desktop (Debug)** (调试模式)

- **特点**: 显示终端窗口，实时输出运行日志
- **适用场景**:
  - 遇到问题需要查看错误信息
  - 开发测试
  - 报告 Bug 时需要提供日志
- **启动方式**: 双击开始菜单的 "QwenPaw Desktop (Debug)" 图标
- **日志内容**:
  - 应用启动信息
  - Python 错误堆栈
  - API 调用日志
  - 按 Ctrl+C 或关闭窗口可停止应用

### 常见问题

**Q: 应用启动后窗口白屏，无法正常显示？**
A: 这通常是因为系统缺少 **Microsoft WebView2** 运行时（部分 Windows 10 系统未预装）。
请前往微软官网下载并安装：
[Microsoft WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
安装完成后重启应用即可。

**Q: 应用启动后没有反应？**
A: 使用 "QwenPaw Desktop (Debug)" 模式启动，查看终端输出的错误信息

**Q: 如何卸载？**
A: 在 Windows 设置 → 应用 → 已安装的应用 → 找到 "QwenPaw Desktop" → 卸载

**Q: 安装包是否安全？**
A:

- 应用未经过 **Microsoft 代码签名**（成本 $200-800/年），Windows Defender SmartScreen 会显示警告
- 这是正常现象，点击 "更多信息" → "仍要运行" 即可
- 代码完全开源，构建过程在 GitHub Actions 上透明可查

---

## macOS 使用指南

### 系统要求

- **操作系统**: macOS 14 (Sonoma) 或更高版本
- **架构**:
  - ✅ **Apple Silicon (M1/M2/M3/M4)** - 推荐，支持 MLX 本地模型加速
  - ⚠️ Intel 芯片 - 可能可以运行，但无法使用 MLX 加速功能

### 安装步骤

1. **下载压缩包**
   从 [Release 页面][releases]下载 `QwenPaw-<version>-macOS.zip` 文件

2. **解压缩**
   双击 `.zip` 文件自动解压，得到 `QwenPaw.app` 应用

3. **移动到应用程序文件夹 (可选)**
   将 `QwenPaw.app` 拖到 `/Applications` 文件夹

### 首次启动：解除系统安全限制

#### 为什么需要手动信任？

QwenPaw 应用**未经过 Apple 开发者签名和公证（Notarization）**，macOS Gatekeeper 会默认阻止运行。

**为什么没有签名？**

- 📋 开发者签名需要额外成本和流程，后续版本会补上

**当前影响：**

- ✅ **不影响功能**：应用完全正常运行
- ⚠️ **首次需手动信任**：一次操作后永久有效
- 🔒 **安全性**：开源代码可审计，构建过程透明（CI/CD）

#### 如何解除限制？

#### 方法 1：右键打开 (推荐)

1. **右键点击**（或 Control + 点击）`QwenPaw.app`
2. 在菜单中选择 **"打开"**
3. 在弹出的对话框中，再次点击 **"打开"** 按钮
4. ✅ 之后双击即可正常启动，不会再弹窗

#### 方法 2：系统设置解除拦截

如果仍被拦截：

1. 打开 **系统设置 → 隐私与安全性**
2. 向下滚动，找到类似以下提示：
   _"已阻止使用 'QwenPaw'，因为无法验证开发者"_
3. 点击 **"仍要打开"** 或 **"允许"** 按钮
4. 输入管理员密码确认

#### 方法 3：终端命令解除隔离

```bash
# 移除下载隔离属性
xattr -cr /Applications/QwenPaw.app
```

⚠️ **注意**: 此方法会完全移除安全检查，仅当您完全信任应用来源时使用。

### 🔍 权限请求

首次启动时，macOS 可能会弹窗请求以下权限：

- **桌面文件访问权限**
  用于访问您的文件（如果使用文件相关功能）
  - 点击 **"允许"** 以正常使用
  - 点击 **"不允许"** 应用仍可运行，但部分功能受限

### 启动方式

#### 正常启动（双击）

- 双击 `QwenPaw.app` 即可启动
- 应用会在后台运行，打开浏览器窗口
- 日志输出到：`~/.qwenpaw/desktop.log`

#### 终端启动（查看实时日志）

如果应用崩溃或需要查看详细日志：

```bash
# 切换到应用目录
cd /Applications  # 或您的 QwenPaw.app 所在目录

# 设置环境变量并启动
APP_ENV="$(pwd)/QwenPaw.app/Contents/Resources/env"
PYTHONPATH= PYTHONHOME="$APP_ENV" "$APP_ENV/bin/python" -m qwenpaw desktop
```

**终端启动的优势：**

- ✅ 实时查看所有日志输出
- ✅ 看到完整的 Python 错误堆栈
- ✅ 便于调试和报告问题
- ✅ 可添加 `--log-level debug` 查看更详细信息

**查看日志文件：**

```bash
# 查看最近的启动日志
tail -f ~/.qwenpaw/desktop.log
```

### 常见问题

**Q: 双击后没有任何反应？**
A:

1. 检查 `~/.qwenpaw/desktop.log` 文件查看错误
2. 使用上述终端命令启动，查看实时输出

**Q: 提示"Apple 无法验证此应用"？**
A: 按照上述"解除系统安全限制"步骤操作

**Q: 如何卸载？**
A: 将 `QwenPaw.app` 拖到废纸篓，然后删除 `~/.qwenpaw` 配置文件夹

**Q: Intel Mac 可以用吗？**
A: 可以运行，但无法使用 MLX 模型加速（MLX 仅支持 Apple Silicon）

**Q: 应用为什么没有签名，为什么系统会提示有风险？**

A:

当前采用

- ✅ **开源透明**：所有代码和构建流程公开在 GitHub
- ✅ **CI/CD 可验证**：GitHub Actions 自动构建，日志可查
- ✅ **用户审计**：可以自行检查代码并本地构建
- ✅ **一次信任**：手动信任后永久有效

---

## 技术支持

- **GitHub Issues**: [提交问题](https://github.com/agentscope-ai/QwenPaw/issues)
- **打包文档**: `scripts/pack/README.md` - 技术细节和本地构建指南
- **日志位置**:
  - Windows: Debug 模式终端查看，或 `%USERPROFILE%\.qwenpaw\` 目录
  - macOS: `~/.qwenpaw/desktop.log`

---

## 使用建议

### Windows 用户

- **日常使用**: 使用普通版（无终端窗口）
- **遇到问题**: 切换到 Debug 版查看日志

### macOS 用户

- **首次安装**: 务必按照"解除安全限制"步骤操作
- **调试问题**: 使用终端启动方式查看实时日志
- **权限问题**: 首次启动时请允许文件访问权限
