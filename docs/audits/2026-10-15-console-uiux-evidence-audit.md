# QwenPaw Console UI/UX 证据化巡检与重构设计

- 日期：2026-10-15（Asia/Shanghai）
- 工作目录：`/Users/mazhijian/Documents/Project_2026/P01_LLM/C02_Solutions/QwenPawCodex`
- 运行环境：Console `http://localhost:5176`，API 由 Vite 代理至 `localhost:8004`
- 前端版本：运行页先后显示 `v2.2.2b4`、`v2.2.2b6`；说明巡检期间运行产物发生漂移，视觉与交互结论以最后一次稳定复现为准
- 性质：只读巡检与重构设计；未修改项目源码、未创建/提交/删除业务数据、未执行全量 build/format/test

## 1. 结论摘要

Console 的路由覆盖、异步懒加载、暗色基础 Token 和多数空/错状态已经具备较完整的产品骨架；桌面核心任务可完成，390px 页面普遍没有文档级横向溢出，Cron 创建流程的键盘焦点、校验定位和取消回退表现良好。

本轮形成 12 项正式问题：2 项 P1、9 项 P2、1 项 P3。最优先的是 Tools Agent 切换竞态、多审批卡同坐标遮挡，以及 820px 设置页控件被不可恢复地裁切。另有结构性 IA 问题、浏览器兼容告警和若干待验证假设。证据不足的现象均未升级为缺陷。

| 证据状态 | 数量/范围 | 说明 |
|---|---:|---|
| 已复现 | 7 类 | 820px 设置裁切、Chat/Settings/Models 名称问题、侧栏重复焦点、文件树键盘模型、移动密集触点 |
| 静态确认 | 7 类 | Tools 竞态、审批遮挡、重复轮询、Raw 同步处理、移动全量列表、主题绕 Token、IA 契约问题 |
| 性能数据确认 | 3 组 | 本地 HTTP 时延/体积、页面 DOM/控件数量、静态轮询频率；无 CPU/长任务 Profiler 数据 |
| 不可验证 | 4 类 | 真实触屏手势、屏幕阅读器语音、Hub 管理模式、Performance Resource Timing |
| 待验证假设 | 5 类 | 双 URL 状态保持、Checkpoints 实际错位、Classic/OS 状态一致性等 |

## 2. 方法、边界与证据等级

已完整读取 `design.md`、用户提供的 `AGENTS.md` 指令和《Console UIUX 实用性巡检规范》。采用四条独立证据线：源码契约、真实浏览器交互、浏览器日志与本地 HTTP 探测、相互隔离的子代理静态/桌面复核。

证据等级定义：

- **已复现**：在当前运行环境按明确步骤稳定观察到实际结果。
- **静态确认**：源码已证明契约或执行路径，但本轮没有构造运行数据触发。
- **性能数据确认**：有量化数据；仅声明数据覆盖到的范围。
- **不可验证**：工具、模式、权限或数据明确阻断；不默认判定正常。
- **待验证假设**：有线索但缺少触达性、契约或后果证据；不进入正式缺陷裁决。

禁止边界执行结果：未保存 Cron 草稿，未切换生产配置，未批准/拒绝审批，未创建 Agent/模型/渠道/备份/环境变量，未运行全量 npm 命令。子代理未共享服务进程或测试数据。

## 3. 页面、任务与控件清单（按用户影响排序）

### P0/P1 核心闭环

| 页面 | 核心任务 | 关键控件 | 运行验证 |
|---|---|---|---|
| `/login` | Hub 登录/注册、条款 | 用户名、密码、邀请码、模式切换、语言 | 本地非 Hub 模式不可达；静态确认 |
| `/chat/*` | 新建/继续任务、发送/停止、附件、审批、终端/文件 | Agent、模型、推理、目录、附件、发送、队列、历史 | 桌面/平板/移动、明暗、键盘与名称检查 |
| `/inbox` | Push/审批处理 | Tabs、筛选、分页、批量、批准/拒绝、详情 | 桌面烟测；空状态 |
| `/files` | 工作区浏览、编辑/预览、diff | 文件树、编辑器、预览、图谱、diff 操作 | 桌面/移动；移动密集触点 |
| `/agents` | Agent 创建/编辑/复制/排序 | Gallery、Modal、技能/邮件域 | 桌面烟测；未做写操作 |
| `/models` | Provider、凭据、可见模型、默认模型 | Scope、Cloud/Local、搜索、Provider/Model Modal | 三档视口、明暗；移动横向分段可滚动 |
| `/channels` | 渠道与 ACL | 筛选、渠道卡、配置/ACL Drawer | 桌面/移动烟测；未配置 |
| `/cron-jobs` | 创建/编辑/启停/历史 | 模板、新建、Tabs、列表/日历、表单、历史 | 鼠标、键盘、错误、取消/反向完整验证 |
| `/heartbeat` | 周期、自检内容、目标、活跃时段 | Switch、间隔、文本、Radio、Slider | 页面与配置成功加载；未保存 |
| `/hub/admin` | Runtime/用户/凭据/审计 | 搜索、筛选、启停/重启/删除、Modal | 当前模式重定向到 Chat，不可验证 |

### P1/P2 配置、恢复与集成

| 页面 | 核心任务/控件 | 运行验证 |
|---|---|---|
| `/agent-config` | Runtime workbench、配置分区、自动保存表单 | 桌面烟测 |
| `/skills` | 创建/编辑/删除/启停，Editor | 桌面空态与恢复 CTA |
| `/tools` | 搜索、筛选、批量启停、单项配置 | 桌面 32 类/约 102 控件；未写 |
| `/mcp` | 创建/搜索/启停/配置、Form/JSON | 桌面加载态；静态补齐 |
| `/acp`、`/ACP` | 内建/自定义节点、Drawer、路径、删除 | 桌面烟测；别名静态确认 |
| `/checkpoints` | 快照、图谱、恢复、GC、重置 | 桌面空态；未恢复 |
| `/environments` | 变量/Secret 创建编辑删除 | 桌面烟测；值脱敏，未写 |
| `/security` | 执行规则、文件防护、无认证主机 | 桌面/移动；窄屏 Tabs 有“更多”入口 |
| `/backups` | 创建/导入/恢复/冲突处理 | 桌面烟测；未写 |
| `/imports` | 扫描、选择、导入、重试 | 桌面/移动；未启动导入 |
| `/sessions` | Active/Archived、筛选、归档/恢复/删除 | 桌面/移动；17 字段、移动约 102 控件 |

### P2/P3 扩展、观察与偏好

| 页面 | 核心任务/控件 | 运行验证 |
|---|---|---|
| `/market`、`/apps/:appId` | Apps/Plugins/Skills、安装状态、内嵌 App | Market 桌面烟测；具体 App 无样本 |
| `/skill-pool` | 刷新、批量、删除、广播、内建导入 | 桌面，DOM 约 2086 |
| `/offload-policy` | 工具后台执行策略 | 桌面烟测 |
| `/token-usage` | Trends/Activity、日期、聚合 | 桌面烟测 |
| `/agent-stats` | 日期、刷新、摘要与图表 | 桌面烟测 |
| `/debug` | 日志源、自动刷新、级别、搜索 | 桌面烟测；报告未复制敏感日志 |
| `/voice-transcription` | Provider/模型/行为 | 桌面烟测 |
| `/settings/*` | 21 个设置面板、主题/语言/字号/导航 | 三档视口、明暗、滚轮 |
| `/os...` | Desktop OS 多窗口、Dock、Mission Control | 静态确认；当前 Console 模式未覆盖 |

源码路由依据：`console/src/App.tsx:486-533`、`console/src/layouts/registry/builtinRoutes.tsx:94-382`、`console/src/pages/SettingsCenter/index.tsx:80-292`。

## 4. 运行覆盖矩阵

| 维度 | 已验证 | 未验证/限制 |
|---|---|---|
| 桌面 | 1280×900 与约 1242×1204；全部内建页面烟测 | Hub、Desktop OS 因运行模式不可达 |
| 平板 | 820×1180；Chat、Models、Settings、Files、Cron | 未对每个低频弹窗重复全流程 |
| 移动 | 390×844；Chat、Files、Models、Settings、Cron、Channels、Sessions、Security、Imports | 真触屏设备事件不可用 |
| 主题 | light/dark 在 Chat、Files、Models、Settings、Cron；最终恢复 light | 自定义主题未保存，静态检查 |
| 鼠标 | 导航、Drawer/Modal、取消、滚轮；设置主内容滚动 `0→358px` | 无拖拽排序，避免状态写入 |
| 键盘 | Cron Tab、空表单提交、错误焦点、Esc 与焦点回退；设置按钮聚焦后 PageDown `0→331px` | 文件树、侧栏会话发现正式问题 |
| 触屏 | 390px 几何与触点尺寸、横向滚动容器存在性 | 无真实 touch/pointer 手势注入，明确不可验证 |
| 正常 | 页面加载、主题切换、弹层开关、滚动 | 所有保存型正常流因只读约束跳过 |
| 错误 | Cron 空提交四字段错误；焦点到首错 | 网络故障注入未做，避免干扰共享环境 |
| 反向 | Esc/取消、焦点返回、主题恢复 | 删除/恢复/审批的反向流不操作真实数据 |

### Cron 核心路径证据

1. 鼠标打开“创建任务”：Drawer 具 `role=dialog`、`aria-modal=true`。
2. 空表单提交：显示任务名称、请求内容、用户 ID、会话 ID 四项错误，焦点落到名称。
3. 仅输入未保存名称后再次提交：自动切至“任务类型”，焦点落到请求文本；证明跨 Tab 首错路由有效。
4. Esc 关闭：焦点回到“创建任务”；模板弹窗退出动画结束后也恢复到“从模板创建”。
5. 全程未保存、未生成任务。

## 5. 正式问题

### F1 · P1 · Tools 切换 Agent 时旧请求可覆盖新 Agent 状态

- **状态**：静态确认；并发触达链完整。
- **复现路径**：Tools 页面选择 Agent A，立即切到 B；让 A 的 `listTools` 晚于 B 返回。
- **实际/预期**：完成回调无条件写 `tools/loading`，A 可覆盖 B；预期仅当前 Agent 的最后请求可提交。
- **证据与位置**：`console/src/pages/Agent/Tools/useTools.ts:16-31` 无取消/代次；`console/src/api/modules/tools.ts:30-35` 不接 agentId；`console/src/api/authHeaders.ts:10-20` 发起时从 storage 取 Agent；切换同步持久化见 `console/src/stores/agentStore.ts:88-97,191-201`。现有测试 `useTools.test.ts:231-262` 仅覆盖保存绑定。
- **影响范围**：快速切 Agent、慢网络；可能显示/操作错误 Agent 的工具配置。
- **最小修复**：捕获 agentId，显式传 header；使用 requestId 或 AbortSignal，只提交最新结果，loading 同代次收口。
- **推荐重构**：统一 Agent-scoped query key `['tools', agentId]`，缓存、取消、失效策略集中治理。
- **回归路径**：A/B deferred promise，B 先完成、A 后完成；最终仍为 B，卸载后不写状态。

### F2 · P1 · 多条审批卡固定在同一坐标并相互遮挡

- **状态**：静态确认；后端真实契约支持多 pending。
- **复现路径**：同 scope 产生两条 pending approval，打开 Chat。
- **实际/预期**：所有 sibling 均 `fixed; bottom:80; right:24; z-index:1000`，后项覆盖前项；预期所有待审批可发现并逐项处理。
- **证据与位置**：数组转 Map `console/src/pages/Chat/index.tsx:2121-2178`，遍历全部 `:4655-4657`，统一坐标 `:4720-4731`；后端返回 `_pending.values()` 列表 `src/qwenpaw/app/routers/console.py:720-771`。
- **影响范围**：多审批并发时核心确认受阻；不可见卡仍可能进入键盘焦点序列。
- **最小修复**：单一队列容器，仅显示当前项并提供 N/M 导航，或有界纵向堆叠。
- **推荐重构**：Approval Center 统一承载 Chat 与 Inbox，集中队列、焦点和撤销状态。
- **回归路径**：两条同 scope 审批均可发现、依次处理；Tab 只进入可见卡；关闭上层不误触下层。

### F3 · P2 · 820px 设置页字号控件被卡片裁切且无法横向恢复

- **状态**：已复现（light，820×1180）。
- **复现路径**：打开 `/settings/general`，视口 820×1180，查看字号设置。
- **实际/预期**：`.fontSizeControl` 边界 `left=808,right=1176,width=368`；父行可视右边界 770、`scrollWidth=870`，外层 `.settingsCard{overflow:hidden}`，内容区自身 `scrollWidth=515/clientWidth=530`，控件被裁掉且无横向滚动恢复；预期 769–900px 规则让该行换行并完整可达。
- **证据与位置**：紧凑规则误写在 `SettingsCenter/index.module.less:573-590`，实际元素类来自 `GeneralSettings.module.less:15-28`；CSS Module 作用域不同，规则不会匹配。实际模块只在 `GeneralSettings.module.less:183-191` 对 ≤767px 换行。
- **影响范围**：常见 820px 平板横向/竖向、窄桌面；字号及相邻右侧控件不可操作。
- **最小修复**：将 769–900px 规则移入 `GeneralSettings.module.less`，或由组件显式组合可共享类。
- **推荐重构**：以 container query 驱动统一 `SettingRow`，label/control 两栏在可用宽度不足时换行。
- **回归路径**：768/769/820/900/901px 截图与 DOM 断言；所有表单控件边界在卡片内，键盘可达。

### F4 · P2 · Chat 附件按钮缺少稳定的可访问名称

- **状态**：已复现 + 静态确认。
- **复现路径**：桌面 Chat，检查 composer 图标按钮的 accessibility tree。
- **实际/预期**：附件 `IconButton` 无 `aria-label/title`，Lucide 图标被隐藏，按钮仅通过 tooltip 描述关联；在当前树中按钮没有名称。麦克风/发送依赖实现图标名 `spark-mic-line`/`arrow-up`，不是本地化动作名。预期每个图标按钮有稳定、动作导向、可本地化的名称。
- **证据与位置**：附件触发器 `console/src/pages/Chat/index.tsx:4162-4187` 未传 accessible name；设计规范明确要求 icon-only control 有可访问名称。
- **影响范围**：屏幕阅读器、语音控制和自动化定位；Chat 是最高频路径。
- **最小修复**：为附件、麦克风、发送/停止传入本地化 `aria-label`；tooltip 只作补充。
- **推荐重构**：`IconButton` 开发态强制 `aria-label` 或可见文本，建立 icon-button 契约测试。
- **回归路径**：按角色+名称定位所有 composer 控件；disabled/send/stop 状态名称同步；axe/name audit 无空名称。

### F5 · P2 · `/console/push-messages` 存在两套常驻轮询

- **状态**：静态确认；频率数据由定时常量计算，未抓取网络面板。
- **复现路径**：挂载 MainLayout 并保持前台 60 秒。
- **实际/预期**：ConsolePollService 首次立即、前台每 2.5s/后台 30s；Sidebar 再首次立即并每 6s请求同 endpoint，前台稳态约 34 次/分钟，且 Sidebar 隐藏标签仍 6s；预期同 endpoint 单一 in-flight 链和统一 visibility/backoff。
- **证据与位置**：同时挂载见 `console/src/layouts/MainLayout/index.tsx:58-65`；Service `console/src/components/ConsolePollService/index.tsx:7-9,59-68,127-147`；Sidebar `console/src/layouts/Sidebar.tsx:355-402`。
- **影响范围**：所有登录后的 Console 页面；重复网络、后端负载和状态节奏不一致。
- **最小修复**：Sidebar 消费 Service/共享 store 的审批快照，仅保留独立 inbox 事件请求。
- **推荐重构**：endpoint-keyed polling/query 层，订阅派生 unread/bubble/approval。
- **回归路径**：fake timer 断言单链、hidden 30s cadence、恢复仅一次即时刷新、无并行 in-flight。

### F6 · P2 · 折叠 Raw tool 卡仍同步处理全量大 payload

- **状态**：静态确认；真实性能耗时待 Profiler。
- **复现路径**：打开包含多个大普通文本 tool input/output 的历史会话，卡片保持折叠并切 Raw 模式。
- **实际/预期**：render 阶段先 parse→递归复制→pretty stringify，之后才判断 body 是否挂载；100k guard 发生在全量处理后。预期折叠态不格式化，展开后也有字符/节点预算。
- **证据与位置**：`ToolCardShell.tsx:154-166,221-228`；`rawToolDisplay.ts:35-64,70-101`；普通大文本保留测试 `rawToolDisplay.test.ts:63-68`；晚到的 guard `DefaultBlock.tsx:56-64,136-147`。
- **影响范围**：大工具输出、历史会话和多卡片；主线程长任务与内存放大风险。
- **最小修复**：仅在 `bodyMounted && showRaw` 后格式化；处理前执行总字符/节点预算。
- **推荐重构**：共享 bounded serializer；超限摘要，必要时 Worker/增量查看。
- **回归路径**：折叠多 MB 文本时 formatter 未调用；展开输出有界；记录 1/5/20MB 主线程耗时。

### F7 · P2 · Sessions 移动端全量渲染持续增长的会话集合

- **状态**：静态确认 + 390px 运行几何证据。
- **复现路径**：390px 打开 `/sessions`，数据量增加到 500/2000。
- **实际/预期**：桌面 Table 每页 10 条，移动分支直接 `filteredSessions.map`；当前样本已出现约 102 个交互控件，其中约 95 个小于 44px。预期首屏 DOM 有界、触点符合 44px 基线。
- **证据与位置**：全量获取 `console/src/pages/Control/Sessions/useSessions.ts:18-34`；移动 map `console/src/pages/Control/Sessions/index.tsx:281-357`；桌面分页 `:360-375`。
- **影响范围**：移动端、历史较长用户；渲染/滚动成本和误触概率随数据增长。
- **最小修复**：移动端复用分页或渐进加载，首批 20 条；关键卡片操作触点至少 44px。
- **推荐重构**：后端游标分页 + 虚拟列表，统一桌面/移动数据模型。
- **回归路径**：500/2000 sessions 下首屏节点有界；滚动加载、选择与操作状态保持；触点尺寸断言。

### F8 · P2 · Chat 队列/后台任务面板绕过语义主题 Token

- **状态**：静态确认；自定义主题运行流未保存验证。
- **复现路径**：设置自定义 light/dark surface/accent，打开消息队列和后台任务面板。
- **实际/预期**：面板硬编码 `#fff/#bbb/#555/#888/#999` 及 rgba，无法继承自定义主题；预期业务模块只消费 `--app-*` 语义 Token。
- **证据与位置**：契约 `console/src/styles/tokens.css:1-16,51-76,107-145`，自定义优先级 `console/src/App.tsx:426-450`；违规位于 `MessageQueuePanel.tsx:129-204,260-266,354-370`、`BackgroundTaskPanel.tsx:208-240,315-320,456-590`。
- **影响范围**：队列、后台任务、明暗/自定义主题；对比度和品牌一致性不可控。
- **最小修复**：按角色替换为现有 semantic tokens，仅保留真实状态色。
- **推荐重构**：共享 QueuePanel/StatusRow；色彩、状态、密度统一由组件层治理。
- **回归路径**：自定义 light/dark 计算样式来自 Token；paused/error/running 视觉快照和对比度检查。

### F9 · P2 · 全局侧栏每个会话产生重复焦点停靠点

- **状态**：已复现（独立桌面 IAB，1280×800）+ 静态确认。
- **复现路径**：在 `/cron-jobs` 从首个侧栏按钮连续 Tab；同样检查 Models、Channels、Files。
- **实际/预期**：每个会话依次停在 DnD wrapper“会话名”→内层同名 SessionItem→“更多操作”；30 次 Tab 仅到第 8 个会话，尚未进入主内容。预期一个主行停靠点 + 独立更多操作，拖拽 wrapper 不重复进入语义树。
- **证据与位置**：`console/src/components/SessionGroupDnd/index.tsx:196-216` 将 `useDraggable` attributes/listeners 注入外层 div；`console/src/components/SessionItem/index.tsx:314-337` 内层再设 `role=button/tabIndex=0`，`:400-414` 还有真实 button。运行统计 `/cron-jobs` 可见 focusable=85、nested interactive=46；Models/Channels/Files nested=44。
- **影响范围**：所有带全局侧栏页面；键盘到主内容成本随会话数线性增加，并违反无嵌套交互语义。
- **最小修复**：让 DnD wrapper 不进入 Tab/无障碍树，或把拖拽与行语义合并到同一节点。
- **推荐重构**：统一 `DraggableSessionRow`，明确 row action、drag handle 和 overflow menu 三种语义。
- **回归路径**：每会话仅行与更多操作两个停靠点；Enter/Space 打开、拖拽仍正常；axe 无 nested-interactive；提供 Skip-to-content。

### F10 · P2 · Files 将 tree 声明在容器上，但 72 个节点均为普通 Tab 按钮

- **状态**：已复现 + 静态确认。
- **复现路径**：打开 `/files`，Tab 进入文件树；在 checkpoints 节点按 ArrowDown。
- **实际/预期**：`role=tree` 内 72 个节点全部是默认 tabbable button，均无 `treeitem`；ArrowDown 后焦点不动。预期树为单一 roving Tab stop，↑↓移动，→展开，←折叠/回父级。
- **证据与位置**：容器 `console/src/features/files-workspace/FilesNavigator.tsx:983`；节点 `:193-204,223-235` 使用普通 button，无 roving tabindex、层级或树键盘处理。运行 AX 显示 tree→大量 button。
- **影响范围**：Files 核心工作区的键盘和读屏用户；节点越多，Tab 成本越高。
- **最小修复**：共享 TreeItem，补 `role=treeitem`、`aria-level/expanded/selected` 与 roving focus。
- **推荐重构**：采用符合 WAI-ARIA APG 的通用 FileTree，虚拟化时保持 `aria-setsize/posinset`。
- **回归路径**：72 节点仍只有 1 个树内 Tab stop；方向键、Home/End、Enter、类型搜索按契约工作。

### F11 · P2 · General Settings 语言选择框没有可访问名称

- **状态**：已复现 + 静态确认。
- **复现路径**：打开 `/settings`，查看“语言”行的 accessibility tree/可聚焦元素。
- **实际/预期**：说明文字之后只有无名 `combobox`；唯一未标注可聚焦元素是 `.qwenpaw-select-selection-search-input`。预期名称为“语言”。
- **证据与位置**：`console/src/pages/SettingsCenter/GeneralSettings.tsx:395-400` 的 Select 未设置 `aria-label/aria-labelledby`。
- **影响范围**：设置页读屏与语音控制用户，无法确认该组合框用途。
- **最小修复**：给可见标题稳定 id，并用 `aria-labelledby` 关联 Select；或传本地化 `aria-label`。
- **推荐重构**：`SettingRow` 自动把 label/description/error 绑定到 control。
- **回归路径**：`getByRole('combobox',{name:'语言'})` 唯一命中；各语言 locale 下名称同步。

### F12 · P3 · 模型提供商图标操作缺少提供商上下文

- **状态**：已复现 + 静态确认。
- **复现路径**：打开 `/models`，读取主内容按钮名称。
- **实际/预期**：出现两个精确名称“设置”和两个“禁用”，无法从按钮列表区分 Aliyun/AgentScope。预期“设置 Aliyun”“禁用 AgentScope Platform”等唯一名称。
- **证据与位置**：`console/src/pages/Settings/Models/components/cards/ProviderCloseButton.tsx:23-40` 只用 `models.settings/common.disable`，组件不接 provider name。
- **影响范围**：读屏、语音控制和按名称自动化；存在误操作风险但可通过上下文绕行。
- **最小修复**：传 provider display name 并拼接本地化 aria-label。
- **推荐重构**：所有实体卡片 action 采用 `动作 + 实体名` 命名契约。
- **回归路径**：每个 provider 操作名称唯一，按 role+name 可精确定位；启用/禁用状态名称同步。

## 6. 非阻断观察、排除项与待验证假设

### 浏览器日志债务（改进项）

运行日志稳定出现 React `forwardRef` 参数、`findDOMNode`，以及 Ant Design `popupClassName`、`overlayClassName`、`destroyOnClose`、`bodyStyle`、Spin tip 和未连接 useForm 等告警。源码可定位到 Sidebar、Models、CronJobs、Channels、Sessions、Chat 等多个调用点。当前未证明用户功能损坏，故归为升级/稳定性债务，不冒充正式缺陷。建议以“零业务 warning”为门禁分批迁移弃用 API。

### 运行排除项

- Heartbeat 曾短暂显示“HEARTBEAT.md 指令加载失败”，之后同页稳定加载真实模板和全部控件；未稳定复现，不报缺陷。
- IAB 两次出现 `ERR_CONNECTION_REFUSED`，同一时刻 `/usr/bin/curl`、监听进程均正常且新标签恢复；归为浏览器通道瞬态，不归因应用。
- Files 首次快速切页只见 Loading，延长等待后完整加载；不报加载失败。
- Models 移动分段选项超出可视区，但容器 `overflow-x:auto`，选项仍可横向访问；只建议增加滚动提示/渐隐，不报不可达。
- Security 窄屏 Tabs 有 `rc-tabs` “更多”按钮，隐藏项可达；不报裁切。
- Cron 跨 Tab 错误自动跳转与焦点定位通过；模板 Esc 延迟来自退出动画，最终焦点恢复。

### 待验证假设

1. Checkpoints 的 `parentId='core.agent-group'` 指向不存在的组，而真实组为 `core.workspace-group`；注册器会降级顶层。静态契约异常已确认，但当前用户可见顺序/能力泄漏未复现。位置：`builtinMenu.ts:202-210`、`plugins/registry/store.ts:256-276`。
2. `/models` 与 `/settings/models` 等双入口是否造成表单状态丢失、返回错误或重复请求。
3. Classic Console 与 Desktop OS 设置集合不对称是否为明确产品策略。
4. Sidebar DnD、内嵌 PawApp 在真触屏和屏幕阅读器中的可达性。
5. 多 MB Raw payload 的实际长任务时长；需 Chrome Performance/Profiler 或可重复 benchmark。

## 7. 性能基线

### 已确认数据

本地 HTTP 单次探测（同机、Vite 代理，仅作当前环境基线）：

| Endpoint | HTTP | Time | Bytes |
|---|---:|---:|---:|
| `/` | 200 | 107ms | 37,546 |
| `/api/agents` | 200 | 182ms | 2,484 |
| `/api/chats` | 200 | 17ms | 1,127 |
| `/api/console/push-messages` | 200 | 3ms | 38 |

页面复杂度样本：Chat DOM 约 1230；Tools 约 1746/102 buttons；Sessions 约 1713/78 buttons/17 fields；Skill Pool 约 2086。源码热点：`Chat/index.tsx` 4823 LOC、`Hub/index.tsx` 2118、`ChannelDrawer.tsx` 2029、`sessionApi/index.ts` 1880、`AgentLoopCard.tsx` 1585、`TabbedEditor.tsx` 1486、`MemoryGraphView.tsx` 1389、`ModelSelector/index.tsx` 1381。

### 不可验证与目标基线

IAB 页面沙箱不暴露可用的 Resource Timing，因此没有把资源瀑布、LCP/INP/CLS、长任务或真实重复请求计数写成“已通过”。建议重构门禁：

- LCP ≤2.5s、INP ≤200ms、CLS ≤0.1（75 分位，目标设备/数据集）。
- 主交互同步任务 ≤50ms；1/5/20MB Raw payload 各有固定 benchmark。
- 首屏可交互 DOM 节点有界；Sessions 500/2000 数据不线性挂载全量卡片。
- 同 endpoint 同 scope 同时最多 1 条 in-flight；隐藏页降频 ≥30s。
- 生产 bundle 建立路由 chunk、初始 JS/CSS 预算；本轮因禁止全量 build 未测。

## 8. 目标信息架构

建议按用户任务建立六个稳定域：

1. **Work**：Chat、Inbox、Files、Sessions。
2. **Automations**：Scheduled tasks、Heartbeat、Runs/History。
3. **Agent**：Overview/Runtime、Skills、Tools、Connections（Channels/MCP/ACP）、Checkpoints。
4. **Extensions**：Installed、Discover（Apps/Plugins/Skills）、Import。
5. **Insights**：Agent Stats、Token Usage、Diagnostics。
6. **System Settings**：General、Agents、Models、Environment & Secrets、Security & Offload、Backup、Voice。

治理原则：主导航仅保留高频任务；“All features”与“Pinned shortcuts”分离；每页一个 canonical URL，旧 URL 保留参数并重定向；Classic 与 Desktop OS 共用 IA schema，仅更换壳层；Marketplace 去掉两层重复“Market”概念。

当前断裂的静态证据：Settings Center 将 21 个面板再次挂载到 `/settings/{key}`，而旧路由仍并存；Channels 同时被表达为 Control/settings/Agent configuration，Cron/Heartbeat 同时是 tasks/Agent configuration，Skills/Tools/MCP/ACP 同时是 workspace/settings；完整功能目录被隐藏在 General → Sidebar 编辑中。

## 9. 目标视觉系统与公共组件治理

### 视觉系统

- 只允许语义 Token：surface/text/border/fill/accent/status/focus；业务组件不得新增裸色。
- 保持品牌橙 `#FF7F16`（light）/`#FF9D4D`（dark），状态色只表达状态。
- 密度档以 44px 触点为下限；桌面紧凑视觉可用透明 hit-area 扩展，不牺牲排版。
- 建立 4/8px 间距、12/16/24 圆角层级、正文/辅助/标题字号阶梯和统一阴影层级。
- 动效统一使用现有 motion 能力，进入/退出 120–240ms，并遵循 `prefers-reduced-motion`。

### 公共组件

优先治理：`SettingRow`、`IconButton`、`ResponsiveTabs`、`EntityList/Table`、`Empty/Error/LoadingState`、`ConfirmDangerDialog`、`AgentScopeHeader`、`QueuePanel`、`PollingQuery`、`BoundedRawViewer`。

组件契约：

- `IconButton` 必须有本地化 accessible name。
- `SettingRow` 自主响应容器宽度，不由外层 CSS Module 猜内部类名。
- 列表桌面/移动共享分页与 selection model。
- 所有弹层统一焦点圈、Esc、焦点回退、滚动锁和危险操作文案。
- 状态组件必须明确 loading/empty/error/stale/offline，并提供可执行恢复动作。
- Polling 以 endpoint+scope 去重，具 visibility、backoff、abort 和 freshness 语义。

## 10. 分阶段实施计划与回滚边界

### Phase 0：测量与护栏（1 个迭代）

- 固化三档视口、light/dark、axe、console warning、请求计数、DOM/长任务基线。
- 新增 registry parentId、IconButton name、Token 裸色、单 endpoint 轮询契约检查。
- **回滚边界**：仅测试与监控，不改变 IA/业务行为；可整批回滚。

### Phase 1：P1/P2 外科修复（1–2 个迭代）

- 修 Tools 请求代次、审批队列、820px SettingRow、Chat accessible name。
- 去重 push-message polling；Raw formatter 延迟且有界；移动 Sessions 分页。
- **回滚边界**：每个 Finding 独立 commit/feature flag；API 契约不变。

### Phase 2：公共组件与视觉 Token（2–3 个迭代）

- 抽取上述公共组件；迁移 Queue/BackgroundTask 裸色与弃用 Ant API。
- 先抽 hook/纯组件，再拆 Chat、Hub、ChannelDrawer 等热点，保持 DOM/API 行为。
- **回滚边界**：旧组件保留一版适配层；按页面切换 flag，不做一次性大爆炸替换。

### Phase 3：IA 收敛（2–4 个迭代）

- 发布 All features、六域导航和 canonical URL；旧深链 301/客户端 replace 并保留返回位置。
- Classic/OS 读取同一 registry；Marketplace 单层化。
- **回滚边界**：旧 URL 与导航 schema 至少保留一个稳定版本；遥测异常可回切旧 IA。

### Phase 4：性能与无障碍预算持续化

- CI 定点运行关键视口、axe、请求去重、500/2000 列表、1/5/20MB Raw benchmark。
- **回滚边界**：预算阈值先告警后阻断；确认无基线噪声再升级 gate。

## 11. 实施 Checklist

- [ ] F1 Tools 请求按 Agent 隔离并有乱序回归测试
- [ ] F2 多审批队列可发现、可键盘逐项处理
- [ ] F3 768/769/820/900/901px 设置控件全部可见
- [ ] F4 Chat icon-only controls 均有本地化 accessible name
- [ ] F5 push-message 单轮询链、隐藏页降频
- [ ] F6 折叠 Raw 卡零全量格式化，展开处理有界
- [ ] F7 Sessions 移动首屏 DOM 有界且触点 ≥44px
- [ ] F8 Queue/BackgroundTask 只用语义 Token
- [ ] F9 侧栏每会话仅保留行与菜单两个合理停靠点
- [ ] F10 文件树实现 APG roving focus 与方向键模型
- [ ] F11 语言组合框由可见标题命名
- [ ] F12 Provider 操作包含唯一实体上下文
- [ ] 修正/验证 Checkpoints parentId，并增加 registry invariant test
- [ ] 业务 warning 归零或登记豁免与到期时间
- [ ] 三档视口 × 两主题关键截图基线
- [ ] 鼠标/键盘/触屏真机/滚动 × 正常/错误/反向矩阵完成
- [ ] LCP/INP/CLS、长任务、请求数、DOM 数有可重复数据集
- [ ] canonical URL、旧深链、返回位置和 Classic/OS 状态迁移验证

## 12. 验收标准

1. 六个 P1/P2 核心页面在 390/820/1280px、light/dark 下无不可恢复裁切或文档级横向滚动。
2. 所有图标按钮按 role+本地化 name 可定位；Tab 顺序、Esc、焦点回退符合弹层契约。
3. 正常、错误、取消/返回流均给出明确状态；失败不丢草稿、不跨 Agent 污染。
4. 同 endpoint/scope 单 in-flight；隐藏页按策略降频；恢复不产生请求风暴。
5. 500/2000 sessions 首屏 DOM 有界；Raw 1/5/20MB 不在折叠态做全量同步转换。
6. 自定义 light/dark 主题覆盖 Queue/Task 等核心面板，WCAG AA 对比度达标。
7. canonical IA 可从稳定 All features 找到全部页面；旧深链和返回位置不破坏。
8. Console error 为 0；warning 为 0 或具 owner、理由、到期日的显式豁免。
9. 所有验证结果标注环境、版本、证据等级；未执行项不得写成“通过”。

## 13. 阻断与解除所需输入

- **Hub 管理**：当前非 Hub 模式，`/hub/admin` 重定向；需独立 Hub 测试环境与只读账号。
- **真触屏/屏幕阅读器**：IAB 无真实 touch 设备与 VoiceOver/NVDA 输出；需 iOS/Android 或触屏桌面、VoiceOver/NVDA 测试窗口。
- **写入型正常/反向流**：只读约束禁止创建再删除测试业务数据；需用户批准隔离租户/fixture 和可清理的数据前缀。
- **真实性能**：Resource Timing 不可用且禁止全量 build；需固定 production-like 构建、数据集与 Chrome trace/Profiler。
- **Desktop OS/PawApp**：当前模式/样本不可达；需启用 OS 模式并提供无业务副作用的已安装测试 App。

## 14. 最终裁决

**APPROVE WITH FIXES（针对重构方案进入评审，不代表代码可直接合入）**。

建议先执行 Phase 0 与 Phase 1；IA 与视觉系统方案待用户确认后再进入代码改造。本报告完成后停止，不修改项目代码。
