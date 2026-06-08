# QwenPaw 插件前端自定义方案 — Menu / Route / Layout Slot

> v0.4 · CoPaw `main` HEAD(react-router-dom 7 + antd 5)· 仅前端

---

## 1. TL;DR

引入 **Menu / Route / Slot** 3 个核心概念,沿用现有 `registerRoutes` 命令式风格,**不**引入 `contributes` manifest / `when` DSL / `activationEvents`。配套 **Host SDK hooks**(`useTheme/useLocale/useSelectedAgent/useCurrentSession`)消灭插件靠 MutationObserver / `Storage.prototype` 猴补的黑魔法。基础前置是把内置 menu/route 从 JSX 字面量抽成 `builtinMenu.ts` / `builtinRoutes.ts` 数据,与插件走同一份 merge pipeline。**4 阶段落地**(A 数据化 → B Menu/Route/基础 Slot → C Chat 细粒度 + Host SDK → D Lifecycle/CSS),3 个真实插件(qwenpaw-pet / cloudpaw / DataPaw)dogfood。

---

## 2. 现状

| 维度 | 现状 | 限制 |
|---|---|---|
| 内置 menu / route / layout | 三处 JSX 字面量(`Sidebar.tsx:215-521`、`MainLayout/index.tsx:137-180`、`Header.tsx`) | 无 id/order/group 元数据;插件 route 永远排内置之后;**route override 不可能** |
| 插件菜单合并 | 强制 append 到 `plugins-group`(`Sidebar.tsx:524-534`),icon 强制 emoji | 不能插入 `agent-group/control-group/settings-group` |
| 组件替换 | 仅 `OptionsPanel/defaultConfig.ts` 的 `configProvider` 类实例(CloudPaw 用) | 只能 patch 类实例方法;不是合约 |
| 卸载 | `window.location.reload()` | 无前端 `unregister` |

根本问题:**内置 layout / menu / route 是 JSX 字面量,不是数据**。要根治必须先抽成数据。

---

## 3. 设计原则

1. **三概念封顶**:Menu + Route + Slot(命名组件如 `chat.welcome.*` 也是 slot,不开新概念)
2. **内置 = 数据**,与插件走同一份 merge + sort pipeline,不存在"内置在前 + 插件在后"两套集合
3. **替换必须显式**(`replace: targetId`),未声明而 id 冲突 → 拒绝注册 + warn
4. **整页 swap 禁止**:`route.replace/wrap` 只针对具体 routeId,不接管 `/*`
5. **提供 Host SDK Hooks**(`useTheme/useLocale/useSelectedAgent/useCurrentSession/fetch`),禁止插件靠 DOM/Storage 反向工程

---

## 4. API 定义

### 4.1 Menu API

```ts
// console/src/plugins/registry/types.ts

export type MenuLocation = "primary.agentScoped" | "primary.settings" | "userMenu";

export interface MenuItem {
  id: string;                                         // 全局唯一,"core.workspace" / "datapaw.workspace"
  location?: MenuLocation;                            // 默认 "primary.settings"
  parentId?: string;                                  // 嵌入分组,"core.agent-group" / "core.settings-group"
  before?: string;                                    // 相对某 id 之前
  after?: string;                                     // 相对某 id 之后
  order?: number;                                     // 兜底排序,小在前
  label: string | (() => string);                    // 支持 i18n 回调
  icon?: React.ComponentType<{ size?: number }> | React.ReactNode;
  route?: string;                                     // 关联 routeId,优先于 path
  badge?: () => React.ReactNode;                     // 角标,如未读数
  visible?: () => boolean;                            // callback,不引入 DSL
  divider?: boolean;
}

export namespace QwenPaw.menu {
  function add(item: MenuItem | MenuItem[]): Disposable;
  function replace(targetId: string, item: MenuItem): Disposable;
  function remove(targetId: string): void;
  function snapshot(location?: MenuLocation): MenuItem[];  // 调试/审计
}
```

### 4.2 Route API

```ts
export interface Route {
  id: string;
  path: string;                                       // "/chat/*" / "/agent/workspace"
  component: React.ComponentType | LazyComponent;
}

export type RouteWrapper = (Original: React.ComponentType) => React.ComponentType;

export namespace QwenPaw.route {
  function add(route: Route | Route[]): Disposable;
  function replace(targetId: string, component: React.ComponentType): Disposable;
  function wrap(targetId: string, wrapper: RouteWrapper): Disposable;
  function remove(targetId: string): void;
}
```

**冲突解决**:多次 `replace` → 最后一个生效(前序自动 dispose);多次 `wrap` → 按注册顺序套娃(后注册者套外层);同 path 不同 routeId → 后注册者拒绝 + warn。

### 4.3 Slot API

```ts
export type SlotName = string;                       // 见 §5.3 命名表
export type SlotKind = "fill" | "replace";

export interface SlotOpts {
  id?: string;                                       // 命名本次 fill,供其他 fill 用 before/after 引用
  order?: number;
  visible?: () => boolean;
  before?: string;                                   // 仅 fill 模式
  after?: string;                                    // 仅 fill 模式
}

export type SlotRenderer = () => React.ReactNode;

export namespace QwenPaw.slot {
  function fill(name: SlotName, render: SlotRenderer, opts?: SlotOpts): Disposable;
  function replace(name: SlotName, render: SlotRenderer, opts?: SlotOpts): Disposable;
  function snapshot(): SlotInfo[];
}
```

### 4.4 Chat 命名 API(slot 语法糖)

```ts
export interface ToolRenderProps { result: unknown; sessionId: string; messageId: string; }
export interface MessageAction { id: string; label: string; icon?: React.ReactNode; onClick: (ctx: MessageContext) => void; }
export interface MessageTransformMatcher { regex?: RegExp; predicate?: (text: string) => boolean; }

export namespace QwenPaw.chat {
  function toolRender(toolName: string, render: React.FC<ToolRenderProps>): Disposable;
  function messageAction(action: MessageAction): Disposable;
  function senderAction(action: SenderAction): Disposable;
  function messageTransform(matcher: MessageTransformMatcher, render: React.FC<{ matched: string }>): Disposable;
}
```

### 4.5 Host SDK(订阅 host 状态,**消灭 DOM/Storage 反向工程**)

```ts
export interface AgentInfo { id: string; name: string; type?: string; }
export interface SessionInfo { id: string; agentId: string; createdAt: number; }

export namespace QwenPaw.host {
  // React Hooks(组件内用)
  function useTheme(): "light" | "dark";
  function useLocale(): string;                      // "zh-CN" / "en-US" / "ja-JP" / "ru-RU"
  function useSelectedAgent(): AgentInfo | null;
  function useCurrentSession(): SessionInfo | null;

  // 命令式订阅(非 React 上下文)
  function onThemeChange(cb: (theme: "light" | "dark") => void): Disposable;
  function onLocaleChange(cb: (locale: string) => void): Disposable;
  function getSelectedAgentId(): string | null;
  function getCurrentSessionId(): string | null;

  // 网络
  function fetch<T = unknown>(path: string, init?: RequestInit): Promise<T>;  // 自动注 auth + X-Agent-Id

  // 共享依赖(已有,保留)
  const React: typeof React;
  const antd: typeof antd;
  const components: SharedComponents;                 // 暴露稳定子集,详见 4.6
}
```

### 4.6 共享组件子集(`QwenPaw.host.components`)

```ts
export interface SharedComponents {
  Card: typeof Card;
  Button: typeof Button;
  Input: typeof Input;
  Select: typeof Select;
  Table: typeof Table;
  Modal: typeof Modal;
  Tabs: typeof Tabs;
  Spin: typeof Spin;
  Tooltip: typeof Tooltip;
  Badge: typeof Badge;
  Empty: typeof Empty;
}
```

插件 bundle 时把 antd 标记为 external,运行时从这里取。

### 4.7 审计 API

```ts
export interface OverrideRecord {
  kind: "menu.replace" | "route.replace" | "route.wrap" | "slot.replace";
  targetId: string;
  pluginId: string;
  timestamp: number;
}

export namespace QwenPaw.audit {
  function overrides(): OverrideRecord[];
}
```

### 4.8 Disposable

```ts
export interface Disposable { dispose(): void }
```

所有 `register*` 返回 `Disposable`,等价对应 `remove/unregister`。鼓励 `Disposable.from(d1, d2, d3).dispose()` 风格批量清理。

---

## 5. 数据结构与位置语义

### 5.1 Menu 位置解析

```
1. 收集所有 MenuItem(内置 + 插件),过滤 visible() === false
2. 按 location 分桶(primary.agentScoped / primary.settings / userMenu)
3. 桶内按 parentId 建树
4. 同层节点:先按 before/after 拓扑,冲突降级 order,同 order 按注册时间稳定
5. replace 后处理:同 id 项被 replacer 替换,写 audit
```

### 5.2 Route 冲突解决

```
对同一 routeId:
  - replace 多次 → 最后一个生效,前序 Disposable 失效
  - wrap 多次 → 按注册顺序套娃(后注册者套外层)
  - 同时存在 replace + wrap → wrap 套在 replace 结果之上
  - 同 path 不同 routeId → 后注册者拒绝 + console.warn
```

### 5.3 Slot 命名表(host 维护,新增走 PR)

```
# Shell-wide(layout 全局)
header.left              # logo 右侧,品牌区
header.right             # 与内置 actions(Language/Theme...)并列,用 SlotOpts.order 控位
header.userMenu          # 头像下拉追加(预留)
sider.brand              # 折叠/展开态品牌槽
sider.top / sider.bottom # 菜单顶/底
rightSider               # 新增区域(无 fill 时隐藏)
content.statusBar        # Content 底状态条(无 fill 时隐藏)
overlay.global           # 全局浮层,替代 document.body fixed div

# Page-scoped(通用 — 借鉴 Hermes)
<pageId>:top             # 页面顶部,如 "chat:top" / "workspace:top"
<pageId>:bottom          # 页面底部,多 fill 按 order 堆叠

# Chat 专有(细粒度 — 对应 CloudPaw 真实需求,见 §9)
chat.welcome.greeting    # 欢迎语
chat.welcome.description # 描述,多语言/多行
chat.welcome.avatar      # 头像
chat.welcome.prompts     # 推荐 prompts(label+value 数组)
chat.header.leftTitle    # 顶部标题
chat.sender.actions      # 输入框左侧 actions
chat.message.actions     # 单条消息下方 actions
chat.sidePanel           # 右侧面板,替代 task-panel 注入
```

**已知现状校准**:
- **Chat 不是 Menu item**,是 Sidebar 顶部 Sticky 按钮(`Sidebar.tsx:580-590`,与 AgentSelector 绑定),无 parentId
- **Sidebar 3 个 section**:Agent-scoped / Global Settings / Auth Actions → `location` 已细分 `primary.agentScoped` / `primary.settings`
- **`header.right` 内部是 4 段**(Resources / GitHub / CodingModeToggle / LangSwitcher+Theme)→ 不细拆 slot,用 `SlotOpts.order` 控位

---

## 6. 实现要点

### 6.1 注册中心(单例)

```ts
// console/src/plugins/registry/store.ts

interface MenuEntry { source: string; item: MenuItem; }
interface RouteEntry { source: string; route: Route; }
interface RouteOverride { source: string; component: React.ComponentType; }
interface RouteWrapEntry { source: string; wrapper: RouteWrapper; registeredAt: number; }
interface SlotEntry { source: string; render: SlotRenderer; opts: SlotOpts; registeredAt: number; }

class PluginRegistry {
  private menus = new Map<string, MenuEntry>();
  private routes = new Map<string, RouteEntry>();
  private overrides = new Map<string, RouteOverride>();          // routeId → 最后一个
  private wraps = new Map<string, RouteWrapEntry[]>();           // routeId → 按注册顺序
  private slots = new Map<SlotName, SlotEntry[]>();              // slotName → 多个(fill)或一个(replace)
  private subs = new Set<() => void>();
  private audit: OverrideRecord[] = [];

  addMenu(source: string, item: MenuItem): Disposable {
    if (this.menus.has(item.id)) {
      console.warn(`[QwenPaw] menu id conflict: ${item.id}`);
      return { dispose: () => {} };
    }
    this.menus.set(item.id, { source, item });
    this.notify();
    return { dispose: () => { this.menus.delete(item.id); this.notify(); } };
  }

  replaceMenu(source: string, targetId: string, item: MenuItem): Disposable {
    const prev = this.menus.get(targetId);
    this.menus.set(targetId, { source, item: { ...item, id: targetId } });
    this.audit.push({ kind: "menu.replace", targetId, pluginId: source, timestamp: Date.now() });
    this.notify();
    return { dispose: () => { if (prev) this.menus.set(targetId, prev); else this.menus.delete(targetId); this.notify(); } };
  }

  // route / slot 类似,关键是 wrap 的洋葱套娃
  wrapRoute(source: string, targetId: string, wrapper: RouteWrapper): Disposable {
    const arr = this.wraps.get(targetId) ?? [];
    const entry = { source, wrapper, registeredAt: Date.now() };
    arr.push(entry);
    this.wraps.set(targetId, arr);
    this.audit.push({ kind: "route.wrap", targetId, pluginId: source, timestamp: entry.registeredAt });
    this.notify();
    return { dispose: () => {
      const a = this.wraps.get(targetId) ?? [];
      this.wraps.set(targetId, a.filter(e => e !== entry));
      this.notify();
    }};
  }

  // 拼装最终 route 组件:replace 替换 base + wrap 套娃
  resolveRoute(routeId: string): React.ComponentType | null {
    const base = this.overrides.get(routeId)?.component ?? this.routes.get(routeId)?.route.component;
    if (!base) return null;
    const wraps = this.wraps.get(routeId) ?? [];
    return wraps.reduce((Comp, w) => w.wrapper(Comp), base);
  }

  // 同步快照(menu 排序、slot 排序在这里做,纯函数,易测)
  snapshotMenus(location: MenuLocation): MenuItem[] {
    const all = [...this.menus.values()]
      .map(e => e.item)
      .filter(i => (i.location ?? "primary.settings") === location)
      .filter(i => i.visible?.() !== false);
    return sortByPosition(all);   // 拓扑 before/after + order 兜底
  }

  subscribe(cb: () => void): Disposable { this.subs.add(cb); return { dispose: () => this.subs.delete(cb) }; }
  private notify() { this.subs.forEach(cb => cb()); }
}

export const store = new PluginRegistry();
```

### 6.2 `<Slot>` 组件

```tsx
// console/src/plugins/registry/Slot.tsx

interface SlotProps {
  name: SlotName;
  kind: SlotKind;
  children?: React.ReactNode;    // fallback,仅 replace 模式无插件时渲染
}

export function Slot({ name, kind, children }: SlotProps) {
  const entries = useSyncExternalStore(
    cb => store.subscribe(cb).dispose,
    () => store.snapshotSlots(name),
  );

  if (kind === "replace") {
    const winner = entries[entries.length - 1];   // 最后注册者胜
    return winner ? <>{winner.render()}</> : <>{children}</>;
  }

  // fill 模式:多个并列渲染,内置 children 视为内置 fill
  const sorted = entries.filter(e => e.opts.visible?.() !== false);
  return (
    <>
      {children}
      {sorted.map((e, i) => <React.Fragment key={e.opts.id ?? i}>{e.render()}</React.Fragment>)}
    </>
  );
}
```

### 6.3 Hooks(组件订阅注册数据)

```ts
// console/src/plugins/registry/hooks.ts

export function useMenuItems(location: MenuLocation): MenuItem[] {
  return useSyncExternalStore(
    cb => store.subscribe(cb).dispose,
    () => store.snapshotMenus(location),
  );
}

export function useRoutes(): { id: string; path: string; component: React.ComponentType }[] {
  return useSyncExternalStore(
    cb => store.subscribe(cb).dispose,
    () => store.snapshotRoutes(),    // 内部已应用 replace + wrap
  );
}
```

### 6.4 兼容 Shim(`registerRoutes` / `registerToolRender` 零改动)

```ts
// console/src/plugins/hostExternals.ts(改造)

window.QwenPaw = {
  host: { React, antd, components: sharedComponents, getApiUrl, getApiToken, fetch: hostFetch, ... },
  menu:  { add: (i) => store.addMenu(currentPlugin(), i), replace: (...args) => store.replaceMenu(currentPlugin(), ...args), ... },
  route: { add: (r) => store.addRoute(currentPlugin(), r), replace: ..., wrap: ..., remove: ... },
  slot:  { fill: ..., replace: ... },
  chat:  {
    toolRender: (name, render) => store.fillSlot(currentPlugin(), `chat.toolRender.${name}`, () => render, {}),
    messageAction: (a) => store.fillSlot(currentPlugin(), "chat.message.actions", () => <ActionBtn {...a} />, { id: a.id }),
    ...
  },
  audit: { overrides: () => store.snapshotAudit() },

  // ── 旧 API 兼容转译(老插件零改动可工作) ──
  registerRoutes: (pluginId, routes) => routes.forEach((r, i) => {
    const id = `legacy:${pluginId}:${i}`;
    store.addMenu(pluginId, {
      id, label: r.label, icon: r.icon as any, order: r.priority ?? 0, route: id,
      location: "primary.settings", parentId: "core.plugins-group",   // 保持现状:落到 plugins-group
    });
    store.addRoute(pluginId, { id, path: r.path, component: r.component });
  }),
  registerToolRender: (pluginId, map) => {
    Object.entries(map).forEach(([toolName, render]) => {
      store.fillSlot(pluginId, `chat.toolRender.${toolName}`, () => render, {});
    });
  },

  // ── modules escape hatch 保留(不删,不在 d.ts) ──
  modules: moduleRegistry.getAllModules(),
};
```

### 6.5 Host SDK Hooks 实现

```ts
// console/src/plugins/hostExternals.ts(host hooks 部分)

import { useTheme as useThemeCtx } from "../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../stores/agentStore";
import { useSessionStore } from "../stores/sessionStore";

QwenPaw.host = {
  ...
  useTheme: () => useThemeCtx().isDark ? "dark" : "light",
  useLocale: () => useTranslation().i18n.language,
  useSelectedAgent: () => useAgentStore(s => s.selectedAgent),
  useCurrentSession: () => useSessionStore(s => s.current),
  getSelectedAgentId: () => useAgentStore.getState().selectedAgent?.id ?? null,
  getCurrentSessionId: () => useSessionStore.getState().current?.id ?? null,
  onThemeChange: (cb) => themeBus.subscribe(cb),
  onLocaleChange: (cb) => i18nBus.subscribe(cb),
  fetch: async (path, init) => {
    const agentId = useAgentStore.getState().selectedAgent?.id;
    const headers = { Authorization: `Bearer ${getApiToken()}`, ...(agentId && { "X-Agent-Id": agentId }), ...init?.headers };
    const res = await fetch(getApiUrl(path), { ...init, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },
};
```

### 6.6 Layout 改造(订阅注册数据)

```tsx
// console/src/layouts/Sidebar.tsx(改造后,关键段)

const agentScoped = useMenuItems("primary.agentScoped");
const settings    = useMenuItems("primary.settings");

return (
  <Sider>
    <div className={styles.agentScopedSection}>
      <AgentSelector />
      <StickyChatButton />                              {/* 不在 Menu 数据里,保持现状 */}
      <Slot name="sider.top" kind="fill" />
      <Menu items={toAntdItems(agentScoped)} ... />
    </div>
    <Menu items={toAntdItems(settings)} ... />
    <Slot name="sider.bottom" kind="fill" />
    {authEnabled && <AuthActions />}
    <CollapseToggle />
  </Sider>
);

// console/src/layouts/MainLayout/index.tsx
const routes = useRoutes();
return (
  <Layout>
    <Header><Slot name="header.left" kind="replace"><DefaultBrand /></Slot> ... </Header>
    <Layout>
      <Sidebar />
      <Content>
        <Slot name="content.statusBar" kind="fill" />
        <Routes>{routes.map(r => <Route key={r.id} path={r.path} element={<r.component />} />)}</Routes>
      </Content>
    </Layout>
  </Layout>
);
```

---

## 7. 落地分阶段

| Phase | 范围 | 体量 | 风险 |
|---|---|---|---|
| **A 数据化** | `builtinMenu.ts`/`builtinRoutes.ts` 抽数据;`Sidebar`/`Header`/`MainLayout` 改为消费 hooks;`registerRoutes`/`registerToolRender` 兼容转译上线 | 大 | 中 — feature flag 灰度 1-2 周 |
| **B Menu + Route + 基础 Slot** | `menu.{add,replace,remove}`、`route.{add,replace,wrap}`、`slot.{fill,replace}`(header.* / sider.* 子集) | 中 | 小 |
| **C Chat 细粒度 + Host SDK** | `chat.welcome.{greeting,description,avatar,prompts}`、`chat.header.leftTitle`、`chat.{messageAction,senderAction,messageTransform}`、`host.use{Theme,Locale,SelectedAgent,CurrentSession}`、`host.fetch` | 中 | 小 |
| **D Lifecycle / 资源** | `Disposable` 全链路、卸载不 reload(`PluginManager` 重写)、`frontend_css` 加载、首屏不阻塞(改 `App.tsx:128`) | 中 | 中 |

Phase A 必做文件:
- `console/src/layouts/menu/builtinMenu.ts` — 26+ 项,从 `Sidebar.tsx:215-521` 抽出
- `console/src/layouts/routes/builtinRoutes.ts` — 26+ 条,从 `MainLayout/index.tsx:137-180` 抽出
- `console/src/plugins/registry/{store,Slot,hooks,types}.ts` — 见 §6 实现
- `console/src/layouts/Slot.tsx` — `<Slot name kind>` 组件

---

## 8. Dogfood

### 8.1 qwenpaw-pet — 菜单插入到内置分组(Phase B)

```ts
QwenPaw.menu.add({
  id: "pet.home",
  location: "primary.agentScoped",
  parentId: "core.control-group",
  before: "core.heartbeat",
  label: "Pets", icon: PetIcon, route: "pet.home",
});
QwenPaw.route.add({ id: "pet.home", path: "/plugin/qwenpaw-pet/pets", component: Pets });

// 替换 watchConsoleLanguage.ts 全局原型链劫持
const lang = QwenPaw.host.useLocale();
const isDark = QwenPaw.host.useTheme() === "dark";
```

### 8.2 cloudpaw — 退役 `modules` 猴补 + DOM 黑魔法(Phase C)

```ts
const lang = QwenPaw.host.useLocale();   // 取代监听 Storage + 500ms 轮询

// 5 处 chat 细粒度 slot
QwenPaw.slot.replace("chat.welcome.greeting",    () => greetings[lang]);
QwenPaw.slot.replace("chat.welcome.description", () => descriptions[lang]);
QwenPaw.slot.replace("chat.welcome.prompts",     () => promptSets[lang]);
QwenPaw.slot.replace("chat.welcome.avatar",      () => CLOUDPAW_LOGO_URL);
QwenPaw.slot.replace("chat.header.leftTitle",    () => "Work with CloudPaw");
QwenPaw.slot.replace("header.left",              () => <CloudPawBrand />);

// 替代 MutationObserver + 500ms XPath 扫 body
QwenPaw.chat.messageTransform(
  { regex: /__A2A_STREAM_START__:(.+?):__END__/ },
  ({ matched }) => <A2AStreamBox sessionId={QwenPaw.host.getCurrentSessionId()!} sse={parseSSE(matched)} />,
);

QwenPaw.chat.toolRender("proposal_choice", ProposalCard);
QwenPaw.chat.toolRender("manage_prd", PrdCard);
QwenPaw.chat.toolRender("a2a_call", A2ACallCard);

QwenPaw.route.add({ id: "cloudpaw.a2a", path: "/a2a", component: A2APage });
QwenPaw.menu.add({ id: "cloudpaw.a2a", parentId: "core.agent-group", label: "A2A", icon: A2AIcon, route: "cloudpaw.a2a" });

// 不再触碰 window.QwenPaw.modules、不再 appendChild(<style>)、不再 MutationObserver
// fetch 自动带 X-Agent-Id
const data = await QwenPaw.host.fetch("/a2a/list");
```

### 8.3 DataPaw — 退役整页 swap(Phase C 关键验收)

```ts
// 1. Chat 套壳,不接管整页
QwenPaw.route.wrap("core.chat", (OriginalChat) => (props) => (
  <DataPawShell><OriginalChat {...props} /></DataPawShell>
));

// 2. 工作区作为独立 route,挂在 agent-group 内
QwenPaw.menu.add({
  id: "datapaw.workspace",
  parentId: "core.agent-group",
  after: "core.workspace",
  label: "数据工作台", icon: DatabaseIcon, route: "datapaw.workspace",
});
QwenPaw.route.add({ id: "datapaw.workspace", path: "/datapaw/workspace", component: DataPawWorkspace });

// 3. task-panel 改右侧栏 slot,不再 document.body 注入
QwenPaw.slot.fill("chat.sidePanel", () => <TaskPanel />, {
  visible: () => isDataPawActive() && taskPanelOpen(),
});
```

---

## 9. 现实压测覆盖率

对仓内 cloudpaw + qwenpaw-pet 共 16 处 UI 改动审计:

| 类别 | 改动数 | v0.3 覆盖 | v0.4 覆盖(加 chat 细粒度 + Host SDK + messageTransform) |
|---|---|---|---|
| 菜单 / 路由 | 3 | ✅ 3 | ✅ 3 |
| Chat tool 卡片 | 1 | ✅ 1 | ✅ 1 |
| Chat 欢迎区细粒度(C3-C7) | 5 | ❌ 0 | ✅ 5 |
| Host 状态订阅(C11/C12/P2-P4) | 5 | ❌ 0 | ✅ 5 |
| Chat 消息后处理(C9) | 1 | ❌ 0 | ✅ 1 |
| 全局 CSS 注入(C8)/ agent.select(C10) | 2 | ❌ 0 | ⚠️ 配套范围(见下) |

**v0.3 = 19% → v0.4 = 88%**。剩余 2 处:
- **C8 全局 CSS** — 长期走原则 9 公开 `qp-*` 稳定类名(需 host CSS 重构);短期允许 `QwenPaw.style.inject` 过渡
- **C10 agent.select + lifecycle.onFirstInstall** — 上层应用 API,涉及 zustand store 改造,属"Drivers/Memory/Audit"工作流;短期保留猴补 + reload 作为已知 tech debt

---

## 10. 参考点

### Hermes Dashboard([extending-the-dashboard](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/extending-the-dashboard.md))
- **`<pageId>:top/:bottom` 通用 page-scoped slot 模式** → §5.3 已吸收
- **Plugin SDK 共享 React + 组件 + hooks**(插件 bundle KB 级) → §3 原则 8、§4.5/4.6 已吸收
- **薄 manifest** `tab.{path, position, override, hidden}` 在 bundle 执行前先渲染菜单骨架 → Q5 待决策
- **重复 `(plugin, slot)` 注册自动替换**(HMR 友好) → §6.1 store 实现遵循
- **`GET /plugins/rescan`** 不重启热重载 → Phase D 吸收
- **Layout Variant**(`standard/cockpit/tiled`) → Q6 标记未来方向
- **`--theme-asset-*` CSS 变量协同** → 原则 9 公开 `qp-*` 同思路,主题工作流落地

### OpenClaw
- **"seam(接缝)"隐喻** → 替代 v0.1 的 "contribution",直接命名 Slot
- **`compat.pluginApi` 显式 API 版本字段** → Phase D 评估 `qwenpaw.compat.api`
- **crabpot 真实插件 fixture 兼容性测试** → Q4 建议 Phase B 起做 `console/test/plugin-compat/`

### VS Code
- **`contributes.menus` 命名 menu location + `when` clause** → 砍掉,只取"命名 slot + visible callback"轻量版

---

## 11. Open Questions

| # | 问题 | 倾向 |
|---|---|---|
| Q1 | Slot 命名表(§5.3)初版范围:全量 vs Phase B/C 必需最小集 | **最小集**,合约宁少勿多 |
| Q2 | Phase A 是否走 feature flag 灰度 | **走**,重构面太广 |
| Q3 | 多次 wrap 同一 route 是否允许 | **允许**,audit 链可控 |
| Q4 | 是否同步建 `console/test/plugin-compat/` fixture(借鉴 crabpot) | **Phase B 起做** |
| Q5 | 是否引入薄 menu manifest 字段(对应 Hermes `tab.*`)避免菜单闪烁 | **引入**,`parentId/wrap` 等仍走 register API |
| Q6 | 是否吸收 Hermes Layout Variant(`standard/cockpit/tiled`) | **Phase D 评估**,标记未来 |
| Q7 | chat slot 是否本期就细化到 greeting/description/avatar/prompts/leftTitle | **是**(Phase C),否则 modules 猴补退役不彻底 |
| Q8 | `chat.messageTransform` vs 推 backend 用 tool block 走现有 `toolRender` | 待评估,短期可双轨 |
