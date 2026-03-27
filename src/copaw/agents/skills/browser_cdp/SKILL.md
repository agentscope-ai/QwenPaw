---
name: browser_cdp
description: "当用户明确希望连接到已运行的 Chrome 浏览器（connect_cdp）、扫描本地 CDP 端口、或以暴露 CDP 端口的方式启动浏览器（start + cdp_port）时，使用本 skill。用户没有明确提到 CDP、共享浏览器或远程调试时，启动浏览器不得携带 cdp_port，也不得使用 connect_cdp。CDP 模式会暴露浏览器历史、Cookies 等敏感信息，使用前须告知用户；同一 workspace 同时只能运行或连接一个浏览器。"
metadata:
  {
    "builtin_skill_version": "1.0",
    "copaw":
      {
        "emoji": "🔌",
        "requires": {}
      }
  }
---

# 浏览器 CDP 连接参考

**Chrome DevTools Protocol（CDP）** 允许外部程序连接并控制一个已在运行的 Chrome 进程。本 skill 覆盖三类场景：

1. **扫描本地 CDP 端口** — 发现正在运行的可连接 Chrome
2. **连接已有 Chrome** — 附加到外部 Chrome，不影响其运行
3. **启动暴露 CDP 端口的浏览器** — 让 Playwright 启动的浏览器对外可见

> **⚠️ 隐私提示：使用 CDP 前请知晓**
>
> - **默认模式**（`start` 不带 `cdp_port`）：浏览器完全由 Playwright 私有管理，历史记录、Cookies、登录态**不会暴露**给任何外部程序。
> - **CDP 模式**（`start` + `cdp_port` 或 `connect_cdp`）：任何能访问该端口的程序都可以读取浏览器的**完整历史记录、Cookies、当前页面内容、已保存密码**等敏感信息。仅在信任的本地环境中使用，不要在公共网络或多用户服务器上暴露 CDP 端口。

> **⚠️ 单实例限制：一个 workspace 同时只能运行/连接一个浏览器**
>
> 无论是 Playwright 启动的浏览器还是 CDP 连接，同一 workspace 内同一时间只允许存在一个。需要切换时，必须先执行 `stop`，再启动或连接新的浏览器。

---

## 何时使用

**仅在用户明确表达以下意图时才使用本 skill：**

- 用户说：「连接到我已打开的 Chrome」「扫描一下本地有没有可连接的浏览器」
- 用户明确希望多个 agent 或外部工具**共享**同一个浏览器实例
- 用户明确要求浏览器**对外可见/可调试**
- 用户主动提到 CDP、远程调试端口等概念

**以下情况不要使用 CDP 模式，直接用普通 `start` 即可：**

- 用户只是说「打开浏览器」「帮我打开某网站」，没有提到共享或调试
- 用户没有明确说明需要暴露浏览器给其他程序
- 不确定用户是否了解 CDP 的隐私风险

**使用前须告知用户 CDP 模式会暴露浏览器历史、Cookies 等敏感信息，确认用户知情后再操作。**

---

## 场景一：扫描本地 CDP 端口

默认扫描端口范围 **9000–10000**，并发探测，速度很快。

```json
{"action": "list_cdp_targets"}
```

指定单个端口：
```json
{"action": "list_cdp_targets", "port": 9222}
```

自定义扫描范围（未找到时可扩大范围）：
```json
{"action": "list_cdp_targets", "port_min": 8000, "port_max": 12000}
```

**成功返回示例：**
```json
{
  "ok": true,
  "found": {
    "9222": [{"title": "New Tab", "url": "chrome://newtab/", ...}]
  },
  "message": "Found CDP endpoints on port(s): 9222"
}
```

**未找到时** 返回 `ok: false`，并提示扩大范围或确认 Chrome 是否以 `--remote-debugging-port=N` 启动。

---

## 场景二：连接已有 Chrome（connect_cdp）

先扫描到端口后，再连接：

```json
{"action": "connect_cdp", "cdp_url": "http://localhost:9222"}
```

- 连接成功后可正常使用 `open`、`snapshot`、`click`、`type` 等所有操作
- **不会影响 Chrome 进程**：执行 `stop` 时只断开 Playwright 连接，Chrome 继续运行
- 连接期间每次操作前会自动检查连接是否正常，断开时返回错误提示重新连接
- **隐私风险**：连接后 agent 可读取该 Chrome 的完整 Cookies、历史记录、当前页面内容，请确认用户知情
- **单实例**：如果当前已有浏览器在运行（无论是 Playwright 启动的还是另一个 CDP 连接），必须先 `stop` 再连接

---

## 场景三：启动带 CDP 端口的浏览器

让 Playwright 启动浏览器时暴露指定 CDP 端口，其他工具可同时连接：

```json
{"action": "start", "cdp_port": 9222}
```

启动成功后返回：
```json
{
  "ok": true,
  "message": "Browser started with CDP port 9222",
  "cdp_url": "http://localhost:9222"
}
```

之后可用 `list_cdp_targets` 验证端口已暴露，或将 `cdp_url` 提供给其他 agent / 工具连接。

**注意：**
- **隐私风险**：暴露端口后，任何能访问该端口的程序均可读取浏览器历史、Cookies 及页面内容，操作前请告知用户
- **单实例**：当前 workspace 已有浏览器运行时，无法再启动新浏览器，必须先 `stop`

---

## Cookies 与数据持久化

三种启动方式都复用同一个 workspace 的 `user_data_dir`：

| 启动方式 | Cookies 复用 | 对外可访问 |
|---|---|---|
| `start`（默认） | ✅ | ❌ |
| `start` + `cdp_port` | ✅ | ✅ |
| `connect_cdp`（已有 Chrome） | ✅（若该 Chrome 使用了相同目录） | ✅ |

---

## stop 行为说明

两种 CDP 模式对 `stop` 的响应截然不同：

- **`connect_cdp`**：agent 附加到用户已有的 Chrome，**不拥有**该进程。执行 `stop` 只断开 Playwright 连接，Chrome 继续运行，用户页面不受影响。
- **`start` + `cdp_port`**：agent 自行启动并管理浏览器。执行 `stop` 会**终止 Chrome 进程**，其他通过该 CDP 端口连接的外部工具也会断线。

| 当前状态 | stop 效果 |
|---|---|
| CDP 连接（`connect_cdp`） | 仅断开 Playwright 连接，**Chrome 进程继续运行** |
| Playwright 启动的浏览器（`start` + `cdp_port`） | **终止 Chrome 进程**，外部 CDP 连接同时断线 |

---

## 清除缓存

```json
{"action": "clear_browser_cache"}
```

- 浏览器运行中：通过 CDP 清除 HTTP 缓存，**无需重启**
- 浏览器已停止：删除磁盘上的缓存目录
- Cookies 和 Local Storage **不受影响**

---

## 常见问题

**Chrome 启动后无法扫描到 CDP 端口？**

Chrome 必须以独立进程 + 指定 `user-data-dir` 启动，否则新实例会被移交给已有进程：

```bash
pkill -x "Google Chrome"   # 先关闭已有 Chrome
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-debug-9222 \
  --no-first-run
```

**CDP 连接中断后怎么恢复？**

任何操作都会返回：
```json
{"ok": false, "error": "CDP connection lost (was: http://localhost:9222). Reconnect with action='connect_cdp'."}
```
按提示重新执行 `connect_cdp` 即可。
