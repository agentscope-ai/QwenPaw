# Console 前端性能 P0 修复方案

基线：`734c8b9f`（origin/main），分支：`feat/console-perf-p0`

对应性能审查报告的 P0 项：Finding 3（折叠卡片完整挂载）、Finding 4（隐藏媒体加载 / 假 HEAD）、
Finding 5（RunToolBatchCard 无 memo）、Finding 1（启动全量 warm-up）、Finding 2（Monaco/Coding 进入口）。

## 设计约束（已核实）

1. `window.QwenPaw.modules` 保留为“已加载模块快照”，不再为它全量预热页面。
   插件如需在同步初始化时 patch host module，必须在
   `entry.host_modules` 声明依赖；加载器会在执行插件 bundle 前按需加载。
   新插件也可直接 `await window.QwenPaw.loadModule(key)`。
2. Monaco 仅被 `pages/Coding/TabbedEditor.tsx` 使用（经 `@monaco-editor/react`）。
   monacoSetup 是副作用模块，要求"在任何 Monaco 挂载前执行一次"。
   → 下沉到 Coding 页入口 import 即可满足时序。
3. Chat 是默认路由，保持 eager；Coding 改 `lazyImportWithRetry`。
4. `<details>` 的 `toggle` 事件是标准受控点；ToolCardShell 仅在
   `open === true` 时挂载 body，折叠后卸载媒体和 DOM。高成本 card 必须使用
   `renderBody`，否则父组件仍会在折叠态预先计算 children。
5. MediaPreview 的 file 探测改 `method: "HEAD"`；后端若不支持 HEAD，
   fetch 会返回 405 → 探测逻辑视作"可访问"降级处理（只有 403/404/网络错误报错）。
   onError 后的诊断 GET 保留（那是失败路径，低频）。
6. 图片加 `loading="lazy"` + `decoding="async"`（antd Image 透传 img 属性）。

## Batch 1：折叠卡片懒挂载 + 媒体修复 + RunToolBatchCard memo

- [x] `ToolCardShell.tsx`：统一仅按 `isOpen` 挂载 body（含 error 块）；
      高成本 card 改用 `renderBody`，折叠态不执行序列化、媒体解析或 diff DOM 构造
- [x] `MediaPreview.tsx`：
  - [x] `fetchPreviewError` 拆出 probe（HEAD）与 diagnose（GET）两条路径；file 探测用 HEAD，405/501 视为可访问
  - [x] `<Image>` 加 `loading="lazy"`、`decoding="async"`
  - [x] 同一 URL 的探测使用 100 项、5 分钟 TTL 的 LRU 缓存；失败结果立即清除
- [x] `RunToolBatchCard.tsx`：
  - [x] `mediaItems` / `outputText` 在 card 生命周期内按 `content.result` 引用缓存
  - [x] 折叠后卸载 body，再次展开复用已有派生结果
  - [x] 组件包 `React.memo`
- [x] 单测：ToolCardShell 折叠不挂载 children / 展开后挂载；MediaPreview HEAD 探测与缓存；RunToolBatchCard memo 行为（ToolCards 目录 20/20 通过）
- [x] `npm run test:run` 全量通过 + format（见最终验证阶段）

## Batch 2：删除启动全量 warm-up

- [x] `dynamicModuleRegistry.ts`：启动时只注册 `import.meta.glob` factory，不执行页面 import
- [x] `moduleRegistry.ts`：增加并发去重的 `load(key)`，路由和插件共用同一加载路径
- [x] 插件 manifest 支持 `entry.host_modules`，CloudPaw 声明 Chat config module
- [x] 旧同步 API 访问尚未加载模块时输出明确迁移警告
- [x] 定向测试与全量测试通过

## Batch 3：Monaco/Coding 移出入口 + 拆包

- [x] `main.tsx` 移除 `import "./monacoSetup"`
- [x] `pages/Coding/index.tsx`（或其入口）顶部加 `import "../../monacoSetup"`
- [x] `builtinRoutes.tsx`：CodingPage 改 `lazyImportWithRetry("../../pages/Coding")`
- [x] `vite.config.ts` manualChunks：monaco-editor 拆为 monaco-vendor；
      Ant Design 与 `@agentscope-ai/*` 保持同一 ui-vendor，避免循环 chunk
- [x] production build 验证：index + module-preload 总量显著下降
- [x] 全量测试与 production build 通过

## 验证与提交

- [x] `npm run build:prod` 实测：首屏 HTML 直接加载/预加载约
      9.81 MiB raw / 2.90 MiB gzip；Monaco 4.31 MiB 不再进入首屏 preload
- [x] 全量 `npm run test:run` 通过（146 files / 1234 tests）
- [x] `tsc -b --noEmit` + prettier 通过；production build 通过
- [ ] 后端 pytest：`qwenpaw_dev` 当前未安装 pytest；已完成 compileall 和
      manifest 行为检查，待环境补齐 test extra 后执行完整用例

备注：沙箱环境下 vitest 需 `TMPDIR=/private/tmp`，否则写系统临时目录 EPERM。

## 明确不做（本次范围外）

- Finding 6：已移除核心 UI 的插件阻塞，单插件加入 15 秒超时和 fetch 取消
- Finding 7（轮询合并）、9（缓存 byte budget）→ P1
- Finding 8、10（SDK 内部）→ 需上游配合
- Finding 11（动画）→ P2
