# OS Enhancements Review 跟踪记录

- 审查日期：2026-07-28
- 审查分支：`feat/os-enhancements`
- 审查基线：`d3a2df0a..HEAD`
- 参考文档：
  - `docs/superpowers/specs/os-enhancements.md`
  - `docs/superpowers/specs/2026-07-22-os-window-app-presentation-design.md`
  - `docs/superpowers/plans/2026-07-22-os-window-app-presentation.md`
- 当前结论：复审确认 4 项已修复，1 项部分修复后仍未完成（2026-07-28，
  本地未提交）

## 状态说明

- `待修复`：问题已经确认，尚未提交修复。
- `待复审`：开发者已完成修复，等待重新检查。
- `已修复`：复审确认实现、回归测试和验收标准均通过。
- `未修复`：复审确认问题仍存在或修复不完整。

## 检查清单

- [x] P1：避免窗口拖拽和缩放期间同步持久化阻塞主线程
- [x] P2：持久化窗口恢复时适配当前视口和显示器
- [ ] P2：跨应用导航使用应用默认尺寸和最小尺寸
- [x] P2：Agent 表格高度基于 OS 窗口容器
- [x] P3：完整清理 BootScreen 计时器并稳定回调
- [x] 运行相关单元测试
- [x] 运行 TypeScript 类型检查
- [x] 运行改动文件 ESLint 检查

## Findings

### OSR-001：拖拽与缩放期间同步写入 localStorage

- 严重级别：P1
- 状态：已修复
- 分类：同步 IO / 性能 / 模块化
- 位置：
  - `console/src/os/WindowFrame.tsx:185`
  - `console/src/os/WindowFrame.tsx:255`
  - `console/src/os/osWindowStore.ts:83`
- 问题：`pointermove` 高频调用 `move` 或 `resize`。窗口 store 整体使用
  Zustand `persist`，每次状态更新都会同步序列化窗口和 Space 数据，并调用
  `localStorage.setItem`。浏览器存储属于同步 IO，会阻塞主线程；窗口或 Space
  数量增加时，拖动和缩放可能明显掉帧。
- 建议：拖动期间只更新内存，在 `pointerup` 时持久化最终位置；或者对持久化写入
  做节流。持久化策略应封装在窗口状态模块内，避免 UI 组件感知存储细节。
- 验收标准：
  - 拖拽或缩放的一次连续手势不会在每个 `pointermove` 写入存储。
  - 手势结束后最终窗口几何可以持久化并在刷新后恢复。
  - 新增测试验证连续更新与最终持久化的调用次数或行为。
- 修复提交：本地修改（未提交）。`osWindowStore.ts` 内新增
  `createDebouncedStorage`（250ms 防抖 + `pagehide` 时 flush），经
  `createJSONStorage` 注入 persist，持久化策略完全封装在 store 模块内，
  UI 组件无改动。
- 复审记录：2026-07-28 复审通过。Zustand 仍会在状态更新时生成待持久化
  JSON，但同步 `localStorage.setItem` 已移出 `pointermove` 热路径；连续 30 次
  `move` 在防抖窗口内没有写盘，250ms 后只写入包含最终几何的一份数据。

### OSR-002：持久化窗口可能在显示器变化后留在视口外

- 严重级别：P2
- 状态：已修复
- 分类：Windows/macOS 兼容性 / 功能性
- 位置：`console/src/os/osWindowStore.ts:298`
- 问题：持久化迁移只钳制应用最小宽高，没有限制窗口 `x`、`y`、最大宽度和
  最大高度；而且 `migrate` 只在持久化版本变化时执行。Windows DPI 或缩放比例
  调整、macOS 切换显示器、分屏或浏览器窗口缩小后，旧几何可能把窗口恢复到当前
  视口之外，用户无法再操作窗口。
- 建议：提取纯函数统一规范化完整窗口矩形，并在 hydration 以及 viewport resize
  后按当前工作区重新钳制。需要同时处理活动 Space、已保存 Space 和 `prev` 恢复
  几何。
- 验收标准：
  - 持久化窗口的标题栏始终处于当前可操作视口内。
  - 窗口宽高不超过当前工作区，同时尽可能满足应用最小尺寸。
  - Windows 缩放、macOS 多显示器和小屏幕场景采用同一套平台无关几何逻辑。
  - 新增测试覆盖超大尺寸、负坐标、屏幕外坐标和视口缩小。
- 修复提交：本地修改（未提交）。新增纯函数模块 `windowGeometry.ts`
  （`clampRectToViewport` 统一钳制 x/y/w/h）；`migrate` 升级到 v3 做全量
  规范化；新增 `clampToViewport` action，在 `onRehydrateStorage` 后及
  `DesktopOS` 的 window resize 监听中调用，覆盖活动 Space、已保存 Space
  和 `prev` 恢复几何。
- 复审记录：2026-07-28 复审通过。纯几何函数统一处理负坐标、屏幕外坐标、
  超大尺寸和小视口；hydration 与 `resize` 均会重新钳制活动 Space、保存的
  Space 及 `prev`。实现不依赖路径或平台专属 API，适用于 Windows DPI 变化、
  macOS 显示器切换和浏览器窗口缩放。

### OSR-003：跨应用导航绕过应用尺寸配置

- 严重级别：P2
- 状态：未修复（部分修复）
- 分类：功能性 / 模块化设计
- 位置：
  - `console/src/os/osRouteStore.ts:52`
  - `console/src/os/osRouteStore.ts:68`
  - `console/src/os/osRouteStore.ts:80`
- 问题：跨应用导航直接调用 `open(routeId)`，没有传入 `OsAppDef` 的默认尺寸和
  最小尺寸。例如从其他窗口跳转到系统设置时，会使用全局默认 `820x580`，而不是
  配置的默认 `1200x720`、最小 `960x560`。Agent Config 等配置了最小尺寸的应用
  同样可能受影响。
- 建议：由 `open()` 根据 route id 集中解析应用尺寸，或者建立统一的应用打开服务。
  Dock、Launcher、桌面图标和跨窗口路由不应分别复制尺寸传递逻辑。
- 验收标准：
  - 所有打开入口对同一应用生成一致的初始尺寸和最小尺寸。
  - 跨应用导航到系统设置、Agent Config 等应用时符合 manifest 配置。
  - 新增跨应用打开尺寸测试。
- 修复提交：本地修改（未提交）。`open()` 内通过 `findAppDef` 集中解析静态
  manifest 的默认/最小尺寸，`size` 参数仅作覆盖。
- 复审记录：2026-07-28 复审确认内置应用已修复，但动态 PawApp 尚未覆盖。
  `buildPluginApps()` 为动态应用生成 `960x680` 默认尺寸，而 `findAppDef()` 只
  查找静态 `OS_APPS`、App Store 和 System Settings。动态应用通过
  `osRouteStore.navigateTo()` 跨窗口打开时仍调用 `open(routeId)`，最终回退到
  `820x580`。因此“所有打开入口尺寸一致”的验收标准尚未满足。建议让动态 app
  manifest 注册到窗口管理器可访问的 registry，或让跨应用导航传入已解析的
  `OsAppDef` 尺寸，并增加动态 PawApp 的跨窗口打开测试。

### OSR-004：Agent 表格使用视口高度而非窗口容器高度

- 严重级别：P2
- 状态：已修复
- 分类：功能性 / 响应式布局
- 位置：
  - `console/src/pages/Settings/Agents/index.module.less:2`
  - `console/src/pages/Settings/Agents/components/AgentTable.tsx:290`
- 问题：页面高度和表格纵向滚动区域都使用 `100vh`。在 OS 的 560 至 720px 高窗口
  内，`vh` 仍然指整个浏览器视口，不是窗口内容区，可能造成页面和表格超过窗口、
  出现嵌套滚动，并使固定表头或固定页面头部失效。
- 建议：页面使用 `height: 100%`、`min-height: 0` 的 flex 布局，让表格占据父容器
  剩余空间；如果 antd Table 必须接收数值高度，应从窗口容器测量高度，而不是读取
  浏览器视口。
- 验收标准：
  - 经典布局和 OS 窗口布局均只出现预期的表格滚动区域。
  - OS 窗口在默认高度、最小高度和最大化状态下，页面头部保持可见。
  - 表格固定列和固定表头正常工作。
  - 新增或更新测试，覆盖容器内布局配置。
- 修复提交：本地修改（未提交）。`.agentsPage` 高度改为 `100%`（经典布局
  `.page-content` 与 OS 窗口内容区均为确定高度的 flex 容器）；`AgentTable`
  用 ResizeObserver 测量容器高度并减去表头高度作为 `scroll.y`，不再读取
  `100vh`。
- 复审记录：2026-07-28 复审通过。页面高度改为父容器 `100%`，表格通过
  `ResizeObserver` 读取实际容器高度并扣除表头，不再依赖 `100vh`。经典布局的
  `.page-content` 和 OS Settings pane 都提供确定的父容器高度及滚动边界。

### OSR-005：BootScreen 嵌套计时器未完整清理

- 严重级别：P3
- 状态：已修复
- 分类：功能性 / 代码优雅性
- 位置：
  - `console/src/os/BootScreen.tsx:41`
  - `console/src/os/DesktopOS.tsx:93`
- 问题：BootScreen 在结束计时器中创建第二个 `setTimeout`，但 effect cleanup 只清理
  外层计时器。DesktopOS 的 `handleBootDone` 每次渲染都会创建新函数，也会使依赖
  `onDone` 的 effect 重新执行。组件卸载或父组件重新渲染时，可能遗留回调或重新开始
  动画计时。
- 建议：使用 `useCallback` 稳定 `handleBootDone`，保存并清理 interval、结束 timer
  和 fade timer；也可将动画阶段收敛到单一计时流程。
- 验收标准：
  - 父组件普通重渲染不会重启动画计时。
  - BootScreen 卸载后不会调用 `onDone` 或更新状态。
  - 新增 fake timer 测试覆盖正常结束和提前卸载。
- 修复提交：本地修改（未提交）。BootScreen effect cleanup 现清理 interval、
  结束 timer 和 fade timer 三个计时器；`DesktopOS.handleBootDone` 用
  `useCallback` 稳定，父组件重渲染不再重启动画 effect。
- 复审记录：2026-07-28 复审通过。`handleBootDone` 身份稳定，BootScreen cleanup
  会清理 interval、结束 timer 和 fade timer；fake timer 测试覆盖正常完成、启动
  阶段卸载和 fade 阶段卸载。

## 首次验证记录

- `npx vitest run src/os src/hooks/useIsMobile.test.tsx src/pages/Settings/Agents/components/AgentTable.test.tsx`
  - 结果：7 个测试文件、32 个用例通过。
- `npx tsc --noEmit -p tsconfig.app.json`
  - 结果：通过。
- 对本分支相关改动文件运行 ESLint。
  - 结果：通过。
- 测试缺口：尚未覆盖持久化写入频率、跨应用打开尺寸、视口缩小后的窗口恢复、
  Agent 表格容器高度和 BootScreen 提前卸载。

## 修复记录（2026-07-28）

改动文件：

- `console/src/os/windowGeometry.ts`（新增）+ `windowGeometry.test.ts`
- `console/src/os/osWindowStore.ts` + `osWindowStore.test.ts`
- `console/src/os/BootScreen.tsx` + `BootScreen.test.tsx`（新增）
- `console/src/os/DesktopOS.tsx`
- `console/src/pages/Settings/Agents/index.module.less`
- `console/src/pages/Settings/Agents/components/AgentTable.tsx` + 其测试

修复后验证（全部通过）：

- `npx vitest run src/os src/hooks/useIsMobile.test.tsx
  src/pages/Settings/Agents/components/AgentTable.test.tsx`
  - 结果：9 个测试文件、47 个用例通过（原 32 个 + 新增 15 个）。
  - 新增覆盖：拖拽突发的防抖持久化与最终写入；`clampRectToViewport`
    的负坐标/屏幕外/超大尺寸/视口缩小；`clampToViewport` 对已保存
    Space 与 `prev` 的钳制；`open()` 的 manifest 尺寸回退；BootScreen
    正常结束、启动中卸载、fade 中卸载；AgentTable 不再使用 `100vh`。
- `npx tsc --noEmit -p tsconfig.app.json`：通过。
- 对上述改动文件运行 ESLint 与 Prettier：通过。

## 修复后复审记录

2026-07-28 已完成复审。业务修复仍为本地未提交修改。

| 问题编号 | 复审状态 | 修复提交 | 验证证据 | 复审日期 |
| --- | --- | --- | --- | --- |
| OSR-001 | 已修复 | 本地未提交 | 47/47；连续移动仅防抖后写入最终状态 | 2026-07-28 |
| OSR-002 | 已修复 | 本地未提交 | 47/47；活动/保存 Space 与 prev 均钳制 | 2026-07-28 |
| OSR-003 | 未修复 | 本地未提交 | 内置应用通过；动态 PawApp 仍回退 820x580 | 2026-07-28 |
| OSR-004 | 已修复 | 本地未提交 | 47/47；移除 100vh 并测量容器高度 | 2026-07-28 |
| OSR-005 | 已修复 | 本地未提交 | 47/47；三个计时器阶段均有覆盖 | 2026-07-28 |

## 本次复审新增结论

### 动态 PawApp 的跨应用打开尺寸仍不一致

- 严重级别：P2
- 对应问题：OSR-003
- 位置：
  - `console/src/os/osWindowStore.ts:193`
  - `console/src/os/osWindowStore.ts:198`
  - `console/src/os/osApps.ts:317`
  - `console/src/os/osRouteStore.ts:80`
- 影响：用户从一个 OS 窗口导航到动态插件应用时，新窗口尺寸与从 Dock、Launcher
  或桌面图标打开时不同，可能再次出现内容拥挤。模块层面，动态 app manifest 只在
  React hook 层可见，窗口 store 无法获得同一份配置，尺寸规则仍存在两个来源。
- 需要补充的验证：构造一个动态 PawApp，通过 `navigateTo()` 打开，并断言窗口使用
  `buildPluginApps()` 产生的默认尺寸。
