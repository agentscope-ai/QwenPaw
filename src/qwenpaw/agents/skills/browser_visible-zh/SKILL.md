---
name: browser_visible
description: "当用户需要控制 browser_use 的浏览器启动方式时，使用本 skill。当前 browser_use 默认使用 managed CDP 启动本地 Chrome/Chromium；`headed` 控制是否显示窗口，`private_mode` 控制是否禁用 CDP、改走 Playwright，`browser_args` 传入额外的 Chromium 启动参数，`executable_path` 指定自定义浏览器可执行文件路径。"
metadata:
  builtin_skill_version: "1.3"
  qwenpaw:
    emoji: "🖥️"
    requires: {}
---

# 浏览器启动模式

`browser_use.start` 只有两种启动方式：

- 默认：managed CDP
- `private_mode=true`：Playwright 直接管理

参数含义：

- `headed`：是否显示浏览器窗口
- `private_mode`：是否禁用 CDP，改走 Playwright
- `browser_args`：额外的 Chromium 启动参数（字符串），多个参数用空格分隔。适用于所有启动路径（headless、headed、managed CDP）。例如 `"--incognito"` 启用隐身模式，`"--proxy-server=http://127.0.0.1:7890"` 设置代理。默认空字符串（无额外参数）。
- `executable_path`：自定义浏览器可执行文件路径（字符串）。设置后覆盖系统默认浏览器检测，可指定任意基于 Chromium 的浏览器。例如 `"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"`。仅允许包含已知浏览器关键词（chrome、chromium、edge、firefox、brave 等）的可执行文件，且文件必须存在。默认空字符串（使用系统默认）。

以上参数互不影响，可自由组合。

## 常见用法

默认启动：
```json
{"action": "start"}
```

打开可见窗口：
```json
{"action": "start", "headed": true}
```

不走 CDP：
```json
{"action": "start", "private_mode": true}
```

可见窗口 + 不走 CDP：
```json
{"action": "start", "headed": true, "private_mode": true}
```

隐身模式：
```json
{"action": "start", "headed": true, "browser_args": "--incognito"}
```

指定浏览器路径 + 设置代理：
```json
{"action": "start", "headed": true, "browser_args": "--proxy-server=http://127.0.0.1:7890", "executable_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"}
```

## 什么时候用 `private_mode`

只有当用户明确要求以下之一时，再设置 `private_mode=true`：

- 不想通过 CDP 管理浏览器
- 想改走 Playwright
- 想减少被其他本地工具通过 CDP 连接的可能性

否则只按需设置 `headed=true` 即可。

## 什么时候用 `browser_args`

当用户需要传入 Chromium 原生启动参数时使用，常见场景：

- 隐身/无痕模式（`--incognito`、`--inprivate`）
- 设置代理（`--proxy-server`）
- 指定窗口大小（`--window-size=1920,1080`）
- 禁用 GPU（`--disable-gpu`）
- 加载扩展（`--load-extension=/path/to/ext`）

参数使用 shell 风格的空格分隔，在 Windows 上会自动处理路径中的反斜杠。

## 什么时候用 `executable_path`

当用户需要使用非系统默认的浏览器时使用，常见场景：

- 系统默认是 Chrome，但用户想用 Edge
- 安装了多个浏览器，想指定某一个
- 使用便携版浏览器

注意：`executable_path` 只接受包含已知浏览器关键词（chrome、chromium、edge、firefox、brave、vivaldi、opera、360se、yandex、tor）的可执行文件，且路径必须指向一个真实存在的文件。

## 注意

- 默认就是 managed CDP
- 启动方式完全由调用参数决定
- managed CDP 依赖本机存在 Chrome / Chromium / Edge
- `private_mode=true` 不等于绝对不可检测，只是改为 Playwright 管理
- 用户手动操作可见浏览器时，不一定会刷新 idle 计时
- `private_mode`、`browser_args`、`executable_path` 都是每次 `start` 的显式参数，不会持久保存
- 若当前已有浏览器在运行，需要先 `stop` 再重新 `start`，才能切换启动方式、窗口可见性或启动参数。
- 可见模式会占用桌面并需要图形环境，服务器或无图形环境可能无法使用。
