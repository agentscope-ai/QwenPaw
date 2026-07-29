# OS Enhancements Review 跟踪记录

- 审查日期：2026-07-28
- 审查分支：`feat/os-enhancements`
- 审查基线：`d3a2df0a..HEAD`
- 参考文档：
  - `docs/superpowers/specs/os-enhancements.md`
  - `docs/superpowers/specs/2026-07-22-os-window-app-presentation-design.md`
  - `docs/superpowers/plans/2026-07-22-os-window-app-presentation.md`
- 当前结论：原 5 项问题均已修复；对最新提交 `de540fe0` 复审后新增
  5 项问题（2 项 P1、2 项 P2、1 项 P3），详见“第二轮复审记录”。

## 状态说明

- `待修复`：问题已经确认，尚未提交修复。
- `待复审`：开发者已完成修复，等待重新检查。
- `已修复`：复审确认实现、回归测试和验收标准均通过。
- `未修复`：复审确认问题仍存在或修复不完整。

## 检查清单

- [x] P1：避免窗口拖拽和缩放期间同步持久化阻塞主线程
- [x] P2：持久化窗口恢复时适配当前视口和显示器
- [x] P2：跨应用导航使用应用默认尺寸和最小尺寸
- [x] P2：Agent 表格高度基于 OS 窗口容器
- [x] P3：完整清理 BootScreen 计时器并稳定回调
- [x] 运行相关单元测试
- [x] 运行 TypeScript 类型检查
- [x] 运行改动文件 ESLint 检查
- [ ] P1：生命周期清理只在确认卸载或删除后执行
- [ ] P1：桌面图标拖动不在 `pointermove` 同步持久化
- [ ] P2：拖拽和缩放处理 `pointercancel` / capture 丢失
- [ ] P2：Modal / Drawer 真正挂载到当前 OS 窗口
- [ ] P3：消除 hook effect 驱动的模块级动态应用状态

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
- 状态：已修复
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
- 修复提交：`5e53353b` 先让 `open()` 集中解析静态 manifest；`de540fe0`
  新增统一应用注册表，使动态 PawApp manifest 也可由窗口 store 解析。
- 复审记录：2026-07-28 第二轮复审通过。`resolveAppDef()` 同时覆盖静态应用与
  动态 PawApp，Dock、Launcher、桌面图标和跨应用导航均只传 route id，由
  `open()` 统一应用默认/最小尺寸。新增测试确认动态应用以 `960x680` 打开。

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

2026-07-28 已完成复审。原问题修复已提交，其中 `5e53353b` 修复窗口持久化、
几何、Agent 布局和 BootScreen，`de540fe0` 补齐动态 PawApp 尺寸解析。

| 问题编号 | 复审状态 | 修复提交 | 验证证据 | 复审日期 |
| --- | --- | --- | --- | --- |
| OSR-001 | 已修复 | `5e53353b`、`de540fe0` | 窗口手势仅结束时提交；持久化继续防抖 | 2026-07-28 |
| OSR-002 | 已修复 | `5e53353b` | 活动/保存 Space 与 prev 均钳制 | 2026-07-28 |
| OSR-003 | 已修复 | `5e53353b`、`de540fe0` | 动态 PawApp 使用 registry 的 960x680 | 2026-07-28 |
| OSR-004 | 已修复 | `5e53353b` | 移除 100vh 并测量容器高度 | 2026-07-28 |
| OSR-005 | 已修复 | `5e53353b` | 三个计时器阶段均有覆盖 | 2026-07-28 |

## 第二轮复审记录（提交 `de540fe0`）

- 审查边界：`5e53353b..de540fe0`
- 结论：OSR-003 已补齐并通过复审；新增 OSR-006 至 OSR-010。

### OSR-006：快照缺失被当成卸载，可能永久删除有效布局

- 严重级别：P1
- 状态：待修复
- 分类：功能性 / 数据安全 / 生命周期设计
- 位置：
  - `console/src/os/useOsLifecycle.ts:30`
  - `console/src/os/useOsLifecycle.ts:41`
  - `console/src/os/osWindowStore.ts:400`
  - `console/src/os/osWindowStore.ts:447`
- 问题：清理逻辑只用注册表数量大于 2 判断“已加载”，随后把当前快照中缺失的
  app 直接作为已卸载项永久删除。插件加载允许部分失败；此时内置 app 已让注册表
  大于 2，但暂时加载失败的 PawApp 窗口、图标位置和深链会被清掉。Agent 清理同样
  没有“本次请求成功”的信号：`agents` 会从持久化存储恢复，只要缓存非空就会被
  当作权威列表，可能在刷新完成前或请求失败时删除其他 Agent 的 Space 布局。
- 影响：一次网络故障、插件启动失败或暂态注册表替换可造成用户持久化布局不可恢复
  丢失；现有测试只覆盖理想快照，并把“缺失即删除”固化为预期。
- 建议：显式传入 plugin registry ready/stable 与 agent refresh succeeded 状态；更优
  的方式是在已确认的 uninstall、route dispose、agent delete 事务成功后按明确 id
  清理，不从瞬时快照反推删除事件。
- 验收标准：
  - 插件加载部分失败或 Agent 列表请求失败时不删除任何持久化布局。
  - 只有确认卸载/删除的实体会被清理。
  - 测试覆盖部分插件失败、缓存 Agent 列表、刷新失败和确认删除四种场景。

### OSR-007：桌面图标拖动仍在 pointermove 同步写 localStorage

- 严重级别：P1
- 状态：待修复
- 分类：同步 IO / 性能
- 位置：
  - `console/src/os/DesktopOS.tsx:334`
  - `console/src/os/DesktopOS.tsx:352`
  - `console/src/os/osIconStore.ts:40`
- 问题：每个图标 `pointermove` 都调用持久化 store 的 `setPosition()`。该 store 使用
  Zustand 默认同步 localStorage adapter，因此每次移动都会同步复制 positions、
  JSON 序列化并执行 `localStorage.setItem`，继续阻塞浏览器事件循环。窗口拖拽已经
  改为 DOM 临时几何 + `pointerup` 单次提交，但图标拖动尚未采用同一策略。
- 建议：把拖动中的位置保存在 DOM/ref 或非持久化 transient state，使用 rAF 合并
  视觉更新，仅在手势结束时提交最终位置；持久化策略仍应封装在 store 内。
- 验收标准：一次图标拖动只在结束时更新持久化状态，并有测试断言移动期间无写盘。

### OSR-008：指针取消或 capture 丢失时手势不会收尾

- 严重级别：P2
- 状态：待修复
- 分类：Windows/macOS 兼容性 / 功能性
- 位置：
  - `console/src/os/WindowFrame.tsx:400`
  - `console/src/os/WindowFrame.tsx:447`
  - `console/src/os/DesktopOS.tsx:319`
- 问题：窗口拖拽、缩放和图标拖动只处理 `pointerup`，没有处理
  `pointercancel` 或 `lostpointercapture`。触摸手势被系统取消、浏览器失焦、切换
  应用、Windows/macOS 系统手势接管时，transient DOM 几何可能保留，而 store 仍是
  旧值；ref 和待提交矩形也不会清空，后续渲染会跳回或污染下一次手势。
- 建议：抽取统一 gesture finalize/cancel 函数，同时绑定 `onPointerCancel` 和
  `onLostPointerCapture`；明确取消时是提交最后位置还是回滚，并测试两种窗口手势和
  图标手势。
- 验收标准：取消、capture 丢失和正常抬起都能清理 rAF/ref，DOM 与 store 最终一致。

### OSR-009：Modal / Drawer 的窗口级 overlay 隔离尚未实际接入

- 严重级别：P2
- 状态：待修复
- 分类：功能性 / 模块化设计
- 位置：
  - `console/src/os/OsAppHost.tsx:62`
  - `console/src/os/osWindowContainer.tsx:21`
  - `console/src/os/OsAppHost.test.tsx:36`
- 问题：`ConfigProvider.getPopupContainer` 能自动约束 Select、Dropdown、Tooltip 等
  popup，但不会替 Modal/Drawer 设置它们各自的 `getContainer`。业务代码中没有
  `useOverlayContainer()` 消费者，现有 56 处 Modal/Drawer 仍挂到
  `document.body`，可以遮住整个桌面而不是所属窗口。新增测试只验证 context 有值，
  没有渲染 Modal/Drawer 验证真实 portal 目标。
- 建议：提供 OS-aware Modal/Drawer wrapper，或在业务页面统一接入
  `getContainer={useOverlayContainer()}`；避免让几十个页面各自理解 OS 宿主细节。
- 验收标准：至少用真实 Modal 和 Drawer 测试 portal、mask、定位、滚动与 z-index，
  并确认经典布局仍使用原行为。

### OSR-010：动态应用注册表由 React effect 维护模块级可变状态

- 严重级别：P3
- 状态：待修复
- 分类：代码优雅性 / 模块化设计
- 位置：
  - `console/src/os/osAppRegistry.ts:35`
  - `console/src/os/osAppRegistry.ts:64`
- 问题：React UI 的 `appById` 和非 React store 的 `resolveAppDef()` 不是同一个原子
  快照；后者依赖 `useEffect` 在渲染后同步模块级 Map。effect 执行前、OS shell 未
  挂载、热重载或测试未手工 reset 时，store 可能读取旧 manifest。这也让 registry
  的生命周期隐式依赖某个组件是否渲染。
- 建议：建立独立的 app registry external store/service，由 route/menu/plugin
  注册事件同步更新，React hook 和窗口 store 都订阅/读取同一快照；不要让 hook
  通过副作用维护跨模块全局状态。
- 验收标准：注册、更新、卸载动态 app 后，同一 tick 内 UI 与 `open()` 解析结果一致，
  且无需挂载 DesktopOS 才能工作。

## 第二轮验证结果

- `npx vitest run src/os src/hooks/useIsMobile.test.tsx
  src/pages/Settings/Agents/components/AgentTable.test.tsx`
  - 结果：13 个测试文件、65 个用例通过。
- `npx tsc --noEmit -p tsconfig.app.json`：通过。
- 对 `de540fe0` 改动的 TS/TSX 文件运行 ESLint：通过。
- 对 `de540fe0` 全部改动文件运行 Prettier check：通过。
- 测试缺口：未覆盖 registry/agent 暂态失败、pointer cancel/capture 丢失、图标拖动
  写盘次数，以及真实 Modal/Drawer 的 portal 行为。
