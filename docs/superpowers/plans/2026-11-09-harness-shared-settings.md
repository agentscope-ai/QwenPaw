# Harness 设置界面与公共工具收敛方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. 功能代码和测试由不同 agent 编写；非核心验证采用临时探针，验收后删除。

**Goal:** 将 Codex/Qoder 的重复设置界面和交互逻辑收敛为一个维护来源，保持插件独立安装、发布和按需加载。

**Architecture:** 两插件在构建时复用 Harness 私有共享前端，公共代码各自编入其 frontend/dist/index.js。请求仍经过公共 SDK 的 host.fetch；厂商包装仅提供名称、文案、登录方式和退出条件。Python IO helper 维护一个标准源码，通过显式同步脚本生成两插件的本地文件，保持现有相对导入与源码开发体验。

**Tech Stack:** React、现有 Ant Design、Vite、TypeScript、lucide-react、现有 Python asyncio 工具；不新增运行时共享插件或公共 SDK API。

**Spec:** 用户提出的第二项收敛反馈及本文件“设计边界”。已按以下步骤完成实施，验证结果记录于文末。

## 已核实的现状

- 每个插件的 Settings.tsx 为 314 行，差异集中在 backend/name、预开浏览器窗口、退出按钮和根类名。
- 每份 Settings.css 为 268 行；规范化根类名后内容完全相同。
- 两份 140 行 Icons.tsx 完全相同，维护了一套 Lucide SVG 节点及自制渲染器。
- 两份 57 行 io_helpers.py 字节完全相同；其等待取消完成和子进程回收行为承载已有正确性修复。
- 当前已使用 host.fetch，无需替换宿主认证、X-Agent-Id 和 API 地址解析。
- 登录轮询间隔为 2 秒、总等待为 120 秒；host.fetch 本身没有单次请求超时。当前关闭只停定时器，未中止所有未完成请求，active 布尔值也不足以区分关闭后重新打开的旧结果。

## 设计边界

采用“共享源码，各自构建”的方式。把完整设置面板重新放回 Console 并通过新增 SDK 组件暴露，会扩大宿主及公共兼容契约；为两种同形界面再建立 schema 驱动渲染框架也没有必要。

分工如下：

| 内容 | 归属 |
| --- | --- |
| 宿主认证、智能体请求头、API 基址 | 现有 host.fetch |
| 二进制输入、检测结果、账户状态、能力列表、公共样式 | 共享 Harness 设置组件 |
| 请求错误解析、轮询、总等待、请求取消和过期结果处理 | 共享连接 hook |
| Codex 名称/文案、浏览器授权、ChatGPT 账户退出条件 | Codex 的薄包装 |
| Qoder 名称/文案、CLI 发起外部授权、不提供登出按钮 | Qoder 的薄包装 |
| CLI 协议、登录进程、账户检测、会话执行与清理 | 现有各厂商后端，保持原行为 |

明确区分维护时去重和发布物自包含：两个 ZIP 各自带有相同的少量编译代码是允许的，不能因此引入另一个插件或远程公共 JS 的运行时依赖。

## 全局约束

- 不修改已完成的 registry 状态职责、宿主 available 语义、实例/调用参数隔离、审批、会话、历史转换和清理修复。
- 不增加插件之间的运行时导入，不要求用户额外安装 common 插件或 Python 公共依赖包。
- 不把可选 Harness UI 静态导入 Console 生产入口，不把整套 Lucide 图标导出到宿主。
- 继续使用现有公共 SDK，不从 console/src 或 qwenpaw.utils 私有路径直接导入运行时能力。
- 两插件保留独立 manifest、入口、语言文案、版本及厂商 SDK requirements。
- 普通用户不安装 Harness 插件时，不加载共享面板、图标或厂商 SDK。
- 同步 IO 仅经现有有界 run_io 处理；锁、客户端、活动状态和生命周期仍留在原事件循环，不把整块 adapter 放进线程。
- 用户安装用的本地最终 ZIP 只更新到 `/Users/luohh/Documents/Qwenpaw/harness插件化`；构建暂存可以使用临时目录。
- 不新增永久细碎回归套件，不放宽旧断言，不把旧套件整体挪进 helper。

## 文件安排

```text
plugins/harness/
  _shared/
    ui/
      Settings.tsx             # 公共布局和类型
      useHarnessConnection.ts  # 公共请求与登录交互生命周期
      Settings.css             # 一份有作用域的公共样式
      hostReact.ts             # Lucide 使用宿主 React 的小型构建桥
    vite.ts                    # 两插件公用的库构建配置
    io_helpers.py              # Python IO helper 唯一手工维护源
  codex/
    io_helpers.py              # 生成文件，保留现有相对导入
    frontend/src/Settings.tsx   # Codex 薄包装
  qoder/
    io_helpers.py              # 生成文件，保留现有相对导入
    frontend/src/Settings.tsx   # Qoder 薄包装
scripts/pack/
  sync_harness_helpers.py      # 同步或检查生成文件，限定这两个插件
```

`_shared/ui` 不命名为 frontend，避免现有 `plugins/harness/*/frontend` 构建通配符将共享源码误当作第三个插件。该目录没有 plugin.json，不进入市场发布列表。

公共组件仅接受现有 HarnessSettingsProps、providerName、厂商 text、`loginMode: "browser" | "external"` 及可选 `canDisconnect(status)`。状态类型及所需文案类型集中定义在共享模块，不从 Codex/Qoder 某一方反向导入类型。Codex 提供 ChatGPT 账户判断；Qoder 不提供退出条件，不渲染该按钮。

删除两份 Icons.tsx 和两份厂商 CSS。保留现有 locale 文件及语言覆盖，本轮不做额外翻译系统重构。

## Task 1：收敛公共组件及厂商差异

- [x] 独立测试作者先记录两个现有界面的检测、连接、认证显示和能力展示基线，确认已有跨插件测试未依赖插件 node_modules。
- [x] 将共同布局与状态类型移入 `_shared/ui/Settings.tsx`，输入仍调用各自 onChange，检测与登录均发送当前表单值，保持未保存配置的原有行为。
- [x] 将公共请求和连接逻辑移入 useHarnessConnection；组件、hook 和样式在同一 ui 目录，不为每个小控件继续拆文件。
- [x] 将厂商入口改成薄包装，保留各自 locale、注册 ID 和 backendId。以真实的 loginMode 和 canDisconnect 表达差异，删除 true/false 常量分支及 Qoder 永远不可达的退出行为。
- [x] 合并 CSS 为 `.harness-settings` 作用域，清理重复覆盖规则但保留最终视觉效果、主题变量、移动端布局、键盘焦点和可访问标签。可保留旧厂商根类名作为兼容附加类。

## Task 2：统一请求、轮询和关闭清理

- [x] hook 内只有一个 POST/JSON/错误解析入口，仍调用 host.fetch；支持 AbortSignal，保留字符串 detail、结构化 detail.message 和 HTTP 状态的错误含义。
- [x] 每个组件实例独立持有状态、定时器和 AbortController，不在共享模块顶层保存连接状态。
- [x] 保留轮询 2 秒和登录启动成功后的总轮询期限 120 秒；同一轮询等上次 status 完成后才安排下一次，不叠加请求。该次重构不额外缩短厂商登录/检测的后端超时。
- [x] 总轮询期限到达时，停止计时器并中止尚未完成的轮询 fetch；关闭、卸载、切换 backend 或智能体时，也中止本组件持有的请求并释放预开空白窗口。
- [x] 通过递增的操作代次忽略旧结果，覆盖“关闭再打开”和“旧请求晚返回”；取消不作为用户可见错误。当前智能体使用现有宿主 hook 获取，不新增 SDK 字段。
- [x] Codex 点击时同步预开空白页以保留浏览器弹窗许可，获得 authUrl 后导航；失败或取消前的空白页关闭。Qoder 交由后端发起 external 登录，不额外打开第二个页面。
- [x] 关闭面板只取消前端请求与轮询，不等同于退出厂商账户，也不承诺终止服务端共享进程。后台授权及进程回收继续由原后端生命周期负责。

## Task 3：使用 Lucide 并保持真正的独立构建

- [x] 两插件明确声明固定版本 lucide-react 构建依赖，使用与当前 Console 一致的 0.562.0；共享组件只静态导入实际使用的图标，不使用动态图标全集。
- [x] 使用 `_shared/ui/hostReact.ts` 将 Lucide 所需的 React 导出绑定到 getHost().host.React，避免插件打包第二份 React 或浏览器残留无法解析的裸 react import。桥接只转发现有 API，不实现另一套 React 或 SVG 渲染器。
- [x] 公共 Vite 配置按调用插件目录解析 @qwenpaw/plugin-sdk 与 lucide-react；共享源码位于两个 frontend 之外，不能假设模块解析会自动找到调用方 node_modules。
- [x] TypeScript paths 同样指向各自 frontend 的已安装依赖和 React 类型；Vite/tsconfig 都覆盖共享源码。两份 vite.config.ts 仅调用公共配置，不重复维护解析规则。
- [x] Console 测试继续用自身安装的 React/Lucide 和现有 SDK alias 运行真实插件源码。若共享目录解析需要 alias，只在测试配置增加准确映射；不让 Console 生产 typecheck 包含插件 TS 项目，不依赖插件 node_modules 才能跑测试。
- [x] 检查两个 dist：共享 UI/CSS 和实际图标各自内联，无指向另一插件、源码相对路径、node_modules 或远程共享 chunk 的运行时引用。

## Task 4：给 IO helper 建立单一维护来源

- [x] 将现有 io_helpers.py 原实现保存到 `_shared/io_helpers.py`；finish、run_io、stop_process 的取消传播、线程等待、terminate/kill/reap 及 5 秒两阶段边界保持不变，不重写算法。
- [x] 新增小型 sync_harness_helpers.py，提供 `--write` 和 `--check`。--write 将标准实现加生成来源注释同步到两插件；--check 检查相同结果，任何手工分叉或未同步都失败，不静默忽略。
- [x] 两份生成文件继续纳入版本管理，使干净 checkout 可直接运行现有 Python 核心测试；厂商 adapter/app-server 的 `.io_helpers` 导入不变。文件标注只修改共享源，并记录同步命令。
- [x] 现有 Harness 构建脚本、打包入口和 Harness CI 接入 --check，不能发布不同步的副本。仅这两个官方插件应用该规则，普通第三方插件的打包不受影响。
- [x] ZIP 各带一份本地 helper，不携带或导入仓库 `_shared` 目录。这是有意的构建期 vendoring：维护一份源码，发布两个自包含副本。

这一选择比新增公共 SDK IO 契约、给插件增加额外 pip 依赖或改变 Python 导入加载机制更小。生成文件仍有重复字节，但不再要求开发者手工同步两套安全逻辑。

## Task 5：验证、打包和清理

- [x] 保留并运行 AgentBackendFields.test.tsx 的真实 Codex/Qoder 集成断言；若 fetch 新增 signal，仅检查该附加字段的存在，不能丢掉路径、请求体、当前表单值和厂商登录差异断言。
- [x] 使用临时探针验证：轮询不重入、关闭/换智能体后中止、120 秒截止、旧结果不覆盖新界面、认证成功后停止、Codex 弹窗失败清理和 Qoder 不额外打开网页。完成后删除，少量核心断言合入既有测试。
- [x] 先移走两个插件 node_modules，在干净依赖边界运行 Console 生产构建和现有跨插件测试；然后分别仅安装单个插件的构建依赖，单独构建并验证另一个插件不存在也能成功。
- [x] 使用现有生成插件 ZIP 的测试核对：两个 ZIP 各含自己的入口、dist 和 IO helper，无其他厂商代码，无构建期共享路径依赖。产物单独解压后安装、导入和 UI 加载，不能只验证仓库内源码可运行。
- [x] 运行已有 SDK/宿主总测试及两个厂商总测试；用临时取消探针确认同步线程真正结束后才释放、进程确实被回收，随后删除探针。不扩大长期测试框架。
- [x] 确认重复布局、CSS、SVG 节点和常量分支已删除；helper 生成校验通过，外部插件 ZIP 仅写入约定目录。
- [x] 独立审查后核对 diff，保护 registry、审批/实例配置、会话和 IO 旧修复；在方案中记录结果，再形成独立提交。

## 最终验收 checklist

- [x] 设置布局、样式和连接生命周期分别只有一个维护来源；两包装只表达厂商差异。
- [x] 无手抄 Lucide 节点、常量分支、第二份 React 或全量动态图标导入。
- [x] host.fetch 认证和智能体隔离保持完整；所有状态、定时器和请求均属于当前面板实例。
- [x] 单个插件独立构建、独立安装和独立运行；用户无须安装共享插件。
- [x] 不使用插件的用户不增加 Harness UI、图标或厂商运行时负担。
- [x] IO 实现仅手工维护一次，生成文件不同步即构建失败，原取消/回收语义不变。
- [x] 原断言保留，长期测试框架保持精简，非核心探针全部删除。


## 实施与验收记录

- 一份共享设置面板、连接 hook 和 CSS；Codex/Qoder 薄包装保留文案、登录方式和退出条件。静态 Lucide 及宿主 React 桥不向 Console 核心增加 Harness UI。
- IO canonical 源与原实现字节一致；两生成副本只增加来源注释，UTF-8 pragma 位于首行，CRLF checkout 归一校验。所有原后端、registry、SDK、会话和审批保护文件 hash 不变。
- 前端 34 项（原7+临时23+审查补充竞态4）通过；宿主/配置/SDK/打包 66 项、Console SDK/host 90 项、厂商 18 项通过。9 组真实线程取消/子进程回收验证通过。永久测试仅增加所需宿主夹具/AbortSignal 和 ZIP 断言，共9行；非核心探针全部删除。
- 两插件 node_modules 移走后，Console 原7+临时23通过，生产构建及所有资源预算检查通过。各自仅自身+共享源+公共SDK的干净源码目录独立安装并构建成功，无兄弟插件或旧 node_modules。依赖缓存不足后使用临时 cache 与官方 registry 正常TLS安装固定声明版本，未改全局配置。
- 两个真实 ZIP 分别独立解压，后端真实安装/导入/注册及本地 helper 执行、编译前端实际注册和 React DOM/SVG 渲染均通过。相同 ZIP 供厂商核心测试消费；原仓库 dist 与依赖目录已恢复。
- 独立审查指出的“迟到 Detect 覆盖登录成功”已最小修复，4 条定向探针 RED→GREEN；检测仍不中断登录轮询。最终 spec compliance / code quality 均通过，无剩余 mustfix；pre-commit 全通过。
- 同一对已审 ZIP 已原子更新到 `/Users/luohh/Documents/Qwenpaw/harness插件化`；原包备份与新包SHA记录在验收证据中。证据目录：`/private/tmp/qwenpaw-shared-settings-evidence-20261109/`。
