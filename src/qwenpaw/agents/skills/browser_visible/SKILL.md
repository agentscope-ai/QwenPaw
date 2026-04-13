---
name: browser_visible
description: "当用户需要控制 browser_use 的浏览器启动方式时，使用本 skill。当前 browser_use 默认使用 managed CDP 启动本地 Chrome/Chromium；`headed` 控制是否显示窗口，`private_mode` 控制是否禁用 CDP、改走 Playwright。"
metadata:
  builtin_skill_version: "1.2"
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

两者互不影响，可自由组合。

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

## 什么时候用 `private_mode`

只有当用户明确要求以下之一时，再设置 `private_mode=true`：

- 不想通过 CDP 管理浏览器
- 想改走 Playwright
- 想减少被其他本地工具通过 CDP 连接的可能性

否则只按需设置 `headed=true` 即可。

## 注意

- 默认就是 managed CDP
- 启动方式完全由调用参数决定
- managed CDP 依赖本机存在 Chrome / Chromium / Edge
- `private_mode=true` 不等于绝对不可检测，只是改为 Playwright 管理
- 用户手动操作可见浏览器时，不一定会刷新 idle 计时
- `private_mode` 是每次 `start` 的显式参数，不会持久保存
- 若当前已有浏览器在运行，需要先 `stop` 再重新 `start`，才能切换启动方式或窗口可见性。
- 可见模式会占用桌面并需要图形环境，服务器或无图形环境可能无法使用。
