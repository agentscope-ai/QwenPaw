# RyPaw Desktop - Electron 版本

这是 RyPaw Desktop 的 Electron 版本，替换了原来的 pywebview 方案。

## 架构说明

```
RyPaw Desktop (Electron)
├── 主进程 (main.js)
│   ├── 启动 Python 后端子进程
│   ├── 管理 Electron 窗口
│   └── 处理自动更新
├── 渲染进程 (preload.js)
│   └── 提供安全的 IPC 通信桥接
└── Python 后端
    └── 运行在 http://127.0.0.1:18765
```

## 为什么选择 Electron？

| 特性 | pywebview | Electron |
|------|-----------|----------|
| 兼容性 | 依赖系统 WebView2 | 内置 Chromium，一致性好 |
| 打包速度 | 3-5 分钟 (conda-pack) | 1-2 分钟 (electron-builder) |
| 调试体验 | 有限日志 | 完整 DevTools |
| 自动更新 | 需自己实现 | electron-updater |
| 社区支持 | 小 | 大，成熟 |

## 开发模式

### 前置要求

- Python 3.10+
- Node.js 18+
- npm

### 启动开发环境

**Windows:**
```powershell
.\scripts\start_electron_dev.ps1
```

**macOS/Linux:**
```bash
bash scripts/start_electron_dev.sh
```

或者手动启动：
```bash
cd electron
npm install
npm run dev
```

开发模式下：
- 使用系统 Python（无需打包）
- 前端支持热重载
- 自动打开 DevTools

## 打包发布

### Windows 打包

```powershell
.\scripts\pack\build_electron.ps1
```

### macOS/Linux 打包

```bash
bash scripts/pack/build_electron.sh
```

### 打包流程

```
1. 构建 console 前端 (npm run build)
   ↓
2. 构建 Python wheel
   ↓
3. 创建可移植 Python 运行时 (conda-pack)
   ↓
4. 安装 Electron 依赖
   ↓
5. electron-builder 打包
   ↓
6. 生成安装包 (.exe/.dmg/.AppImage)
```

### 输出文件

**Windows:**
- `dist/RyPaw Desktop Setup {version}.exe`

**macOS:**
- `dist/RyPaw Desktop-{version}.dmg`
- `dist/RyPaw Desktop-{version}-arm64.dmg` (Apple Silicon)

**Linux:**
- `dist/RyPaw Desktop-{version}.AppImage`
- `dist/rypaw-desktop_{version}_amd64.deb`

## 自动更新

Electron 版本集成了 `electron-updater`，支持自动更新。

### 配置更新服务器

在 `electron/builder.yml` 中配置：

```yaml
publish:
  provider: github  # 或其他提供商
  owner: your-org
  repo: rypaw
```

### 发布新版本

1. 更新 `electron/package.json` 中的版本号
2. 创建 Git tag: `git tag v1.0.0`
3. 推送 tag: `git push origin v1.0.0`
4. 运行打包: `npm run publish`

## 故障排查

### Python 后端启动失败

检查：
1. Python 路径是否正确
2. 依赖是否完整安装
3. 端口 18765 是否被占用

```bash
# 检查端口占用
lsof -i :18765  # macOS/Linux
netstat -ano | findstr :18765  # Windows
```

### Electron 窗口无法加载

1. 打开 DevTools 查看控制台错误
2. 检查网络请求是否成功
3. 查看主进程日志

### 打包失败

1. 清理缓存：`npm cache clean --force`
2. 重新安装依赖：`rm -rf node_modules && npm install`
3. 检查磁盘空间

## 与旧版本对比

### 移除的文件

- `scripts/pack/build_win.ps1` (旧的 pywebview + NSIS)
- `scripts/pack/build_macos.sh`
- `scripts/pack/copaw_desktop.nsi`

### 新增的文件

- `electron/` (Electron 主目录)
  - `main.js` (主进程)
  - `preload.js` (预加载脚本)
  - `package.json` (Electron 配置)
  - `builder.yml` (打包配置)
- `scripts/pack/build_electron.ps1` (新的 Windows 打包)
- `scripts/pack/build_electron.sh` (新的 macOS/Linux 打包)
- `scripts/start_electron_dev.ps1` (开发启动)
- `scripts/start_electron_dev.sh` (开发启动)

## 下一步

- [ ] 配置代码签名 (Windows/macOS)
- [ ] 设置自动更新服务器
- [ ] 添加崩溃报告 (Sentry)
- [ ] 优化安装包大小
- [ ] 添加安装向导
