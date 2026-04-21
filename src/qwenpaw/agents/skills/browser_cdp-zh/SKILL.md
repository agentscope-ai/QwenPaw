---
name: browser_cdp
description: "当用户明确希望连接到已运行的 Chrome 浏览器、扫描本地 CDP 端口、显式指定 `cdp_port`，或让多个 agent / 工具共享同一个浏览器时，使用本 skill。当前 browser_use 默认已使用 managed CDP 启动浏览器；如果用户不希望暴露浏览器历史、Cookies 等敏感信息，推荐改用 `private_mode=true` 的隐私模式。"
metadata:
  builtin_skill_version: "1.2"
  qwenpaw:
    emoji: "🔌"
    requires: {}
---

# 浏览器 CDP 使用参考

当前 **browser_use** 默认就是以 **managed CDP** 方式启动并接管本地 Chrome/Chromium，但这不等于每次都应该把 CDP 端口暴露给用户或其他工具。

本 skill 关注的是更“显式”的 CDP 用法：

1. **扫描本地 CDP 端口**
2. **连接已有 Chrome（`connect_cdp`）**
3. **显式指定 `cdp_port` 启动浏览器**
4. **让多个 agent / 工具共享同一个浏览器实例**

也就是说：

- 普通 `start` 默认会使用 managed CDP，但通常不需要用户理解或感知 CDP 细节
- 只有在用户明确提出“连接现有浏览器 / 扫描端口 / 指定端口 / 共享浏览器”时，才应进入本 skill 的语义范围

> **隐私建议**
>
> 如果用户不希望暴露浏览器历史、Cookies、页面内容或会话信息，推荐使用 `private_mode=true`，改走 Playwright 直接管理模式。

> **⚠️ 单 workspace 单浏览器实例**
>
> 同一 workspace 同时只能运行或连接一个浏览器。若当前已有浏览器实例，必须先执行 `stop`，再切换到新的浏览器或新的 CDP 连接。

---

## 何时使用

仅在用户明确表达以下意图时使用本 skill：

- “连接到我已经打开的 Chrome”
- “扫描一下本机有哪些 CDP 端口可用”
- “用固定调试端口启动浏览器”
- “让别的 agent / 工具也能连到这个浏览器”
- “通过远程调试端口附着到浏览器”

以下情况通常**不要**进入本 skill：

- 用户只是说“打开浏览器”
- 用户只是说“开一个可见窗口”
- 用户没有提到共享、端口、CDP、远程调试

这些情况通常直接使用普通 `start`，必要时加 `headed=true`，参考 **browser_visible** 即可。

---

## 场景一：扫描本地 CDP 端口

默认扫描端口范围 **9000–10000**：

```json
{"action": "list_cdp_targets"}
```

指定单个端口：

```json
{"action": "list_cdp_targets", "port": 9222}
```

自定义扫描范围：

```json
{"action": "list_cdp_targets", "port_min": 8000, "port_max": 12000}
```

适用场景：

- 用户已经手动启动了带远程调试端口的 Chrome
- 你不知道具体端口，先扫描确认
- 需要在连接前确认本机有哪些可附着目标

---

## 场景二：连接已有 Chrome

连接已存在的 CDP 端点：

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

特点：

- 连接成功后，可以继续使用 `open`、`snapshot`、`click`、`type` 等常规操作
- 这是**附着到外部浏览器**，不是 QwenPaw 自己启动的新进程
- `stop` 时只断开连接，**不会关闭外部浏览器**
- 当前也受 idle auto-stop 管理，但 external CDP 的 auto-stop 语义是“自动断开，不关闭外部浏览器”

适用场景：

- 用户已经打开自己的 Chrome，并希望 agent 直接接管
- 需要附着到用户已有登录态 / 已打开标签页

---

## 场景三：显式指定 cdp_port 启动

如果用户明确要求使用固定端口，或需要把端点提供给其他工具，可以在 `start` 时指定 `cdp_port`：

```json
{"action": "start", "cdp_port": 9222}
```

如需同时打开可见窗口：

```json
{"action": "start", "headed": true, "cdp_port": 9222}
```

当前行为说明：

- 如果显式指定的 `cdp_port` 已被占用，会直接报错，不会强行复用
- 如果不指定 `cdp_port`，默认会自动挑选空闲端口，通常可避免多 workspace 冲突
- 自动挑空闲端口仍存在极小 race window：在“找到空闲端口”和“Chrome 真正绑定端口”之间理论上可能被别的进程抢占；当前失败时会清理并报错，但不会自动重试

因此：

- **用户没明确要求端口时，不要主动传 `cdp_port`**
- **用户明确要求固定端口 / 外部共享时，才显式传 `cdp_port`**

---

## 多 workspace 与端口占用

当前多 workspace 下的端口策略是：

- **显式指定端口**：先检测 `127.0.0.1:cdp_port` 是否已占用；若已占用则直接失败，提示用户换端口或先停止旧进程
- **未显式指定端口**：通过自动选空闲端口来降低冲突概率

这意味着：

- 多个 workspace 同时使用默认启动，通常可以并存
- 如果多个 workspace 都要求同一个固定 `cdp_port`，后启动的那个会因为端口已占用而失败

---

## stop 行为

CDP 相关 stop 需要区分两类：

### 1. QwenPaw 自己启动的 managed CDP

例如：

```json
{"action": "start"}
```

或：

```json
{"action": "start", "cdp_port": 9222}
```

这类浏览器由 QwenPaw 自行启动并持有进程，`stop` 时会：

- 断开 Playwright / CDP 连接
- 关闭该浏览器进程

### 2. 外部 CDP 浏览器

例如：

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

这类浏览器不是 QwenPaw 启动的，`stop` 时只会：

- 断开连接
- **不会关闭外部浏览器进程**

---

## 与 browser_visible 的分工

- **browser_visible**：解决“是否显示窗口”“是否改走 private_mode”
- **browser_cdp**：解决“是否连接 / 暴露 / 指定 / 扫描 CDP 端口”

简单说：

- 用户关心“看得见窗口” → 先想 browser_visible
- 用户关心“连接现有浏览器 / 指定调试端口 / 给别人共享” → 先想 browser_cdp

---

## 注意

- 默认 `start` 虽然底层使用 managed CDP，但这属于 tool 的内部默认实现，不代表每次都要把 CDP 概念暴露给用户
- 使用显式 CDP 能力前，应提醒用户存在敏感数据暴露风险
- external CDP 的 auto-stop 是“自动断开”，不是“自动关闭用户浏览器”
- 当前 activity 主要由 tool 操作刷新；用户手动在浏览器窗口中的本地交互，通常不会刷新 idle 计时
- `private_mode` 是每次 `start` 的显式参数，不作为 workspace 持久状态保存
