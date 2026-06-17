# 插件系统

QwenPaw 提供了插件系统，允许用户扩展 QwenPaw 的功能。

## 概述

插件系统支持以下扩展能力：

- **Provider 插件**：添加新的 LLM Provider 和模型
- **Hook 插件**：在应用启动/关闭时执行自定义代码
- **Command 插件**：注册自定义的 `/command` 魔法命令
- **HTTP API 插件**：通过 FastAPI `APIRouter` 在 `/api` 下暴露自定义 REST 接口
- **前端扩展插件**：在浏览器中运行的 JS 插件，共享宿主的 React / Ant Design 运行时，通过声明式 `window.QwenPaw.*` API 扩展界面——注册侧边栏菜单、页面路由、UI 插槽、聊天定制等，无需修改宿主代码

## 插件管理

### 安装插件

从本地目录安装：

```bash
qwenpaw plugin install /path/to/plugin
```

从 URL 安装（支持 ZIP 文件）：

```bash
qwenpaw plugin install https://example.com/plugin.zip
```

强制重新安装：

```bash
qwenpaw plugin install /path/to/plugin --force
```

**注意**：插件操作只能在 QwenPaw 离线时执行。

### 列出已安装插件

```bash
qwenpaw plugin list
```

输出示例：

```
Installed Plugins:
==================

my-provider (v1.0.0)
  Custom LLM provider integration
  Author: Developer Name
  Path: /Users/user/.qwenpaw/plugins/my-provider
```

### 查看插件详情

```bash
qwenpaw plugin info <plugin-id>
```

### 卸载插件

```bash
qwenpaw plugin uninstall <plugin-id>
```

## 插件开发

### 后端插件

#### 基本结构

每个插件至少需要两个文件：

```
my-plugin/
├── plugin.json      # 插件清单（必需）
├── plugin.py        # 入口点（后端必需）
└── README.md        # 文档（推荐）
```

#### plugin.json

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "general",
  "description": "Plugin description",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "0.1.0",
  "meta": {}
}
```

#### 清单字段说明

| 字段             | 类型            | 必填 | 说明                                                                                                                                             |
| ---------------- | --------------- | ---- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `id`             | `string`        | 是   | 插件唯一标识，同时作为安装目录名，不能包含路径分隔符。                                                                                           |
| `version`        | `string`        | 是   | 插件语义化版本号（例如 `1.0.0`）。                                                                                                               |
| `name`           | `string` 或对象 | 否   | 显示名称，缺省取 `id`。也可写成 `{"zh-CN": "...", "en-US": "..."}`，运行时按"英文优先"的顺序取第一个非空值。                                     |
| `type`           | `string`        | 否   | 取值之一：`tool`、`provider`、`hook`、`command`、`frontend`、`general`。省略时会按 `meta` / `entry` 推断（仅为兼容旧插件），新插件建议显式声明。 |
| `description`    | `string` 或对象 | 否   | 插件列表里的简短描述，支持本地化对象形式（同 `name`）。                                                                                          |
| `author`         | `string`        | 否   | 作者或组织名称。                                                                                                                                 |
| `entry.backend`  | `string`        | 否\* | 相对插件目录的 Python 入口文件路径，需在其中导出 `plugin`。                                                                                      |
| `entry.frontend` | `string`        | 否\* | 已构建的前端 bundle 路径（如 `dist/index.js`）。                                                                                                 |
| `dependencies`   | `string[]`      | 否   | Python 依赖列表，安装时通过 pip / uv 自动安装。                                                                                                  |
| `min_version`    | `string`        | 否   | 需要的最低 QwenPaw 版本，缺省 `0.1.0`。                                                                                                          |
| `meta`           | `object`        | 否   | 自由元数据。前端 UI 与 `type` 推断都会读取（如 `meta.tools[]`、`meta.hook_type`、`meta.provider_id`）。                                          |
| `entry_point`    | `string`        | 否   | **遗留字段。** 等价于 `entry.backend`，仅为兼容老插件保留，新插件请使用 `entry.backend`。                                                        |

\* `entry.backend`、`entry.frontend`（或遗留 `entry_point`）至少需要提供其中之一。

#### `type` 取值

| 取值       | 适用场景                                             |
| ---------- | ---------------------------------------------------- |
| `tool`     | 注册一个或多个 Agent 工具（LLM 可调用的函数）。      |
| `provider` | 注册自定义 LLM 提供商 / 模型端点。                   |
| `hook`     | 在应用启动 / 关闭时执行代码。                        |
| `command`  | 注册 `/slash` 控制命令。                             |
| `frontend` | 提供前端 JS bundle，由 UI 动态加载。                 |
| `general`  | 兜底类型，用于组合型插件或不属于以上任何类别的插件。 |

#### plugin.py

```python
# -*- coding: utf-8 -*-
"""My Plugin Entry Point."""

from qwenpaw.plugins.api import PluginApi
import logging

logger = logging.getLogger(__name__)


class MyPlugin:
    """My Plugin."""

    def register(self, api: PluginApi):
        """Register plugin capabilities.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering my plugin...")

        # 注册你的功能
        # api.register_provider(...)
        # api.register_startup_hook(...)
        # api.register_shutdown_hook(...)

        logger.info("✓ My plugin registered")


# Export plugin instance
plugin = MyPlugin()
```

### 前端插件

前端插件是运行在浏览器端的 JavaScript 扩展。与后端插件通过 Python `PluginApi` 注册能力不同，前端插件通过全局 `window.QwenPaw.*` API 声明式地扩展 Console 界面。

**加载生命周期：**

1. Console 启动，在 `window.QwenPaw` 上挂载 Host SDK（React、antd 等共享依赖）和注册 API（menu、route、slot、chat 等命名空间）
2. Console 请求 `/frontend_plugin` 获取已启用的前端插件列表
3. 逐一下载各插件的 JS bundle，通过 Blob URL 动态导入执行
4. 插件代码执行，调用 `window.QwenPaw.*` 注册菜单、路由、聊天定制等 UI 扩展
5. 注册立即生效——菜单出现在侧边栏、路由可导航、聊天区域呈现定制内容

插件无需声明使用了哪些扩展点；系统通过 `pluginId` 自动追踪所有注册。卸载或禁用插件时，通过 `dispose()` 或 `chat.disposeAll(pluginId)` 清理全部注册。

**设计特点：**

| 特点              | 说明                                                                             |
| ----------------- | -------------------------------------------------------------------------------- |
| **共享运行时**    | React、ReactDOM、Ant Design 由宿主提供，插件无需打包，避免版本冲突和体积膨胀     |
| **声明式注册**    | 三个核心动词：`set`（设置 / 合并属性）、`render`（替换渲染）、`add`（追加项目）  |
| **pluginId 隔离** | 所有注册方法以 `pluginId` 为第一参数，系统据此追踪来源、检测冲突、支持按插件清理 |
| **可撤销**        | 每个注册返回 `{ dispose() }` 对象，调用即撤销，支持热重载和插件卸载              |
| **国际化**        | 文本字段支持 `Localized<T>` 类型——传入 `(locale) => string` 函数按语言返回不同值 |

**扩展点一览：**

| 命名空间                          | 能力                            | 典型用途                                        |
| --------------------------------- | ------------------------------- | ----------------------------------------------- |
| `host`                            | 共享依赖、React Hooks、认证请求 | 获取 React / antd、读取主题和语言、调用后端 API |
| `menu`                            | 侧边栏菜单项                    | 添加导航入口                                    |
| `route`                           | 页面路由                        | 注册新页面、包装已有页面                        |
| `slot`                            | 通用 UI 插槽                    | 向 Header / Sidebar 等预设位置注入内容          |
| `chat.welcome`                    | 欢迎界面                        | 自定义问候语、推荐提示词                        |
| `chat.theme`                      | 聊天主题色                      | 更换主色调                                      |
| `chat.leftHeader` / `rightHeader` | 聊天头部                        | 设置品牌 Logo、添加操作按钮                     |
| `chat.sender`                     | 输入框                          | 自定义 placeholder、输入建议                    |
| `chat.actions` / `requestActions` | 消息操作按钮                    | 在消息下方添加自定义操作                        |
| `chat.requestPayload`             | 外发聊天请求体                  | 请求发送到后端前追加或改写自定义字段            |
| `chat.request` / `response`       | 消息气泡                        | 在消息前后追加内容或完全替换渲染                |
| `chat.toolRender`                 | 工具调用渲染                    | 自定义工具结果展示（如天气卡片）                |
| `chat.card`                       | 自定义卡片                      | 注册新的卡片类型                                |
| `audit`                           | 审计与调试                      | 查看所有扩展注册记录                            |

#### 基本结构

```
my-plugin/
├── plugin.json      # 插件清单（必需）
├── src/
│   └── index.tsx    # 入口点，调用 window.QwenPaw.* API
├── package.json     # 依赖声明
├── tsconfig.json    # TypeScript 配置
└── vite.config.ts   # 构建配置
```

#### plugin.json

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "type": "frontend",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

#### src/index.tsx

插件入口文件在加载时执行，通过 `window.QwenPaw.*` API 注册扩展：

```tsx
const { React, antd } = window.QwenPaw.host;
const pluginId = "my-plugin";

// 调用 window.QwenPaw.* API 注册菜单、路由、聊天定制等
// 详见下方「前端扩展 API」
```

#### 构建工具链

**package.json**：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "scripts": { "build": "vite build" },
  "devDependencies": {
    "vite": "^5.0.0",
    "typescript": "^5.0.0",
    "@vitejs/plugin-react": "^4.0.0"
  }
}
```

**tsconfig.json**：

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react",
    "strict": false,
    "skipLibCheck": true
  }
}
```

**vite.config.ts**：

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react({ jsxRuntime: "classic" })],
  build: {
    lib: {
      entry: "src/index.tsx",
      formats: ["es"],
      fileName: () => "index.js",
    },
    rollupOptions: { external: ["react", "react-dom"] },
  },
});
```

`jsxRuntime: "classic"` 将 JSX 编译为 `React.createElement`，使用宿主提供的 `React`；`external` 避免打包 React，使用应用已加载的版本。

#### 构建和安装

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/my-plugin/
qwenpaw app
```

可将 `console/src/plugins/types/qwenpaw.d.ts` 复制到插件项目中作为 `qwenpaw-host.d.ts`，获得完整的类型提示。

## 前端扩展 API

前端插件通过 `window.QwenPaw.*` API 扩展 Console 界面，无需修改宿主代码。所有注册方法第一个参数是 `pluginId`，每个注册返回 `{ dispose() }` 对象用于撤销。

### Host SDK — `window.QwenPaw.host`

宿主共享依赖，插件无需打包这些库：

```ts
host.React                        // React 库
host.ReactDOM                     // ReactDOM 库
host.antd                         // Ant Design 组件库
host.antdIcons                    // Ant Design 图标库
host.apiBaseUrl                   // API 基础 URL
host.getApiUrl(path: string)      // 拼接完整 API URL
host.getApiToken(): string | null // 获取当前认证 Token
```

**React Hooks（在 React 组件内使用）：**

```ts
const theme = window.QwenPaw.host.useTheme(); // "light" | "dark"
const locale = window.QwenPaw.host.useLocale(); // "zh" | "en"
const agent = window.QwenPaw.host.useSelectedAgent(); // { id: string }
const session = window.QwenPaw.host.useCurrentSession(); // { id: string } | null
```

**命令式获取（可在任意位置调用）：**

```ts
const agentId = window.QwenPaw.host.getSelectedAgentId();
const sessionId = window.QwenPaw.host.getCurrentSessionId();
```

**认证代理请求（自动注入 Authorization 和 X-Agent-Id 请求头）：**

```ts
const resp = await window.QwenPaw.host.fetch("/api/v1/my-endpoint", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "test" }),
});
const data = await resp.json();
```

### 侧边栏菜单 — `window.QwenPaw.menu`

| 方法       | 签名                                     | 说明             |
| ---------- | ---------------------------------------- | ---------------- |
| `add`      | `(pluginId, item \| item[]): Disposable` | 添加菜单项       |
| `replace`  | `(pluginId, targetId, item): Disposable` | 替换已有菜单项   |
| `remove`   | `(targetId): void`                       | 移除菜单项       |
| `snapshot` | `(location?): MenuItem[]`                | 获取当前菜单快照 |

**MenuItem 参数：**

```ts
{
  id: string;                    // 全局唯一，如 "my-plugin.foo"
  label: string | (() => ReactNode);
  icon?: ReactComponent | ReactNode;
  route?: string;                // 点击时导航到的路由 id
  parentId?: string;             // 挂在哪个分组下
  location?: "primary.agentScoped" | "primary.settings" | "userMenu";
  before?: string;               // 排在某个 id 之前
  after?: string;                // 排在某个 id 之后
  order?: number;                // 数值越小越靠前
  visible?: () => boolean;       // 动态控制显隐
  isGroup?: boolean;             // 作为分组标题
  divider?: boolean;             // 渲染为水平分割线
}
```

### 页面路由 — `window.QwenPaw.route`

| 方法      | 签名                                          | 说明                     |
| --------- | --------------------------------------------- | ------------------------ |
| `add`     | `(pluginId, route \| route[]): Disposable`    | 注册新路由               |
| `replace` | `(pluginId, targetId, component): Disposable` | 替换已有路由的组件       |
| `wrap`    | `(pluginId, targetId, wrapper): Disposable`   | 包装已有路由（洋葱模式） |
| `remove`  | `(targetId): void`                            | 移除路由                 |

**Route 参数：**

```ts
{
  id: string; // 全局唯一，如 "my-plugin.home"
  path: string; // URL 路径，支持 react-router 模式
  component: React.ComponentType; // 页面组件
}
```

**wrap 示例（为已有页面加顶部 banner）：**

```tsx
window.QwenPaw.route.wrap("my-plugin", "core.chat", (Inner) => {
  return () => (
    <div>
      <div style={{ background: "#fff3cd", padding: 8, textAlign: "center" }}>
        Beta Feature
      </div>
      <Inner />
    </div>
  );
});
```

### 通用 UI 插槽 — `window.QwenPaw.slot`

| 方法       | 签名                                          | 说明                                          |
| ---------- | --------------------------------------------- | --------------------------------------------- |
| `fill`     | `(pluginId, name, render, opts?): Disposable` | 向插槽追加内容（可多个共存）                  |
| `replace`  | `(pluginId, name, render, opts?): Disposable` | 替换插槽内容（最后注册的生效，屏蔽所有 fill） |
| `snapshot` | `(): SlotInfo[]`                              | 获取所有已注册的插槽信息                      |

**内置插槽：**

| 插槽名              | 类型    | UI 位置                        |
| ------------------- | ------- | ------------------------------ |
| `header.logo`       | replace | 顶部导航栏最左侧               |
| `header.left`       | fill    | 顶部导航栏左区（Logo 右边）    |
| `header.right`      | fill    | 顶部导航栏右区（设置按钮左边） |
| `sider.top`         | fill    | 侧边栏顶部（Agent 选择器下方） |
| `sider.bottom`      | fill    | 侧边栏底部（菜单下方）         |
| `content.statusBar` | fill    | 主内容区顶部                   |
| `overlay.global`    | fill    | 全局覆盖层                     |

**示例：**

```tsx
// 替换 Header Logo
window.QwenPaw.slot.replace("my-plugin", "header.logo", (defaultLogo) => {
  return <img src="https://example.com/logo.svg" style={{ height: 24 }} />;
});
```

### 聊天欢迎界面 — `chat.welcome`

```tsx
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => (locale.startsWith("zh") ? "你好！" : "Hello!"),
  description: "I specialize in data analysis.",
  avatar: "https://example.com/avatar.png",
  nick: "My Bot",
  prompts: [
    { label: "分析数据", value: "请分析上传的数据集" },
    { label: "生成图表", value: "根据数据创建柱状图" },
  ],
});

// 或完全替换欢迎界面
window.QwenPaw.chat.welcome.render("my-plugin", (props) => {
  return <div>Custom Welcome</div>;
});
```

### 聊天主题 — `chat.theme`

```ts
window.QwenPaw.chat.theme.set("my-plugin", {
  colorPrimary: "#1890ff",
});
```

### 聊天头部 — `chat.leftHeader` / `chat.rightHeader`

```tsx
// 设置左上角标题
window.QwenPaw.chat.leftHeader.set("my-plugin", {
  title: "My Brand",
  logo: <img src="logo.svg" style={{ height: 20 }} />,
});

// 在右上角添加按钮
window.QwenPaw.chat.rightHeader.add(
  "my-plugin",
  <button
    onClick={() => alert("Plugin action!")}
    style={{ border: "none", background: "none", cursor: "pointer" }}
  >
    My Button
  </button>,
  { id: "my-plugin.btn", order: 10 },
);
```

### 输入框 — `chat.sender`

```ts
// 自定义 placeholder
window.QwenPaw.chat.sender.set("my-plugin", {
  placeholder: "Ask me anything...",
  disclaimer: "Responses may not be accurate.",
});

// 添加输入建议
window.QwenPaw.chat.sender.addSuggestion("my-plugin", {
  id: "my-plugin.suggestions",
  items: [
    { label: "/analyze", value: "analyze" },
    { label: "/visualize", value: "visualize" },
  ],
});
```

### 消息操作按钮 — `chat.actions` / `chat.requestActions`

```tsx
// AI 回复消息下方添加操作按钮
window.QwenPaw.chat.actions.add("my-plugin", {
  id: "my-plugin.star",
  icon: <span>⭐</span>,
  onClick: ({ data }) => console.log("Starred:", data),
});

// 用户消息下方添加操作按钮
window.QwenPaw.chat.requestActions.add("my-plugin", {
  id: "my-plugin.edit",
  icon: <span>✏️</span>,
  onClick: ({ data }) => console.log("Edit:", data),
});
```

### 请求体转换 — `chat.requestPayload`

使用 `chat.requestPayload.add` 可以在 Console 将聊天请求发送到后端前改写 `requestBody`。多个转换函数会按 `order` 从小到大执行，入参包含当前 `payload`、解析后的 `sessionId` 和 `selectedAgent`。

```ts
window.QwenPaw.chat.requestPayload.add(
  "my-plugin",
  ({ payload, sessionId, selectedAgent }) => ({
    ...payload,
    request_context: {
      session_id: sessionId,
      agent_id: selectedAgent,
      datasource_id: "ds-123",
    },
  }),
  { id: "my-plugin.request-context", order: 10 },
);
```

转换函数返回新对象时会替换当前请求体；返回 `undefined` 时保持请求体不变。建议使用全局唯一的 `id`，方便审计和卸载时清理。

### 消息气泡自定义 — `chat.request` / `chat.response`

```tsx
// 设置默认 AI 回复的头像和昵称
// 当前会复用 welcome.avatar / welcome.nick，因为默认 ResponseCard 读取这两个字段
window.QwenPaw.chat.response.set("my-plugin", {
  avatar: "https://example.com/bot-avatar.png",
  nick: "My Bot",
});

// 在用户消息前方追加内容
window.QwenPaw.chat.request.prepend("my-plugin", ({ data }) => {
  return <div style={{ fontSize: 10, color: "#999" }}>User</div>;
});

// 在最新 AI 回复下方追加信息条
window.QwenPaw.chat.response.append("my-plugin", ({ data, isLast }) => {
  if (!isLast) return null;
  return (
    <div
      style={{
        background: "#e3f2fd",
        padding: "4px 8px",
        borderRadius: 4,
        fontSize: 12,
      }}
    >
      Powered by My Plugin
    </div>
  );
});

// 完全替换用户消息渲染（可调用 fallback() 保留默认渲染）
window.QwenPaw.chat.request.render("my-plugin", ({ data, fallback }) => {
  return (
    <div style={{ border: "1px dashed #ccc", borderRadius: 8, padding: 4 }}>
      {fallback()}
    </div>
  );
});
```

### 工具调用渲染 — `chat.toolRender`

```tsx
// 注册自定义工具结果渲染组件（props 包含 result, sessionId, messageId）
window.QwenPaw.chat.toolRender("my-plugin", "get_weather", ({ result }) => {
  const data = typeof result === "string" ? JSON.parse(result) : result;
  return (
    <div style={{ padding: 12, border: "1px solid #e8e8e8", borderRadius: 8 }}>
      {data.city}: {data.temperature}°C
    </div>
  );
});
```

### 自定义卡片 — `chat.card`

```ts
window.QwenPaw.chat.card("my-plugin", "my-card", MyCardComponent);
```

### 审计与调试

```ts
// 查看扩展注册记录
console.table(window.QwenPaw.audit.overrides());

// 清理插件的所有 Chat 扩展注册
window.QwenPaw.chat.disposeAll("my-plugin");
```

### 国际化支持

所有支持 `Localized<T>` 类型的字段可传入函数，按语言返回不同值：

```ts
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => (locale.startsWith("zh") ? "你好！" : "Hello!"),
});
```

### 常见错误

| 错误                              | 原因                                 | 解决                                        |
| --------------------------------- | ------------------------------------ | ------------------------------------------- |
| `e.item.render is not a function` | render/prepend/append 传了非函数     | 确保传入 React 组件或返回 ReactNode 的函数  |
| `duplicate id`                    | 两次 `add` 使用了相同 id             | 使用全局唯一 id（推荐 `pluginId.xxx` 格式） |
| Hook 在组件外调用                 | `useTheme()` 等在非 React 上下文使用 | 改用 `getSelectedAgentId()` 等命令式 API    |

## 使用示例

### 示例 1：添加自定义 Provider

假设你想接入一个企业内部的 LLM 服务。

#### 1. 创建插件目录

```bash
mkdir my-llm-provider
cd my-llm-provider
```

#### 2. 创建 plugin.json

```json
{
  "id": "my-llm-provider",
  "name": "My LLM Provider",
  "version": "1.0.0",
  "type": "provider",
  "description": "Custom LLM provider for enterprise",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": ["httpx>=0.24.0"],
  "min_version": "0.1.0",
  "meta": {
    "api_key_url": "https://example.com/get-api-key",
    "api_key_hint": "Get your API key from example.com"
  }
}
```

#### 3. 创建 provider.py

```python
# -*- coding: utf-8 -*-
"""My LLM Provider Implementation."""

from qwenpaw.providers.openai_provider import OpenAIProvider
from qwenpaw.providers.provider import ModelInfo
from typing import List


class MyLLMProvider(OpenAIProvider):
    """My custom LLM provider (OpenAI-compatible)."""

    def __init__(self, **kwargs):
        """Initialize provider."""
        super().__init__(**kwargs)

    @classmethod
    def get_default_models(cls) -> List[ModelInfo]:
        """获取默认模型列表。"""
        return [
            ModelInfo(
                id="my-model-v1",
                name="My Model V1",
                supports_multimodal=False,
                supports_image=False,
                supports_video=False,
            ),
            ModelInfo(
                id="my-model-v2",
                name="My Model V2",
                supports_multimodal=True,
                supports_image=True,
                supports_video=False,
            ),
        ]
```

#### 4. 创建 plugin.py

```python
# -*- coding: utf-8 -*-
"""My LLM Provider Plugin Entry Point."""

import importlib.util
import logging
import os

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class MyLLMProviderPlugin:
    """My LLM Provider Plugin."""

    def register(self, api: PluginApi):
        """Register the provider.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering My LLM Provider...")

        # 从同一目录加载 provider 模块
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        provider_path = os.path.join(plugin_dir, "provider.py")

        spec = importlib.util.spec_from_file_location(
            "my_provider", provider_path
        )
        provider_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(provider_module)

        MyLLMProvider = provider_module.MyLLMProvider

        # Register provider
        api.register_provider(
            provider_id="my-llm",
            provider_class=MyLLMProvider,
            label="My LLM",
            base_url="https://api.example.com/v1",
            metadata={},
        )

        logger.info("✓ My LLM Provider registered")


# Export plugin instance
plugin = MyLLMProviderPlugin()
```

#### 5. 安装和使用

```bash
# 安装插件
qwenpaw plugin install my-llm-provider

# 启动 QwenPaw
qwenpaw app

# 在 Web UI 中配置 API Key
# 然后就可以使用新的 Provider 了
```

### 示例 2：添加启动钩子

假设你想在 QwenPaw 启动时初始化一个监控服务。

#### 1. 创建插件

```bash
mkdir monitoring-hook
cd monitoring-hook
```

#### 2. 创建 plugin.json

```json
{
  "id": "monitoring-hook",
  "name": "Monitoring Hook",
  "version": "1.0.0",
  "type": "hook",
  "description": "Initialize monitoring service at startup",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "0.1.0"
}
```

#### 3. 创建 plugin.py

```python
# -*- coding: utf-8 -*-
"""Monitoring Hook Plugin Entry Point."""

from qwenpaw.plugins.api import PluginApi
import logging

logger = logging.getLogger(__name__)


class MonitoringHookPlugin:
    """Monitoring Hook Plugin."""

    def register(self, api: PluginApi):
        """Register the monitoring hook.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering monitoring hook...")

        def startup_hook():
            """Startup hook to initialize monitoring."""
            try:
                logger.info("=== Monitoring Service Initialization ===")

                # 初始化你的监控服务
                # from my_monitoring import init_monitoring
                # init_monitoring(app_name="QwenPaw")

                logger.info("✓ Monitoring initialized successfully")

            except Exception as e:
                logger.error(
                    f"Failed to initialize monitoring: {e}",
                    exc_info=True,
                )

        # 注册启动钩子（priority=0 表示最高优先级）
        api.register_startup_hook(
            hook_name="monitoring_init",
            callback=startup_hook,
            priority=0,
        )

        logger.info("✓ Monitoring hook registered")


# Export plugin instance
plugin = MonitoringHookPlugin()
```

#### 4. 安装

```bash
qwenpaw plugin install monitoring-hook
qwenpaw app
```

### 示例 3：添加自定义命令

假设你想添加一个 `/status` 命令来查看系统状态。

#### 1. 创建插件

```bash
mkdir status-command
cd status-command
```

#### 2. 创建 plugin.json

```json
{
  "id": "status-command",
  "name": "Status Command",
  "version": "1.0.0",
  "type": "command",
  "description": "Custom status command",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "0.1.0"
}
```

#### 3. 创建 query_rewriter.py

```python
# -*- coding: utf-8 -*-
"""Query rewriter for status command."""


class StatusQueryRewriter:
    """Rewrite /status queries to agent prompts."""

    @staticmethod
    def should_rewrite(query: str) -> bool:
        """Check if query should be rewritten."""
        if not query:
            return False
        return query.strip().lower().startswith("/status")

    @staticmethod
    def rewrite(query: str) -> str:
        """Rewrite /status query to agent prompt."""
        return """请帮我检查系统状态，包括：

1. 当前使用的模型和 Provider
2. 内存使用情况
3. 最近的对话数量
4. 插件加载情况

请用清晰的格式展示这些信息。"""
```

#### 4. 创建 plugin.py

```python
# -*- coding: utf-8 -*-
"""Status Command Plugin Entry Point."""

import logging

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class StatusCommandPlugin:
    """Status Command Plugin."""

    def register(self, api: PluginApi):
        """Register the status command.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering status command...")

        # Register startup hook to patch query handler
        api.register_startup_hook(
            hook_name="status_query_rewriter",
            callback=self._patch_query_handler,
            priority=50,
        )

        logger.info("✓ Status command registered: /status")

    def _patch_query_handler(self):
        """Patch AgentRunner.query_handler to rewrite /status queries."""
        from qwenpaw.app.runner.runner import AgentRunner
        from .query_rewriter import StatusQueryRewriter

        original_query_handler = AgentRunner.query_handler

        async def patched_query_handler(self, msgs, request=None, **kwargs):
            """Patched query handler."""
            if msgs and len(msgs) > 0:
                last_msg = msgs[-1]
                if hasattr(last_msg, 'content'):
                    content_list = (
                        last_msg.content
                        if isinstance(last_msg.content, list)
                        else [last_msg.content]
                    )
                    for content_item in content_list:
                        if (
                            isinstance(content_item, dict)
                            and content_item.get('type') == 'text'
                        ):
                            text = content_item.get('text', '')
                            if StatusQueryRewriter.should_rewrite(text):
                                rewritten = StatusQueryRewriter.rewrite(text)
                                logger.info("Rewriting /status query")
                                content_item['text'] = rewritten
                                break

            async for result in original_query_handler(
                self,
                msgs,
                request,
                **kwargs,
            ):
                yield result

        AgentRunner.query_handler = patched_query_handler
        logger.info("✓ Patched AgentRunner.query_handler for /status")


# Export plugin instance
plugin = StatusCommandPlugin()
```

#### 5. 安装和使用

```bash
qwenpaw plugin install status-command
qwenpaw app

# 使用命令
/status
```

### 示例 4：添加自定义前端页面

向侧边栏添加一个欢迎页面。构建工具链文件（`package.json`、`tsconfig.json`、`vite.config.ts`）参考上方「前端插件 > 构建工具链」。

**plugin.json**：

```json
{
  "id": "welcome-plugin",
  "name": "Welcome Plugin",
  "version": "1.0.0",
  "type": "frontend",
  "description": "Welcome page plugin",
  "author": "Your Name",
  "entry": { "frontend": "dist/index.js" }
}
```

**src/index.tsx**：

```tsx
const { React, antd } = window.QwenPaw.host;
const { Typography, Card } = antd;
const pluginId = "welcome-plugin";

const WelcomePage = () => {
  const theme = window.QwenPaw.host.useTheme();
  return (
    <Card
      style={{
        maxWidth: 480,
        margin: "40px auto",
        background: theme === "dark" ? "#1f1f1f" : "#fff",
      }}
    >
      <Typography.Title level={2}>Welcome to QwenPaw</Typography.Title>
      <Typography.Paragraph>插件系统运行正常！</Typography.Paragraph>
    </Card>
  );
};

window.QwenPaw.menu.add(pluginId, {
  id: "welcome-plugin.home",
  label: "Welcome",
  icon: "spark-home-line",
  route: "welcome-plugin.home",
});

window.QwenPaw.route.add(pluginId, {
  id: "welcome-plugin.home",
  path: "/welcome-plugin/home",
  component: WelcomePage,
});
```

```bash
npm install && npm run build
cp -r . ~/.qwenpaw/plugins/welcome-plugin/
qwenpaw app
```

### 示例 5：自定义工具调用渲染

自定义 Agent 工具调用结果的展示方式。项目结构同示例 4，仅 `src/index.tsx` 不同。

**src/index.tsx**：

```tsx
const { React, antd } = window.QwenPaw.host;
const { Card, Descriptions } = antd;
const pluginId = "tool-render-plugin";

window.QwenPaw.chat.toolRender(pluginId, "get_weather", ({ result }) => {
  const data = typeof result === "string" ? JSON.parse(result) : result;
  return (
    <Card title="天气信息" size="small" style={{ marginTop: 8, maxWidth: 400 }}>
      <Descriptions column={1} size="small">
        <Descriptions.Item label="城市">{data.city}</Descriptions.Item>
        <Descriptions.Item label="温度">{data.temperature}°C</Descriptions.Item>
        <Descriptions.Item label="天气">{data.weather}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
});
```

### 示例 6：自定义聊天欢迎界面

定制对话页面的欢迎语、描述和推荐提示词。项目结构同示例 4，仅 `src/index.tsx` 不同。

**src/index.tsx**：

```tsx
const pluginId = "custom-greeting-plugin";

window.QwenPaw.chat.welcome.set(pluginId, {
  greeting: (locale) =>
    locale.startsWith("zh")
      ? "你好！我是定制版 QwenPaw"
      : "Hello! I'm customized QwenPaw",
  description: "这是一个定制化的聊天助手",
  prompts: [
    { label: "分析代码", value: "帮我分析这段代码" },
    { label: "单元测试", value: "写一个单元测试" },
    { label: "优化逻辑", value: "优化这段逻辑" },
  ],
});
```

### 示例 7：暴露 FastAPI 接口

后端插件可以通过注册 `fastapi.APIRouter` 暴露自己的 HTTP 接口。路由会挂载在
`/api` 加上你指定的前缀下，与 QwenPaw 核心 API 使用同一个 FastAPI 应用，因此
共享 CORS、鉴权等设置，并会出现在 `/openapi.json` 与 `/docs` 中。

下面示例增加一个简单的 `/api/pets` 接口：列出宠物，并支持新增。

#### 1. 创建插件目录

```bash
mkdir pet-api-plugin && cd pet-api-plugin
```

#### 2. 创建 plugin.json

```json
{
  "id": "pet-api-plugin",
  "name": "Pet API Plugin",
  "version": "1.0.0",
  "type": "general",
  "description": "Expose a small REST API under /api/pets",
  "author": "Your Name",
  "entry": {
    "backend": "plugin.py"
  },
  "dependencies": [],
  "min_version": "1.1.5"
}
```

#### 3. 创建 plugin.py

```python
# -*- coding: utf-8 -*-
"""Pet API Plugin Entry Point."""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class Pet(BaseModel):
    """Pet model."""

    id: int
    name: str
    species: str


class PetCreate(BaseModel):
    """Pet creation payload."""

    name: str
    species: str


_PETS: List[Pet] = [
    Pet(id=1, name="Mochi", species="cat"),
    Pet(id=2, name="Bao", species="dog"),
]


def build_router() -> APIRouter:
    """Build the plugin's APIRouter.

    Routes are mounted under ``/api`` + the prefix passed to
    ``register_http_router``. With ``prefix="/pets"`` the handlers
    below are served at ``/api/pets`` and ``/api/pets/{pet_id}``.
    """
    router = APIRouter()

    @router.get("", response_model=List[Pet])
    def list_pets() -> List[Pet]:
        """Return all pets."""
        return list(_PETS)

    @router.get("/{pet_id}", response_model=Pet)
    def get_pet(pet_id: int) -> Pet:
        """Return a single pet by id."""
        for pet in _PETS:
            if pet.id == pet_id:
                return pet
        raise HTTPException(status_code=404, detail="Pet not found")

    @router.post("", response_model=Pet, status_code=201)
    def create_pet(payload: PetCreate) -> Pet:
        """Create a new pet."""
        new_id = (max((p.id for p in _PETS), default=0)) + 1
        pet = Pet(id=new_id, name=payload.name, species=payload.species)
        _PETS.append(pet)
        return pet

    return router


class PetApiPlugin:
    """Pet API Plugin."""

    def register(self, api: PluginApi):
        """Register the HTTP router.

        Args:
            api: PluginApi instance
        """
        logger.info("Registering Pet API plugin...")

        api.register_http_router(
            build_router(),
            prefix="/pets",
            tags=["pets"],
        )

        logger.info("✓ Pet API registered at /api/pets")


# Export plugin instance
plugin = PetApiPlugin()
```

#### 4. 安装并试用

```bash
qwenpaw plugin install pet-api-plugin
```

启动 QwenPaw 后，可在终端用 `curl` 测试（端口请按你本地实际为准，例如 `8088`）：

```bash
# 列出全部宠物
curl http://127.0.0.1:8088/api/pets

# 按 id 查询
curl http://127.0.0.1:8088/api/pets/1

# 新增宠物（POST 到集合路径 /api/pets）
curl -X POST http://127.0.0.1:8088/api/pets \
  -H "Content-Type: application/json" \
  -d '{"name": "Luna", "species": "rabbit"}'
```

**说明：**

- `prefix` 必须以 `/` 开头，且不能仅为 `/`，应使用有语义的片段（如 `/pets`）。完整路径恒为 `/api` + 你的 `prefix`。
- 每个前缀只能被一个插件占用；重复注册相同前缀会抛出 `ValueError`。
- `tags` 可选；省略时路由在 OpenAPI 中会默认打上 `plugin:<插件 id>` 标签。
- 插件卸载或禁用时会自动卸载对应路由。

## 依赖管理

### 使用 requirements.txt

如果插件需要额外的 Python 包，创建 `requirements.txt`：

```
httpx>=0.24.0
pydantic>=2.0.0
```

插件安装时会自动安装依赖。

### 使用自定义 PyPI 源

```
--index-url https://custom-pypi.example.com/simple
my-package>=1.0.0
```

## 最佳实践

### 1. 命名规范

- **插件 ID**：使用小写字母和连字符，如 `my-plugin`
- **版本号**：遵循语义化版本（1.0.0, 1.1.0, 2.0.0）

### 2. 错误处理

钩子回调应该优雅处理错误，避免阻塞应用启动：

```python
def startup_hook():
    try:
        # 你的初始化代码
        pass
    except Exception as e:
        logger.error(f"Initialization failed: {e}", exc_info=True)
        # 不要 raise，让应用继续启动
```

### 3. 日志记录

使用 Python logging 记录插件行为：

```python
import logging

logger = logging.getLogger(__name__)

logger.info("Plugin loaded")
logger.debug("Debug information")
logger.error("Error occurred", exc_info=True)
```

### 4. 文档

提供清晰的 README.md 文档，包括：

- 功能说明
- 安装步骤
- 使用示例
- 配置说明
- 故障排查

## 优先级系统

### Hook 优先级

钩子按优先级顺序执行：

- **优先级值越低，执行越早**
- Priority 0 = 最高优先级（最先执行）
- Priority 100 = 默认优先级
- Priority 200 = 低优先级（最后执行）

**示例**：

```python
# 最先执行
api.register_startup_hook("early", callback, priority=0)

# 默认顺序
api.register_startup_hook("normal", callback, priority=100)

# 最后执行
api.register_startup_hook("late", callback, priority=200)
```

## 故障排查

### 插件未加载

1. 检查插件是否已安装：

   ```bash
   qwenpaw plugin list
   ```

2. 查看 QwenPaw 日志：

   ```bash
   tail -f ~/.qwenpaw/logs/qwenpaw.log | grep -i plugin
   ```

3. 验证插件清单格式：
   ```bash
   qwenpaw plugin info <plugin-id>
   ```

### 依赖安装失败

1. 检查 `requirements.txt` 格式
2. 手动安装依赖测试：
   ```bash
   pip install -r /path/to/plugin/requirements.txt
   ```
3. 使用 `--force` 重新安装插件

### Provider 未显示

1. 确认插件已安装并重启 QwenPaw
2. 检查 Web UI 的模型管理页面
3. 查看日志中的 provider 注册信息

### 命令未响应

1. 确认插件已安装
2. 检查 startup hook 是否成功执行
3. 查看日志中的 patch 信息

## 安全注意事项

1. **只安装可信插件**：插件代码会在 QwenPaw 进程中执行
2. **检查依赖**：确保插件依赖来自可信源
3. **审查代码**：安装前审查插件源代码
4. **离线操作**：插件安装/卸载需要 QwenPaw 离线

## PluginApi 参考

### register_provider

注册自定义 LLM Provider。

```python
api.register_provider(
    provider_id: str,          # Provider 唯一标识符
    provider_class: Type,      # Provider 类
    label: str,                # 显示名称
    base_url: str,             # API base URL
    metadata: Dict[str, Any],  # 额外元数据
)
```

### register_startup_hook

注册启动钩子。

```python
api.register_startup_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

### register_shutdown_hook

注册关闭钩子。

```python
api.register_shutdown_hook(
    hook_name: str,      # 钩子名称
    callback: Callable,  # 回调函数
    priority: int = 100, # 优先级（越低越早执行）
)
```

### register_http_router

将 `fastapi.APIRouter` 挂载到 `/api` + _prefix_ 下。

```python
api.register_http_router(
    router: APIRouter,             # fastapi.APIRouter 实例
    *,
    prefix: str,                   # /api 下的路径，例如 "/pets"
    tags: Optional[List[str]] = None,  # OpenAPI 标签（可选）
)
```

完整步骤见上文「示例 7：暴露 FastAPI 接口」。

## 高级功能

### Monkey Patch

对于需要修改 QwenPaw 行为的插件（如自定义命令），可以使用 monkey patch：

```python
def _patch_query_handler(self):
    """Patch AgentRunner to intercept queries."""
    from qwenpaw.app.runner.runner import AgentRunner

    original_handler = AgentRunner.query_handler

    async def patched_handler(self, msgs, request=None, **kwargs):
        # 你的自定义逻辑
        # 修改 msgs 或添加额外处理

        # 调用原始 handler
        async for result in original_handler(self, msgs, request, **kwargs):
            yield result

    AgentRunner.query_handler = patched_handler
```

### 访问运行时信息

通过 `api.runtime` 访问运行时信息：

```python
def my_hook():
    # 访问 provider manager
    provider_manager = api.runtime.provider_manager

    # 获取所有 providers
    providers = provider_manager.list_provider_info()
```

## 插件打包

将插件打包为 ZIP 文件以便分发：

```bash
cd /path/to/plugins
zip -r my-plugin-1.0.0.zip my-plugin/
```

用户可以通过 URL 安装：

```bash
qwenpaw plugin install https://example.com/my-plugin-1.0.0.zip
```

## 常见问题

### Q: 插件可以访问哪些 QwenPaw API？

A: 插件通过 `PluginApi` 访问核心功能，包括：

- Provider 注册
- Hook 注册
- HTTP 路由注册（`register_http_router`）
- Runtime helpers（provider_manager 等）

### Q: 插件可以修改 QwenPaw 的核心行为吗？

A: 可以，通过 monkey patch 或 hook 机制。但请谨慎使用，确保不会破坏核心功能。

### Q: 插件之间会冲突吗？

A: 如果多个插件注册相同的 provider_id 或 command_name，后注册的会覆盖先注册的。建议使用唯一的 ID。

## 示例插件

### GPT Image 2 工具插件

一个为 QwenPaw agents 添加 OpenAI GPT Image 2 图片生成能力的工具插件。

**系统要求：**

- QwenPaw 最低版本：`1.1.5`

**安装方法：**

```bash
# 克隆 QwenPaw 仓库（如果尚未克隆）
git clone https://github.com/agentscope-ai/QwenPaw.git
cd QwenPaw

# 安装插件
qwenpaw plugin install plugins/tool/gpt-image2
```

**配置步骤：**

1. 安装完成后，重启 QwenPaw
2. 进入 Agent 设置 → 工具管理
3. 找到 "generate_image_gpt" 工具
4. 点击"配置"按钮，输入你的 OpenAI API Key
5. 启用该工具

**使用方法：**

配置完成后，agent 可以通过调用工具来生成图片：

```
用户: 请生成一张可爱的小猫在花园里玩耍的图片
Agent: [调用 generate_image_gpt 工具]
       [返回生成的图片]
```

**功能特性：**

- 支持多种图片尺寸：1024x1024, 1024x1792, 1792x1024
- 质量选项：low, medium, high, auto
- 自动验证 API Key
- Per-agent 配置（每个 agent 可以使用不同的 API Key）

更多详情请参考 `plugins/tool/gpt-image2/README.md`。
