# 浏览器

浏览器是 QwenPaw 的内置能力。Agent 通过 `browser` 工具编写异步 Python 代码，驱动一个真实的浏览器完成打开网页、填表、点击、读取页面内容等任务。它既可以启动一个独立的浏览器，也可以接入你自己日常使用、已经登录的 Chrome。

> **Beta 功能**：新版统一浏览器默认启用。如果你需要旧版行为，可以在控制台切回旧版实现；切换后需要重启服务才会生效。

---

## 两种浏览器

| 用哪个浏览器        | 说明                                                    | 前置条件                           |
| ------------------- | ------------------------------------------------------- | ---------------------------------- |
| **独立浏览器**      | QwenPaw 自己启动一个 Chromium，与你的日常浏览器互不干扰 | 无                                 |
| **你自己的 Chrome** | 直接在你已登录的 Chrome 里开标签页工作，你能全程看见    | 安装 [Chrome 浏览器扩展](./chrome) |

两者用的是同一个 `browser` 工具和同一套 SDK，Agent 的写法完全一样，区别只在于"用谁的浏览器、带谁的登录态"。

---

## 工作方式

Agent 使用的是 QwenPaw 自带的 Browser SDK（不是 Playwright），API 是封闭的一套：只有 SDK 明确提供的方法可用。完整 API 参考随内置的 **browser** 技能一起交付给 Agent，你不需要手动配置。

每一轮操作遵循固定纪律：

1. **感知** — 先读取页面当前状态，确认自己看到了什么；
2. **操作** — 再执行导航、点击、填写等动作；
3. **验证** — 操作完成后重新感知，确认结果符合预期才声明成功。

所以在对话中你会看到 Agent 反复"看一眼页面再动手"，这是有意设计的：它只陈述本轮真实观察到的内容，卡住时会说明卡在哪一步，而不是猜一个完整答案。

### 需要你介入的时刻

遇到登录、验证码、二次验证（2FA）等必须由人完成的步骤，Agent 会停下来把这一步交还给你，并说明卡在哪里，而不会尝试自动化这些流程。你在浏览器里完成之后，让它继续即可。

> 无头运行（没有可见窗口）时无法把步骤交还给人。需要人工介入的任务，请确保浏览器有界面——见下方 `headless` 配置。

---

## 浏览器身份

**身份**决定 Agent 以谁的名义上网、带哪份登录态。

| 身份           | 含义                                         | 用哪个浏览器    |
| -------------- | -------------------------------------------- | --------------- |
| `auto`（默认） | Chrome 扩展已连接时取 `user`，否则取 `guest` | 视情况          |
| `user`         | 你真实的 Chrome，带你已登录的会话            | 你自己的 Chrome |
| `avatar`       | 一个持久化的备用身份，登录态会保留到下次     | 独立浏览器      |
| `guest`        | 无痕访客，关闭即丢弃                         | 独立浏览器      |

身份的优先级是：Agent 在代码里显式指定 > `browser.identity` 配置 > `auto` 规则。

- 显式要求 `user` 但 Chrome 扩展未连接时，Agent 会收到明确提示：先连接 Chrome 扩展，或改用 `avatar` / `guest`；
- `auto` 在同样情况下会自动落到 `guest`，任务不会中断。

> `user` 身份使用的是你真实的浏览器和真实的登录态，Agent 在其中的操作与你自己点击的效果等同。请只在你愿意让它代劳的网站上使用。

---

## 独立浏览器从哪来

`browser.backend` 只影响 `avatar` 和 `guest` 使用的独立浏览器；`user` 身份始终走 Chrome 扩展，与该项无关。

| 取值           | 行为                                                                               |
| -------------- | ---------------------------------------------------------------------------------- |
| `auto`（默认） | 由 QwenPaw 启动并管理一个 Chromium                                                 |
| `launch`       | 同 `auto`，显式声明由 QwenPaw 启动                                                 |
| `managed_cdp`  | 启动一个带调试端口的 Chromium 再通过 CDP 控制；端口见 `cdp_port`，`0` 表示自动分配 |
| `connect_cdp`  | 连接到一个已经在运行的 CDP 端点；必须同时设置 `cdp_url`                            |

默认情况下 QwenPaw 优先使用你系统默认浏览器的 Chromium 内核可执行文件，找不到时回退到 QwenPaw 自带的 Chromium。可用 `use_system_default` 和 `executable_path` 干预。

---

## 切换新旧实现

在控制台进入 **智能体 → 工具**，找到 **browser** 工具卡片，用卡片上的按钮切换：

| 按钮           | 含义                                       |
| -------------- | ------------------------------------------ |
| **新版(Beta)** | 使用新版统一浏览器能力（默认）             |
| **旧版(兼容)** | 使用原有浏览器实现，适用于需要旧行为的场景 |

两者的调用方式不同：新版是 `browser(code)`——Agent 写一段异步 Python；旧版按 `action` 参数逐个动作调用。该开关写入全局配置，对所有智能体生效。

> 切换后卡片上会提示"重启服务后将切换为：…"。**必须重启 QwenPaw 服务**才会真正生效，这一项不支持热加载。

---

## 配置项

浏览器配置位于全局 `~/.qwenpaw/config.json` 的 `browser` 段，对所有智能体生效：

```json
{
  "browser": {
    "experimental": true,
    "backend": "auto",
    "identity": "auto",
    "headless": "auto"
  }
}
```

| 字段                       | 类型               | 默认值   | 说明                                                                                    |
| -------------------------- | ------------------ | -------- | --------------------------------------------------------------------------------------- |
| `experimental`             | bool               | `true`   | 是否使用新版统一浏览器；`false` 切回旧版实现。**改动需重启服务**                        |
| `backend`                  | string             | `"auto"` | 独立浏览器的获取方式：`auto` / `launch` / `managed_cdp` / `connect_cdp`                 |
| `identity`                 | string             | `"auto"` | 浏览器身份：`auto` / `user` / `avatar` / `guest`                                        |
| `cdp_url`                  | string \| null     | `null`   | `connect_cdp` 时必填，指向已有的 CDP 端点                                               |
| `cdp_port`                 | int                | `0`      | `managed_cdp` 的调试端口，`0` 表示自动分配（取值 0-65535）                              |
| `engine`                   | string             | `"auto"` | 浏览器内核，仅支持 `auto` / `chromium`；旧配置中的 `webkit`、`firefox` 会回退到 `auto`  |
| `channel`                  | string \| null     | `null`   | Chromium 发布通道（如 `chrome`、`msedge`）                                              |
| `executable_path`          | string \| null     | `null`   | 指定浏览器可执行文件路径                                                                |
| `headless`                 | string             | `"auto"` | `auto` 表示容器内或无图形界面时无头运行，否则显示窗口；也可写 `"true"` / `"false"` 强制 |
| `user_data_dir`            | string \| null     | `null`   | 自定义独立浏览器的数据目录；不填则按工作区自动分配                                      |
| `args`                     | string[]           | `[]`     | 追加的浏览器启动参数                                                                    |
| `viewport`                 | [int, int] \| null | `null`   | 视口尺寸，两个值都必须为正整数                                                          |
| `proxy`                    | string \| null     | `null`   | 代理地址                                                                                |
| `use_system_default`       | bool               | `true`   | 优先使用系统默认浏览器的 Chromium 可执行文件                                            |
| `idle_ttl_seconds`         | float              | `600`    | 浏览器整体空闲多久后关闭（秒）                                                          |
| `session_idle_ttl_seconds` | float              | `900`    | 单个会话空闲多久后回收（秒）                                                            |
| `exec_timeout_seconds`     | float              | `120`    | 单次 `browser` 调用的执行超时（秒）                                                     |

> **已废弃字段**：`backend: "extension"` 请改用 `identity: "user"`；`context` 请改用 `identity`（`profile` → `avatar`，`incognito` → `guest`）。旧配置仍可加载，但会在日志中给出告警。

---

## 数据存放位置

独立浏览器的数据按智能体工作区隔离，不会与你日常浏览器混用：

| 目录                                      | 内容                                                      |
| ----------------------------------------- | --------------------------------------------------------- |
| `workspaces/{agent_id}/.browser-profile/` | 独立浏览器的持久化 profile（`avatar` 身份的登录态在这里） |
| `workspaces/{agent_id}/.browser-cdp/`     | `managed_cdp` 模式下的浏览器数据目录                      |
| `workspaces/{agent_id}/browser/`          | 旧版兼容模式的浏览器数据                                  |

`user` 身份不落这些目录——它用的是你自己 Chrome 的 profile。浏览器进程按 `idle_ttl_seconds` / `session_idle_ttl_seconds` 自动回收，服务退出时一并关闭。

---

## 常见问题

### 切换了新旧实现却没有变化？

这一项不热加载。请重启 QwenPaw 服务后再试；工具卡片上出现"重启服务后将切换为：…"说明改动已保存、等待重启。

### Agent 提示需要连接 Chrome 扩展？

说明身份被显式指定为 `user`，但 Chrome 扩展当前没有连接。安装并连接 [Chrome 浏览器扩展](./chrome)，或把 `browser.identity` 改为 `avatar` / `guest`。

### 服务器上没有图形界面，能用吗？

可以。`headless` 为 `auto` 时会在容器内或无显示环境自动无头运行。但需要人工完成登录、验证码的任务在无头模式下无法交还给你，这类任务请在有界面的环境执行。

### `connect_cdp` 启动失败？

`connect_cdp` 必须同时设置 `browser.cdp_url`，否则配置校验会直接报错。请确认目标浏览器已开启调试端口且地址可达。

### 为什么每次任务都要重新登录？

`guest` 身份是无痕访客，关闭即丢弃。需要保留登录态请改用 `avatar`（独立浏览器的持久化身份），或用 `user` 直接复用你自己 Chrome 的登录态。

---

## 相关页面

- [Chrome 浏览器扩展](./chrome) — 把 QwenPaw 连接到你自己的 Chrome
- [MCP 与内置工具](./mcp) — 查看和管理 Agent 可用的工具
- [Skills](./skills) — 内置 **browser** 技能与 SDK 参考的交付方式
- [配置与工作目录](./config) — 全局配置文件与目录结构
