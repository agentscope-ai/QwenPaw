# QwenPaw 插件前端扩展开发指南

## 1. 概述

QwenPaw 插件前端扩展系统为插件开发者提供了一套统一的 API（`window.QwenPaw.*`），用于在不修改宿主代码的情况下扩展 Console 界面。

### 两类扩展点

| 类别 | 作用域 | API 入口 | 说明 |
|------|--------|----------|------|
| **Console 级** | 整个 Console | `menu` / `route` / `slot` | 注册侧边栏菜单、页面路由、通用 UI 插槽 |
| **Chat 级** | 聊天页面 | `chat.*` | 定制欢迎语、消息气泡、操作按钮、输入框等 |

### 核心设计原则

- **pluginId-first**：所有注册方法第一个参数是 `pluginId`，确保审计归因和批量清理。
- **Disposable 模式**：每个注册都返回 `{ dispose() }` 对象，调用 `dispose()` 可撤销注册。
- **三动词模式**：`set`（标量覆盖）/ `render`（整体替换）/ `add`（追加到列表）。
- **LIFO 栈 vs 追加列表**：标量字段（如 `welcome.greeting`）使用后进先出栈，最后注册的生效；列表字段（如 `actions`）共存追加。
- **Localized\<T\>**：支持原始值或 `(locale: string) => T` 函数，自动适配当前语言。

---

## 2. 快速上手

### 最小插件示例

```tsx
// frontend/src/index.tsx — 插件入口文件
const { React } = window.QwenPaw.host;
const pluginId = "my-plugin";

// 1. 注册一个侧边栏菜单项
window.QwenPaw.menu.add(pluginId, {
  id: "my-plugin.dashboard",
  label: "My Dashboard",
  icon: "spark-barChart-line",
  parentId: "settings",         // 挂在 Settings 分组下
  route: "my-plugin.dashboard", // 对应下面的路由 id
});

// 2. 注册对应的路由页面
window.QwenPaw.route.add(pluginId, {
  id: "my-plugin.dashboard",
  path: "/my-dashboard",
  component: () => {
    const theme = window.QwenPaw.host.useTheme();
    return React.createElement("div", {
      style: { padding: 24, color: theme === "dark" ? "#fff" : "#000" },
    }, "Hello from My Plugin!");
  },
});

// 3. 自定义聊天欢迎语
window.QwenPaw.chat.welcome.set(pluginId, {
  greeting: "Welcome to My Plugin!",
  description: "I can help you with data analysis.",
});
```

### 项目结构

```
my-plugin/
├── plugin.json          # 插件元数据（name, version, author）
├── frontend/
│   ├── src/
│   │   └── index.tsx    # 插件入口，执行 window.QwenPaw.* 注册
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│   └── dist/
│       └── index.js     # 构建产物，Host 加载此文件
└── plugin.py            # 后端入口（可为空）
```

### TypeScript 支持

将 `console/src/plugins/types/qwenpaw.d.ts` 复制到插件项目中作为 `qwenpaw-host.d.ts`，获得完整的类型提示。

---

## 3. API 参考

### 3.1 Console 级 API

#### `window.QwenPaw.menu` — 侧边栏菜单

| 方法 | 签名 | 说明 |
|------|------|------|
| `add` | `(pluginId, item \| item[]): Disposable` | 添加菜单项 |
| `replace` | `(pluginId, targetId, item): Disposable` | 替换已有菜单项（LIFO 栈） |
| `remove` | `(targetId): void` | 移除菜单项 |
| `snapshot` | `(location?): MenuItem[]` | 获取当前菜单快照 |

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

**示例：**

```ts
const dispose = window.QwenPaw.menu.add("my-plugin", {
  id: "my-plugin.analysis",
  label: "Data Analysis",
  icon: "spark-barChart-line",
  parentId: "workspace",
  after: "core.tools",
  route: "my-plugin.analysis",
});

// 不再需要时撤销
dispose.dispose();
```

#### `window.QwenPaw.route` — 页面路由

| 方法 | 签名 | 说明 |
|------|------|------|
| `add` | `(pluginId, route \| route[]): Disposable` | 注册新路由 |
| `replace` | `(pluginId, targetId, component): Disposable` | 替换已有路由的组件 |
| `wrap` | `(pluginId, targetId, wrapper): Disposable` | 包装已有路由（洋葱模式） |
| `remove` | `(targetId): void` | 移除路由 |

**Route 参数：**

```ts
{
  id: string;                          // 唯一标识
  path: string;                        // URL 路径，支持 react-router 模式
  component: React.ComponentType<any>; // 页面组件
}
```

**wrap 示例（为已有页面加顶部 banner）：**

```ts
window.QwenPaw.route.wrap("my-plugin", "core.chat", (Inner) => {
  return () => {
    const React = window.QwenPaw.host.React;
    return React.createElement("div", null,
      React.createElement("div", {
        style: { background: "#fff3cd", padding: 8, textAlign: "center" },
      }, "Beta Feature"),
      React.createElement(Inner, null),
    );
  };
});
```

#### `window.QwenPaw.slot` — 通用 UI 插槽

| 方法 | 签名 | 说明 |
|------|------|------|
| `fill` | `(pluginId, name, render, opts?): Disposable` | 向插槽追加内容（可多个共存） |
| `replace` | `(pluginId, name, render, opts?): Disposable` | 替换插槽内容（LIFO 栈，屏蔽所有 fill） |
| `snapshot` | `(): SlotInfo[]` | 获取所有已注册的插槽信息 |

**SlotRenderer 签名：**

```ts
type SlotRenderer = (defaultContent?: React.ReactNode) => React.ReactNode;
```

**内置插槽一览：**

| 插槽名 | 类型 | UI 位置 | 说明 |
|--------|------|---------|------|
| `header.logo` | replace | 顶部导航栏最左侧 | 替换品牌 Logo（默认 QwenPaw Logo） |
| `header.left` | fill | 顶部导航栏左区（Logo 右边） | 追加自定义元素，无默认内容 |
| `header.right` | fill | 顶部导航栏右区（设置按钮左边） | 追加工具栏按钮、指示器等 |
| `sider.top` | fill | 侧边栏顶部（Agent 选择器下方、菜单上方） | 追加导航元素或小组件 |
| `sider.bottom` | fill | 侧边栏底部（菜单下方） | 追加页脚链接、状态指示等 |
| `content.statusBar` | fill | 主内容区顶部（页面内容上方） | 追加状态栏、横幅、通知条 |
| `overlay.global` | fill | 全局覆盖层（Layout 最外层） | 追加全局弹窗、浮动面板、抽屉 |

**示例：**

```ts
// 在侧边栏底部追加一个角标
window.QwenPaw.slot.fill("my-plugin", "sider.bottom", () => {
  return React.createElement("span", {
    style: { fontSize: 10, color: "#999" },
  }, "v1.0.0");
});

// 替换 Header Logo
window.QwenPaw.slot.replace("my-plugin", "header.logo", (defaultLogo) => {
  return React.createElement("img", {
    src: "https://example.com/logo.svg",
    style: { height: 24 },
  });
});
```

---

### 3.2 Chat 级 API

所有 Chat API 通过 `window.QwenPaw.chat.*` 访问，第一个参数均为 `pluginId`。

#### Chat 扩展点总览

**标量扩展点（Scalar，LIFO 栈，最后注册的生效）：**

| 扩展点 | 插件 API | UI 位置 |
|--------|---------|---------|
| `welcome.greeting` | `chat.welcome.set(pid, { greeting })` | 欢迎面板问候语 |
| `welcome.description` | `chat.welcome.set(pid, { description })` | 欢迎面板描述文字 |
| `welcome.avatar` | `chat.welcome.set(pid, { avatar })` | 欢迎面板头像 |
| `welcome.nick` | `chat.welcome.set(pid, { nick })` | 欢迎面板昵称 |
| `welcome.prompts` | `chat.welcome.set(pid, { prompts })` | 欢迎面板推荐问题 |
| `welcome.render` | `chat.welcome.render(pid, fn)` | 整体替换欢迎面板 |
| `header.leftTitle` | `chat.leftHeader.set(pid, { title })` | 聊天头部左侧标题 |
| `header.leftLogo` | `chat.leftHeader.set(pid, { logo })` | 聊天头部左侧 Logo |
| `header.leftHeader.render` | `chat.leftHeader.render(pid, node)` | 整体替换聊天左上角 |
| `theme.colorPrimary` | `chat.theme.set(pid, { colorPrimary })` | 聊天主题色 |
| `sender.placeholder` | `chat.sender.set(pid, { placeholder })` | 输入框 placeholder |
| `sender.disclaimer` | `chat.sender.set(pid, { disclaimer })` | 输入框下方免责声明 |
| `request.render` | `chat.request.render(pid, fn)` | 整体替换用户消息气泡 |
| `response.render` | `chat.response.render(pid, fn)` | 整体替换 AI 回复气泡 |

**列表扩展点（List，多插件共存追加）：**

| 扩展点 | 插件 API | UI 位置 |
|--------|---------|---------|
| `header.rightHeader` | `chat.rightHeader.add(pid, node)` | 聊天头部右侧按钮区 |
| `sender.prefix` | `chat.sender.addPrefix(pid, node)` | 输入框前方区域 |
| `sender.suggestions` | `chat.sender.addSuggestion(pid, item)` | 输入建议下拉列表 |
| `actions` | `chat.actions.add(pid, spec)` | AI 回复消息下方操作按钮 |
| `requestActions` | `chat.requestActions.add(pid, spec)` | 用户消息下方操作按钮 |
| `cards` | `chat.card(pid, name, render)` | 自定义卡片渲染器 |
| `customToolRender` | `chat.toolRender(pid, name, render)` | 工具调用结果自定义渲染 |
| `request.prepend` | `chat.request.prepend(pid, fn)` | 用户消息气泡上方 |
| `request.append` | `chat.request.append(pid, fn)` | 用户消息气泡下方 |
| `response.prepend` | `chat.response.prepend(pid, fn)` | AI 回复气泡上方 |
| `response.append` | `chat.response.append(pid, fn)` | AI 回复气泡下方 |

---

#### `chat.welcome` — 欢迎界面

| 方法 | 签名 | 说明 |
|------|------|------|
| `set` | `(pluginId, partial): Disposable` | 覆盖欢迎界面的特定字段 |
| `render` | `(pluginId, value): Disposable` | 完全替换欢迎界面渲染 |

**set 可设置的字段：**

```ts
{
  greeting?: Localized<ReactNode>;       // 问候语
  description?: Localized<ReactNode>;    // 描述文字
  avatar?: Localized<string | ReactNode>; // 头像
  nick?: Localized<string | ReactNode>;  // 昵称
  prompts?: Localized<Array<{ label?: ReactNode; value: string }>>; // 推荐问题
}
```

**示例：**

```ts
window.QwenPaw.chat.welcome.set("my-plugin", {
  greeting: (locale) => locale.startsWith("zh") ? "你好！" : "Hello!",
  description: "I specialize in data analysis.",
  prompts: [
    { label: "Analyze my data", value: "Please analyze the uploaded dataset" },
    { label: "Create a chart", value: "Create a bar chart from the data" },
  ],
});
```

#### `chat.theme` — 聊天主题

```ts
window.QwenPaw.chat.theme.set(pluginId, {
  colorPrimary?: string;  // 主题色，如 "#1890ff"
});
```

#### `chat.leftHeader` — 聊天左上角标题区

| 方法 | 说明 |
|------|------|
| `set(pluginId, { logo?, title? })` | 覆盖 Logo 或标题 |
| `render(pluginId, node)` | 完全替换整个左上角区域 |

#### `chat.rightHeader` — 聊天右上角按钮区

```ts
chat.rightHeader.add(pluginId, node, opts?)
// node: React.ReactNode — 要添加的按钮/元素
// opts?: { id?: string; order?: number }
```

**示例：**

```ts
window.QwenPaw.chat.rightHeader.add("my-plugin",
  React.createElement("button", {
    onClick: () => alert("Plugin action!"),
    style: { border: "none", background: "none", cursor: "pointer" },
  }, "My Button"),
  { id: "my-plugin.btn", order: 10 },
);
```

#### `chat.sender` — 输入框

| 方法 | 签名 | 说明 |
|------|------|------|
| `set` | `(pluginId, { placeholder?, disclaimer? })` | 覆盖 placeholder 或免责声明 |
| `addPrefix` | `(pluginId, node, opts?)` | 在输入框前方追加元素 |
| `addSuggestion` | `(pluginId, { id?, items })` | 添加输入建议 |

**addSuggestion 示例：**

```ts
window.QwenPaw.chat.sender.addSuggestion("my-plugin", {
  id: "my-plugin.suggestions",
  items: [
    { label: "/analyze", value: "analyze" },
    { label: "/visualize", value: "visualize" },
  ],
});
```

#### `chat.actions` / `chat.requestActions` — 消息操作按钮

```ts
chat.actions.add(pluginId, spec)        // AI 回复消息下的操作按钮
chat.requestActions.add(pluginId, spec) // 用户消息下的操作按钮
```

**ChatActionSpec：**

```ts
{
  id: string;
  icon?: React.ReactElement;
  render?: (ctx: { data: unknown }) => React.ReactElement;  // 自定义渲染（优先于 icon）
  onClick?: (ctx: { data: unknown }) => void;
}
```

**示例：**

```ts
window.QwenPaw.chat.actions.add("my-plugin", {
  id: "my-plugin.star",
  icon: React.createElement("span", null, "⭐"),
  onClick: ({ data }) => console.log("Starred message:", data),
});
```

#### `chat.request` — 用户消息气泡

| 方法 | 签名 | 说明 |
|------|------|------|
| `render` | `(pluginId, fn): Disposable` | 完全替换用户消息渲染 |
| `prepend` | `(pluginId, fn, opts?): Disposable` | 在用户消息前方追加内容 |
| `append` | `(pluginId, fn, opts?): Disposable` | 在用户消息后方追加内容 |

**render 签名：**

```ts
type ChatRequestRenderFn = (ctx: {
  data: Record<string, unknown>;        // 消息数据
  fallback: () => React.ReactElement;   // 默认渲染函数
}) => React.ReactNode;
```

**示例（用虚线框包裹用户消息）：**

```ts
window.QwenPaw.chat.request.render("my-plugin", ({ data, fallback }) => {
  return React.createElement("div", {
    style: { border: "1px dashed #ccc", borderRadius: 8, padding: 4 },
  }, fallback());  // 调用 fallback() 保留默认渲染
});
```

#### `chat.response` — AI 回复气泡

| 方法 | 签名 | 说明 |
|------|------|------|
| `render` | `(pluginId, fn): Disposable` | 完全替换 AI 回复渲染 |
| `prepend` | `(pluginId, fn, opts?): Disposable` | 在 AI 回复前方追加内容 |
| `append` | `(pluginId, fn, opts?): Disposable` | 在 AI 回复后方追加内容 |

**render 签名：**

```ts
type ChatResponseRenderFn = (ctx: {
  data: Record<string, unknown>;
  isLast?: boolean;                    // 是否是最新一条 AI 回复
  fallback: () => React.ReactElement;
}) => React.ReactNode;
```

**示例（在最新 AI 回复下追加信息条）：**

```ts
window.QwenPaw.chat.response.append("my-plugin", ({ data, isLast }) => {
  if (!isLast) return null;
  return React.createElement("div", {
    style: { background: "#e3f2fd", padding: "4px 8px", borderRadius: 4, fontSize: 12 },
  }, "Powered by My Plugin");
});
```

#### `chat.toolRender` — 工具调用渲染

```ts
chat.toolRender(pluginId, toolName, component): Disposable
```

注册特定工具名的自定义渲染组件。组件 props 包含 `result`, `sessionId`, `messageId`。

#### `chat.card` — 自定义卡片

```ts
chat.card(pluginId, cardName, component): Disposable
```

#### `chat.disposeAll` — 批量清理

```ts
chat.disposeAll(pluginId): void
```

移除指定插件的所有 Chat 扩展注册。通常在插件卸载时调用。

---

### 3.3 Host SDK

通过 `window.QwenPaw.host` 访问宿主环境的共享依赖和工具。

#### 共享依赖

```ts
host.React                        // React 库
host.ReactDOM                     // ReactDOM 库
host.antd                         // Ant Design 组件库
host.antdIcons                    // Ant Design 图标库
host.apiBaseUrl                   // API 基础 URL
host.getApiUrl(path: string)      // 拼接完整 API URL：apiBaseUrl + path
host.getApiToken(): string | null // 获取当前认证 Token
```

#### React Hooks（只能在 React 组件内使用）

| Hook | 返回值 | 说明 |
|------|--------|------|
| `host.useTheme()` | `"light" \| "dark"` | 当前主题模式 |
| `host.useLocale()` | `string` | 当前语言（如 `"zh"`, `"en"`） |
| `host.useSelectedAgent()` | `{ id: string }` | 当前选中的 Agent |
| `host.useCurrentSession()` | `{ id: string } \| null` | 当前聊天会话 |

#### 命令式获取（可在任意位置调用）

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `host.getSelectedAgentId()` | `string` | 当前 Agent ID |
| `host.getCurrentSessionId()` | `string \| null` | 当前会话 ID |

#### 认证代理请求

```ts
host.fetch(path: string, init?: RequestInit): Promise<Response>
```

自动注入 `Authorization` 和 `X-Agent-Id` 请求头，无需手动处理认证。

```ts
const resp = await window.QwenPaw.host.fetch("/api/v1/my-endpoint", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "test" }),
});
const data = await resp.json();
```

---

### 3.4 审计 API

```ts
window.QwenPaw.audit.overrides(): OverrideRecord[]
```

返回最近 500 条扩展注册记录（环形缓冲区），包含：

```ts
{
  kind: string;           // 操作类型，如 "menu.add", "chat.scalar.set"
  pluginId: string;       // 来源插件
  field?: string;         // 字段名（Chat 扩展）
  targetId?: string;      // 目标 ID（Console 扩展）
  supersededPluginId?: string; // 被覆盖的插件
  detail?: string;        // 描述信息
  timestamp: number;      // 时间戳
}
```

可在浏览器控制台中快速排查：

```js
console.table(window.QwenPaw.audit.overrides());
```

**AuditKind 完整枚举：**

| 分类 | kind 值 |
|------|---------|
| Menu | `menu.add`, `menu.replace`, `menu.dispose`, `menu.conflict` |
| Route | `route.add`, `route.replace`, `route.wrap`, `route.dispose`, `route.conflict` |
| Slot | `slot.fill`, `slot.replace`, `slot.dispose`, `slot.error` |
| Chat Scalar | `chat.scalar.set`, `chat.scalar.superseded`, `chat.scalar.dispose` |
| Chat List | `chat.list.add`, `chat.list.dispose`, `chat.error` |

---

### 3.5 模块注册表

```ts
window.QwenPaw.modules: Record<string, Record<string, unknown>>
```

宿主启动时注册的可 patch 模块表。插件可读取或替换其中的函数实现。

---

### 3.6 Legacy API（向后兼容）

以下 API 为旧版插件保留，新插件应使用 `menu` / `route` / `chat.toolRender` 代替。

#### `registerRoutes`

```ts
window.QwenPaw.registerRoutes(pluginId: string, routes: PluginRouteDeclaration[]): void
```

内部转换为 `menu.add` + `route.add`，路由挂在侧边栏 "Plugins" 分组下。

**PluginRouteDeclaration：**

```ts
{
  path: string;
  component: React.ComponentType<any>;
  label: string;
  icon?: string;
  priority?: number;
}
```

#### `registerToolRender`

```ts
window.QwenPaw.registerToolRender(
  pluginId: string,
  renderers: Record<string, React.FC<Record<string, unknown>>>,
): void
```

等价于对每个 key 调用 `chat.toolRender(pluginId, toolName, render)`。

---

## 4. 类型定义速查

| 类型 | 定义 | 说明 |
|------|------|------|
| `Disposable` | `{ dispose(): void }` | 撤销注册 |
| `Localized<T>` | `T \| ((locale: string) => T)` | 国际化值 |
| `MenuItem` | 见 3.1 节 | 菜单项配置 |
| `Route` | `{ id, path, component }` | 路由配置 |
| `SlotRenderer` | `(default?) => ReactNode` | 插槽渲染函数 |
| `SlotOpts` | `{ id?, order?, visible?, before?, after? }` | 插槽选项 |
| `ChatActionSpec` | `{ id, icon?, render?, onClick? }` | 消息操作按钮 |
| `WelcomeRenderFn` | `(props) => ReactElement` | 欢迎界面自定义渲染 |
| `ChatRequestRenderFn` | `({ data, fallback }) => ReactNode` | 用户消息自定义渲染 |
| `ChatResponseRenderFn` | `({ data, isLast?, fallback }) => ReactNode` | AI 回复自定义渲染 |
| `ChatRequestSlotFn` | `({ data }) => ReactNode` | 用户消息 prepend/append |
| `ChatResponseSlotFn` | `({ data, isLast? }) => ReactNode` | AI 回复 prepend/append |
| `RouteWrapper` | `(Inner) => ComponentType` | 路由包装器 |

---

## 5. 设计原则与注意事项

### set vs render vs add

| 动词 | 行为 | 冲突策略 | 适用场景 |
|------|------|----------|----------|
| `set` | 按字段浅合并 | 每个字段独立 LIFO 栈 | 修改部分属性（greeting, placeholder） |
| `render` | 整体替换渲染 | LIFO 栈，优先于 set | 完全自定义渲染逻辑 |
| `add` | 追加到列表 | 多项共存 | 添加按钮、建议、prepend/append |

### LIFO 栈行为

标量字段（set/render/replace）使用后进先出栈：
- 插件 A 调用 `set`，再由插件 B 调用 `set` → 显示 B 的值
- 插件 B 调用 `dispose()` → 回退显示 A 的值
- 不同字段独立：A 设置 `greeting`、B 设置 `description` 互不干扰

### fill vs replace 插槽

- `fill`：多个插件可向同一插槽追加内容，按 `order` 排序共存。
- `replace`：最后一个 `replace` 生效，会屏蔽该插槽的所有 `fill` 内容。
- `replace` 被 `dispose` 后，`fill` 内容会恢复显示。

### Localized\<T\> 国际化

```ts
// 方式 1：直接传值（不区分语言）
chat.welcome.set(pid, { greeting: "Hello!" });

// 方式 2：传函数（按语言返回不同值）
chat.welcome.set(pid, {
  greeting: (locale) => locale.startsWith("zh") ? "你好！" : "Hello!",
});
```

### 清理时机

- 单个扩展：调用返回的 `dispose.dispose()`
- 插件卸载时：调用 `window.QwenPaw.chat.disposeAll(pluginId)` 清理所有 Chat 注册
- Console 级（menu/route/slot）需逐个 dispose 或通过 `remove(targetId)` 清理

### 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `e.item.render is not a function` | render/prepend/append 传了非 React 组件 | 确保传入的是 React 组件或返回 ReactNode 的函数 |
| `duplicate id` | 两次 `add` 使用了相同的 id | 使用全局唯一的 id（推荐 `pluginId.xxx` 格式） |
| Hook 在组件外调用 | `useTheme()` 等在非 React 上下文使用 | 改用 `getSelectedAgentId()` 等命令式 API |
