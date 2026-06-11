# Console Migration — Ant Design v5 → shadcn/ui + Tailwind v4

> **Shared knowledge brief for the Ruflo agent team.** Every agent working on this
> migration MUST read this file first. It is the single source of truth for
> decisions, conventions, and the antd→shadcn mapping. Keep it updated as the
> migration progresses (append to the "Progress log" at the bottom).

## 1. Goal & scope

Reformulate the **visual layer** of the `console/` app (QwenPaw's main app: chat,
coding, agent/skill/MCP management) from **Ant Design v5** to **shadcn/ui +
Tailwind v4 + Radix + motion** — the same modern stack already used in `website/`.

- **In scope:** `console/` only. NOT `website/`, NOT plugins.
- **Approach:** incremental rewrite. The app must stay buildable/functional after
  every slice. Migrate foundation → layout+Chat → other pages → cleanup.
- **DO NOT change the contract of:** `console/src/api/**`, `console/src/stores/**`,
  `console/src/locales/**`, `console/src/i18n.ts`, `console/src/plugins/**`,
  `console/src/tauri/**`. Reuse them as-is. Only swap presentation.

## 2. Hard facts about the current app (verified)

- **Scale:** ~339 antd/`@ant-design`/`antd-style`/`@agentscope-ai` imports across
  ~202 files under `console/src`.
- **Brand primary color is ORANGE `#FF7F16`** — `App.tsx` overrides the Bailian
  blue with `token.colorPrimary = "#FF7F16"`. Use orange as the primary in the new
  design tokens. (Bailian blue `#1677ff` is NOT the real brand color.)
- **Dark mode** is toggled by adding the class **`.dark-mode`** to
  `<html>` (see `src/contexts/ThemeContext.tsx`). The Tailwind v4 dark variant MUST
  target `.dark-mode`, NOT the default `.dark`. Add in `index.css`:
  `@custom-variant dark (&:is(.dark-mode *));`
  `ThemeContext` already manages light/dark/system + localStorage key
  `qwenpaw-theme`. **Preserve its public API** (`themeMode`, `isDark`,
  `setThemeMode`, `toggleTheme`, `useTheme()`). Only its job changes: it no longer
  needs to feed antd's `ConfigProvider`; it just keeps toggling `.dark-mode`.
- **Path alias:** `@` → `console/src` (in `vite.config.ts` + `tsconfig`).
- **Router:** `react-router-dom@7`, basename may be `/console` (see
  `getRouterBasename` in `App.tsx`). Keep routing untouched.
- **i18n:** `react-i18next`, 5 locales (en/zh/ja/ru/id) in `src/locales`. antd also
  provided its own locale + dayjs locale wiring in `App.tsx` — once antd is gone,
  drop the `antd/locale/*` imports but KEEP dayjs locale wiring and i18n.
- **Backend:** FastAPI REST + **SSE** streaming. Client lives in
  `src/api/**` (40+ modules, `request.ts`, `config.ts`, `authHeaders.ts`). SSE is
  consumed via `src/pages/Chat/**`. Do not touch transport — only re-render.
- **Desktop:** Tauri integration in `src/tauri/**`. Don't break imports.
- **Tests:** Vitest + Testing Library. `vite.config.ts` `test.alias` stubs
  `@agentscope-ai/chat|design|icons`. When those packages are removed, remove the
  corresponding aliases/`deps.inline`/`cssStubPlugin` entries too. Excluded tests:
  `ChatPage.test.tsx`, `src/tauri/**`, `testConnectionMessage.test.ts`.
- **Build:** `npm run build` = `tsc -b && vite build`. `manualChunks` in
  `vite.config.ts` currently buckets `antd`/`@ant-design`/`@agentscope-ai` into
  `ui-vendor` — update when antd is removed.

## 3. Target stack & conventions

- **Tailwind v4** via `@tailwindcss/vite` plugin (NOT PostCSS). Single
  `src/index.css` with `@import "tailwindcss";`, `@custom-variant dark`, and
  `@theme`/`:root`/`.dark-mode` CSS-variable tokens. Mirror website's `index.css`
  approach (`website/src/index.css`) but with orange primary.
- **shadcn/ui** components generated into `src/components/ui/**`. Config in
  `console/components.json` (style: new-york or default; base color: neutral;
  rsc: false; tsx: true; aliases `@/components`, `@/components/ui`, `@/lib/utils`).
- **`cn()` helper** in `src/lib/utils.ts` — copy from `website/src/lib/utils.ts`
  (`clsx` + `tailwind-merge`).
- **Icons:** `lucide-react` (already a dependency). Replace `@ant-design/icons`.
- **Animation:** `motion` (Framer Motion successor) for transitions.
- **Forms:** `react-hook-form` + `zod` + shadcn `Form` for antd `Form` replacements.
- **Toasts:** `sonner` replaces antd `message`/`notification`. Mount `<Toaster />`
  once in `App.tsx`. Provide a thin adapter so existing `message.success(...)`
  call-sites can be swapped with minimal churn (or a codemod-style find/replace).
- **Charts:** `@ant-design/plots` (used in Settings/TokenUsage) → `recharts`
  (shadcn chart) in Phase 2. Low priority.

### New deps to add (`console/package.json`)

`tailwindcss@^4`, `@tailwindcss/vite@^4`, `class-variance-authority`, `clsx`,
`tailwind-merge`, `tw-animate-css`, `motion`, `sonner`, `react-hook-form`,
`@hookform/resolvers`, `zod`, and the `@radix-ui/react-*` primitives pulled in by
the shadcn components you generate. Keep `lucide-react`, `react-markdown`,
`remark-gfm`, `mermaid`, `@monaco-editor/react`, `react-resizable-panels`,
`@dnd-kit/*`, `zustand`, `ahooks`, `dayjs`, i18n libs.

## 4. antd → shadcn/Tailwind component map

| Ant Design                                                                | shadcn/ui replacement                                                          | Notes                                                                                                                 |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| `Button`                                                                  | `Button` (`ui/button`)                                                         | map `type="primary"`→default, `text`→`ghost`, `link`→`link`, `danger`→`destructive`; `loading` → spinner + `disabled` |
| `Input`, `Input.TextArea`, `Input.Password`                               | `Input`, `Textarea`, password input                                            |                                                                                                                       |
| `Select`                                                                  | `Select` (`ui/select`)                                                         | for searchable/multi use `Command`/`combobox` pattern                                                                 |
| `Form`, `Form.Item`                                                       | `Form` + `react-hook-form` + `zod`                                             | reuse backend `agent/schema` JSON-Schema where forms are schema-driven                                                |
| `Modal`                                                                   | `Dialog` (`ui/dialog`)                                                         | confirm modals → `AlertDialog`                                                                                        |
| `Drawer`                                                                  | `Sheet` (`ui/sheet`)                                                           | `side` prop = left/right/top/bottom                                                                                   |
| `Table`                                                                   | `Table` (`ui/table`) + `@tanstack/react-table` if sorting/paging needed        | many `columns.tsx` files                                                                                              |
| `Tabs`                                                                    | `Tabs` (`ui/tabs`)                                                             |                                                                                                                       |
| `Segmented`                                                               | `Tabs` or `ToggleGroup`                                                        |                                                                                                                       |
| `Card`                                                                    | `Card` (`ui/card`)                                                             |                                                                                                                       |
| `Tag`                                                                     | `Badge` (`ui/badge`)                                                           |                                                                                                                       |
| `Tooltip`                                                                 | `Tooltip` (`ui/tooltip`)                                                       | wrap app in `TooltipProvider`                                                                                         |
| `Dropdown`, `Menu`                                                        | `DropdownMenu` (`ui/dropdown-menu`)                                            | sidebar menu → custom nav + `NavLink`                                                                                 |
| `Popconfirm`                                                              | `AlertDialog`                                                                  |                                                                                                                       |
| `Popover`                                                                 | `Popover` (`ui/popover`)                                                       |                                                                                                                       |
| `Switch`                                                                  | `Switch` (`ui/switch`)                                                         |                                                                                                                       |
| `Checkbox`/`Radio`                                                        | `Checkbox`/`RadioGroup`                                                        |                                                                                                                       |
| `Slider`                                                                  | `Slider` (`ui/slider`)                                                         | see `Agent/Config/SliderWithValue`                                                                                    |
| `Collapse`                                                                | `Accordion` (`ui/accordion`)                                                   |                                                                                                                       |
| `Skeleton`, `Spin`                                                        | `Skeleton` (`ui/skeleton`) + small spinner (lucide `Loader2` + `animate-spin`) |                                                                                                                       |
| `Avatar`                                                                  | `Avatar` (`ui/avatar`)                                                         |                                                                                                                       |
| `message`, `notification`                                                 | `sonner` toasts                                                                |                                                                                                                       |
| `App` (antd) / `ConfigProvider`                                           | remove; replace with `TooltipProvider` + `<Toaster />`                         |                                                                                                                       |
| `theme`, `bailian*Theme`, `antd-style` `createGlobalStyle`/`createStyles` | Tailwind classes + `index.css` tokens                                          |                                                                                                                       |
| `@ant-design/icons`                                                       | `lucide-react`                                                                 |                                                                                                                       |
| `@ant-design/plots`                                                       | `recharts` (shadcn chart)                                                      | Phase 2                                                                                                               |
| `@ant-design/x-markdown`, `@agentscope-ai/chat`                           | `react-markdown` + custom bubble components                                    | Chat slice                                                                                                            |
| `Upload`                                                                  | custom dropzone (`react-dropzone` optional) or input[type=file]                | Chat/Settings                                                                                                         |
| `DatePicker`/`TimePicker`                                                 | shadcn `Calendar` + `Popover` (`react-day-picker`) or native                   | CronJobs/Schedules                                                                                                    |
| `Pagination`                                                              | shadcn `Pagination`                                                            |                                                                                                                       |
| `Progress`                                                                | custom Tailwind bar or `ui/progress`                                           |                                                                                                                       |
| `Tree`                                                                    | custom (`FileTree`) — keep logic, restyle                                      | Coding                                                                                                                |
| `Result`, `Empty`, `Descriptions`, `Statistic`                            | compose with Card/Tailwind                                                     |                                                                                                                       |

## 5. AgentScope v2 features the new UI should expose better

(See `docs/agentscope-v2/`.) The redesign should make these first-class:

- **Event streaming (`reply_stream`)**: render incremental text deltas, collapsible
  **thinking** blocks, **tool_call**/**tool_result** cards (already modeled in
  `src/components/Chat/ToolCards/**` — restyle, keep behavior).
- **Permission / approval (human-in-the-loop)**: `ApprovalCard` + `ApprovalContext`
  → shadcn `Dialog`/`AlertDialog` with clear allow/deny/ask and rule suggestions.
- **Content blocks**: text / thinking / tool_call / tool_result / image(DataBlock).
- **Sessions, agents, credentials, models, schedules, skills, MCP, workspace,
  multi-agent (Team)** — management surfaces (Phase 2).

## 6. Migration phases (order)

- **Phase 0 — Foundation:** deps, Tailwind v4 in `vite.config.ts`, `src/index.css`
  tokens (orange primary, `.dark-mode` variant), `components.json`,
  `src/lib/utils.ts`, base `src/components/ui/**` kit, rewrite `ThemeContext` (drop
  antd `ConfigProvider`; mount `TooltipProvider` + `<Toaster/>` in `App.tsx`).
  **Phase 0 must leave the app building** (antd still present elsewhere — that's OK;
  Tailwind and antd coexist during the transition).
- **Phase 1 — Layout + Chat:** `src/layouts/**`, `src/pages/Chat/**`,
  `src/components/Chat/**`, `ApprovalCard`. Highest value.
- **Phase 2 — Other pages:** `pages/Agent/**`, `pages/Coding/**`, `pages/Inbox/**`,
  `pages/Control/**`, `pages/Settings/**`, `pages/Login/**`.
- **Phase 3 — Cleanup:** remove `antd`, `antd-style`, `@ant-design/*`,
  `@agentscope-ai/*`, `less`, orphan `styles/*.css`; update `vite.config.ts`
  (`manualChunks`, css `less`/modules, test aliases/`cssStubPlugin`).

## 7. Coexistence rule (critical)

During the transition antd and Tailwind run side by side. To avoid style clashes:

- Tailwind preflight can conflict with antd's reset. Mitigation: keep antd's CSS;
  scope new components with Tailwind utility classes; if preflight breaks antd,
  disable preflight base layer or import order so antd wins on legacy pages. Verify
  visually after Phase 0.
- Never delete an antd page until its replacement is merged and verified.

## 8. Verification (run after each slice)

- `cd console && npm install`
- `npx tsc -b` (no type errors) ; `npm run build` (green)
- `npm run lint`
- `grep` for residual `from "antd"` / `@ant-design` in migrated files → must be 0
- `npm run test` for touched slices
- `npm run dev` + Playwright/Chrome MCP: Chat streaming, approval dialog,
  light/dark toggle (`.dark-mode`), navigation. Screenshots before/after.

## 9. Progress log

- (init) Brief created. Phase 0 starting. antd footprint: 339 imports / 202 files.
- (Phase 0 done — 2026-06-11) Foundation installed and verified by CODER agent.

  Files CREATED:

  - console/components.json — shadcn config (new-york, neutral base, cssVariables, aliases)
  - console/src/index.css — Tailwind v4 entry: `@import "tailwindcss"`, `@import "tw-animate-css"`, `@custom-variant dark (&:is(.dark-mode *))`, `@theme inline` token map, `:root` light tokens (orange primary oklch ≈ #FF7F16), `.dark-mode` dark tokens
  - console/src/lib/utils.ts — `cn()` helper (clsx + tailwind-merge)
  - console/src/components/ui/ — 24 shadcn components: button, input, textarea, label, card, dialog, alert-dialog, sheet, tabs, dropdown-menu, tooltip, scroll-area, avatar, badge, separator, select, switch, checkbox, skeleton, sonner, form, popover, accordion, table, slider

  Files MODIFIED:

  - console/package.json — new deps: tailwindcss@^4.1.8, @tailwindcss/vite@^4.1.8, class-variance-authority, clsx, tailwind-merge, tw-animate-css, motion, sonner, react-hook-form, @hookform/resolvers, zod, 16 @radix-ui/react-\* primitives
  - console/vite.config.ts — added tailwindcss() plugin from @tailwindcss/vite
  - console/src/main.tsx — added `import "./index.css"` before App import
  - console/src/App.tsx — added TooltipProvider + Toaster; antd ConfigProvider retained for legacy pages

  Verification:

  - `npm install` — success (1176 packages)
  - `npx tsc -b` — PASS (zero errors)
  - `npm run build` — SUCCESS in 34.98s
  - ThemeContext.tsx unchanged — `.dark-mode` toggling and public API intact
  - antd pages unmodified — coexistence intact

- Phase 1 — Layout (Coder A) done — 2026-06-11: Layout shell + header widgets migrated. Files: `layouts/MainLayout/index.tsx` (antd Layout/Spin→Tailwind flex+Loader2), `layouts/Header.tsx` (antd+agentscope+@ant-design/icons→shadcn Dialog/DropdownMenu/Tooltip/Button+lucide), `layouts/Sidebar.tsx` (antd Sider/Menu/Button/Modal/Form→shadcn Dialog/Tooltip/ScrollArea/Button/Input+Tailwind nav), `layouts/registry/adapter.tsx` (removed antd MenuProps, dropped toAntdItems), `layouts/registry/builtinRoutes.tsx` (antd Spin→Loader2), `components/ThemeToggleButton/index.tsx`, `components/LanguageSwitcher/index.tsx`, `components/CodingModeToggle/index.tsx`, `components/AgentSelector/index.tsx` (antd Select/Tag/Tooltip→shadcn Popover/Badge/Tooltip). Verification: `npx tsc -b` PASS (zero errors); `npm run build` SUCCESS (37.96s); grep antd/`@ant-design`/`antd-style` in slice = 0.
- Phase 1 — Approval/Inbox (Coder B) done: Migrated `components/ApprovalCard/ApprovalCard.tsx`, `pages/Inbox/index.tsx`, `pages/Inbox/components/{ApprovalCard,PushMessageCard,HarvestCard,CreateHarvestModal,MagazineStackViewer}.tsx`, `pages/Inbox/hooks/useTraceViewer.ts`. antd→shadcn: Card/CardContent, Button (destructive/outline/ghost), Badge (severity colors), Dialog, AlertDialog (Popconfirm→AlertDialog), Accordion (Collapse), Tabs, Select, Checkbox, Avatar, Form+react-hook-form+zod (CreateHarvestModal), sonner toasts (message.success/error/info/warning). lucide-react for all @ant-design/icons. antd Progress (circular) replaced with inline SVG. `npx tsc -b` — PASS (zero errors in slice). grep antd — ZERO in slice.
- Phase 2 — Agent pages done — 2026-06-11: Migrated all files under `pages/Agent/**` (ACP, Config, MCP, Skills, Tools, Workspace and their components/hooks). antd→shadcn: Card/CardContent, Button, Input, Textarea, Label, Switch, Select, Dialog, AlertDialog (Modal.confirm→confirmResolverRef pattern), Sheet (Drawer), Accordion (Collapse), Tabs, Form+react-hook-form (useFormContext/useWatch/Controller/form.reset), sonner toasts via useAppMessage hook. lucide-react for all @ant-design/icons. SliderWithValue updated to shadcn Slider API (value={[n]}, onValueChange). window.confirm() for non-React .ts hook (useSkills.ts). `npx tsc -b` — PASS (zero errors in slice). grep antd/`@agentscope-ai/design`/`@ant-design` in slice = ZERO.
- Phase 2 — Control/Coding/Login/misc done — 2026-06-11 (CODER): Migrated entire assigned slice: `pages/Control/**` (Sessions, Channels, CronJobs, Heartbeat + all components), `pages/Coding/**` (index, FileTree, TabbedEditor, GitPanel — kept @monaco-editor/react + react-resizable-panels), `pages/Login/index.tsx`, `components/PlanPanel`, `components/ProjectSelectModal`, `components/SkillVisual`, `components/MarkdownCopy`, `components/MermaidCodeBlock`, `components/ChunkErrorBoundary`, `hooks/useAppMessage`, `utils/scanError`, `utils/freeModelSwitchWarning`. antd→shadcn: Sheet (Drawer), Dialog (Modal), AlertDialog (Popconfirm/Modal.confirm), useReactTable+ColumnDef (antd Table), Button, Input, Textarea, Select, Switch, Switch, Label, Badge→Tailwind span, Tooltip (Trigger/Content pattern), DropdownMenu (Table row actions), Checkbox. Form.useForm()→useState controlled state with form-proxy ref pattern (parent calls form.current.setFieldsValue/getFieldValue/resetFields/submit, child wires its own state into those methods via useEffect). Native `<input type="time">` + `<input type="datetime-local">` replace antd TimePicker/DatePicker. Tabs→CSS button tabs with activeTab state. Tag→Tailwind colored spans. `useAppMessage()` (sonner adapter) replaces `message.useMessage()`; removed all `{contextHolder}` usages. lucide-react for all @ant-design/icons. `createRoot` portal for imperative utils (scanError, freeModelSwitchWarning). `npx tsc -b` — one pre-existing error in `pages/Agent/Workspace/components/FileEditor.tsx` (outside slice, present before changes); zero new errors from this slice. grep antd/`@agentscope-ai/design`/`@ant-design` in slice = ZERO.
- AionUi re-theme color sweep done — 2026-06-11: Replaced all hardcoded orange/cream/dark colors (#ff7f16, #d45b0a, #f9f8f4, #f9f7f3, #1a1a1a, #1e1e1e, rgba(255,127,22,_), rgba(255,157,77,_), rgba(43,18,0,\*)) across 11 files with AionUi design tokens (bg-primary/text-primary-foreground, bg-accent, bg-muted, bg-card, bg-sidebar/border-sidebar-border, bg-border, text-foreground, text-muted-foreground). Chart orange series colors replaced with `#5b4b8a` (violet brand accent). BackendLoadingPage gauge stroke updated to `var(--primary)`. PreviewModal dark/light `pre` conditional replaced with single token class; unused `isDark` usage and `useTheme` import removed. Added `src/fontsource.d.ts` to declare `@fontsource-variable/inter` (pre-existing TS2307 error). `npx tsc -b` — PASS (zero errors). `npm run build` — SUCCESS. grep forbidden colors in 11 files = ZERO.
- Pre-PR a11y/theme fixes applied — 2026-06-11: (BLOCKERS) Added `sr-only` `SheetHeader`/`SheetTitle`/`SheetDescription` to `ChatSessionDrawer` and `ChatSearchPanel` to satisfy Radix accessible-name requirement. (SHOULD-FIX A) Replaced remaining hardcoded `#FF7F16` with `text-primary`/`bg-primary`/`accent-primary`/`var(--primary)` in ACPDrawer, ChannelDrawer, BackupProgress, BackupScopeForm, RestoreBackupModal, ProviderConfigModal, ModelSelector, AudioModeCard, ProviderTypeCard, HarvestCard (provider icon avatar palette entry in `providerLetterIcon.tsx` and App.tsx antd ConfigProvider intentionally preserved). (SHOULD-FIX B) Login page card/text literals replaced with `bg-card`/`text-muted-foreground`; `isDark` retained for gradient + logo src. (SHOULD-FIX C) Added `DialogDescription`/`SheetDescription` (sr-only) to ProjectSelectModal, PlanPanel, ImportHubModal, PoolTransferModal, SkillDrawer, useConflictRenameModal, AgentModal, CreateBackupModal, SilentBackupModal, CustomProviderModal, JobDrawer, CreateHarvestModal. `npx tsc -b` — PASS (zero errors). `npm run build` — SUCCESS (43.60s).

---

## 10. Research inventory (2026-06-11, researcher)

### 10.1 Antd / @ant-design / antd-style / @agentscope-ai symbol frequency table

Symbols tallied from grep over `console/src/**/*.{ts,tsx}` (antd + @agentscope-ai/design as the design system wrapper for antd). These are the top ~30 prioritised by count; count = distinct import-lines referencing the symbol (a file importing two components in one line counts as one per symbol).

| Symbol                                                                                   | Source pkg                   | Approx count     | Representative files                                                                                                                                         |
| ---------------------------------------------------------------------------------------- | ---------------------------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Button`                                                                                 | antd / @agentscope-ai/design | ~60              | Most pages and components                                                                                                                                    |
| `Modal`                                                                                  | antd / @agentscope-ai/design | ~30              | Chat/index.tsx, Inbox/index.tsx, Agent/_, Settings/_, Control/\*                                                                                             |
| `Form`                                                                                   | antd / @agentscope-ai/design | ~28              | Login/index.tsx, Agent/Config/\*\*, Control/CronJobs/JobDrawer.tsx, Control/Channels/ChannelDrawer.tsx, Settings/Agents/AgentModal.tsx, etc.                 |
| `Input`                                                                                  | antd / @agentscope-ai/design | ~25              | Sidebar.tsx, Chat/ChatSessionItem, Settings/Models, Control/Sessions/FilterBar.tsx, etc.                                                                     |
| `Card`                                                                                   | antd / @agentscope-ai/design | ~22              | Inbox/\*, Agent/Config/**, Settings/Models/**, ApprovalCard.tsx                                                                                              |
| `Tooltip`                                                                                | antd / @agentscope-ai/design | ~20              | Sidebar.tsx, Header.tsx, Coding/_, Chat/_, Control/CronJobs/columns.tsx                                                                                      |
| `Tag`                                                                                    | antd / @agentscope-ai/design | ~18              | Inbox/\*, Settings/Backups/ScopeTags.tsx, Control/Sessions/columns.tsx                                                                                       |
| `Select`                                                                                 | antd / @agentscope-ai/design | ~17              | AgentSelector, Settings/Models, Control/Channels, Agent/MCP/index.tsx                                                                                        |
| `Spin`                                                                                   | antd                         | ~15              | Layouts, Coding/FileTree.tsx, Chat/ModelSelector, Agent/Tools, Settings/\*                                                                                   |
| `Drawer`                                                                                 | antd / @agentscope-ai/design | ~12              | Chat/ChatSessionDrawer, Chat/ChatSearchPanel, Agent/Skills/SkillDrawer.tsx, Control/Sessions/SessionDrawer.tsx, Settings/Market/DetailDrawer.tsx             |
| `Table`                                                                                  | antd / @agentscope-ai/design | ~10              | Settings/Agents/AgentTable.tsx, Settings/Backups/BackupTable.tsx, Settings/Backups/RestoreAgentTable.tsx, Settings/PluginManager, Control/Sessions/index.tsx |
| `Tabs`                                                                                   | antd / @agentscope-ai/design | ~9               | Agent/MCP/index.tsx, Agent/Config/index.tsx, Settings/PluginManager, Settings/Security                                                                       |
| `Switch`                                                                                 | antd / @agentscope-ai/design | ~8               | Agent/MCP/MCPOAuthSection, Agent/Config/\*\*, Agent/Workspace/FileItem.tsx                                                                                   |
| `Dropdown`                                                                               | antd / @agentscope-ai/design | ~8               | Header.tsx, ThemeToggleButton, LanguageSwitcher, Control/CronJobs/columns.tsx                                                                                |
| `Typography` / `Text`                                                                    | antd                         | ~8               | ApprovalCard.tsx, Settings/Debug, Settings/Backups/BackupProgress.tsx                                                                                        |
| `Badge`                                                                                  | antd                         | ~6               | Header.tsx, Sidebar.tsx, Coding/index.tsx, Control/Channels/index.tsx                                                                                        |
| `Progress`                                                                               | antd                         | ~5               | PlanPanel, Settings/Backups/BackupProgress.tsx, Settings/Models/LocalModelManageModal.tsx, tauri/BackendLoadingPage.tsx                                      |
| `Alert`                                                                                  | antd                         | ~5               | Settings/VoiceTranscription/\*, Control/Channels/ChannelDrawer.tsx                                                                                           |
| `Checkbox`                                                                               | antd / @agentscope-ai/design | ~5               | Settings/Backups/BackupScopeForm.tsx, Settings/Environments/EnvRow.tsx, Agent/Skills/\*                                                                      |
| `Radio`                                                                                  | antd                         | ~5               | Settings/VoiceTranscription/\*, Settings/Backups/BackupScopeForm.tsx                                                                                         |
| `Popconfirm`                                                                             | antd                         | ~5               | Settings/Agents/AgentTable.tsx, Settings/Backups/BackupTable.tsx, Inbox/PushMessageCard.tsx                                                                  |
| `Empty`                                                                                  | antd / @agentscope-ai/design | ~4               | Agent/MCP, Settings/AgentStats, Settings/PluginManager                                                                                                       |
| `Space`                                                                                  | antd                         | ~4               | ApprovalCard.tsx, Settings/Security, Settings/Backups/CreateBackupModal.tsx                                                                                  |
| `DatePicker` / `TimePicker`                                                              | antd                         | ~4               | Settings/AgentStats/index.tsx, Settings/TokenUsage/index.tsx, Control/CronJobs/JobDrawer.tsx, Control/Heartbeat/index.tsx                                    |
| `Avatar`                                                                                 | antd                         | ~1               | Inbox/PushMessageCard.tsx                                                                                                                                    |
| `Pagination`                                                                             | antd                         | ~1               | Settings/PluginManager/MarketPluginList.tsx                                                                                                                  |
| `AutoComplete`                                                                           | antd                         | ~1               | Settings/Models/RemoteModelManageModal.tsx                                                                                                                   |
| `Slider`                                                                                 | @agentscope-ai/design        | ~1               | Agent/Config/SliderWithValue.tsx                                                                                                                             |
| `IconButton`                                                                             | @agentscope-ai/design        | ~8               | Chat/\*, PlanPanel, ChatSessionItem, ChatActionGroup, ChatSearchPanel, WhisperSpeechButton                                                                   |
| `@ant-design/icons` (all)                                                                | @ant-design/icons            | ~70 import-lines | Most pages — lucide replacements map below                                                                                                                   |
| `@ant-design/plots` (Line/Column/Pie)                                                    | @ant-design/plots            | 4                | Settings/TokenUsage/TokenTypeChart.tsx, Settings/TokenUsage/ModelTrendChart.tsx, Settings/AgentStats/index.tsx                                               |
| `@ant-design/x-markdown` (XMarkdown, ComponentProps)                                     | @ant-design/x-markdown       | 2                | Agent/Workspace/FileEditor.tsx, MermaidCodeBlock/mermaidComponents.tsx                                                                                       |
| `@agentscope-ai/chat` (AgentScopeRuntimeWebUI, useChatAnywhere\*, Attachments, Markdown) | @agentscope-ai/chat          | ~15              | Chat/index.tsx, Chat/sessionApi, Chat/HostBubbles.tsx, ToolCards/shared/DefaultBlock.tsx, ToolCards/shared/MediaPreview.tsx                                  |
| `createGlobalStyle`                                                                      | antd-style                   | 1                | App.tsx:1 (single usage — trivial CSS reset `* { margin:0; box-sizing:border-box }`)                                                                         |
| `ConfigProvider` / `bailianTheme` / `bailianDarkTheme`                                   | @agentscope-ai/design        | 3                | App.tsx (main theme wiring), ToolCards/shared/MediaPreview.tsx                                                                                               |

**Lucide icon replacements for `@ant-design/icons`:** The top antd icons used are: `PlusOutlined` (Add/Plus), `SearchOutlined` (Search), `EditOutlined` (Pencil), `DeleteOutlined` (Trash2), `CopyOutlined` (Copy), `MoreOutlined` (MoreHorizontal), `DownloadOutlined` (Download), `UploadOutlined` (Upload), `SaveOutlined` (Save), `CloseOutlined` (X), `CheckOutlined` (Check), `SyncOutlined` (RefreshCw), `FilterOutlined` (Filter), `EyeOutlined`/`EyeInvisibleOutlined` (Eye/EyeOff), `MenuOutlined` (Menu/GripVertical), `LinkOutlined` (Link), `ReloadOutlined` (RotateCcw), `SettingOutlined` (Settings), `LoadingOutlined` (Loader2+animate-spin). Many lucide equivalents are already used in `ApprovalCard.tsx` (Shield, Check, X, Clock, Copy).

### 10.2 SSE / Event Streaming Contract

**Transport — how the stream is opened**

`console/src/pages/Chat/index.tsx` lines 1166–1238 show a `customFetch` function that POSTs to `GET_API_URL("/console/chat")` with:

```json
{
  "input": [...],            // last user message content parts
  "session_id": "...",       // window.currentSessionId
  "user_id": "...",          // window.currentUserId
  "channel": "...",          // window.currentChannel
  "stream": true,
  ...biz_params
}
```

Headers include `buildAuthHeaders()` (Bearer token from `src/api/authHeaders.ts`).

The raw `Response` is passed directly into `AgentScopeRuntimeWebUI` via `options.api.fetch`. The SDK library (`@agentscope-ai/chat`) owns SSE frame parsing internally; the host only provides a `responseParser` callback that receives individual parsed JSON chunks.

**Standard SSE endpoint per AgentScope v2 docs:**
`GET /sessions/{session_id}/stream?agent_id=<id>` with header `x-user-id: <id>` and `Accept: text/event-stream`. The stream replays buffered events on connect, then delivers live events. A 30-second heartbeat `:\n\n` comment frame is sent to keep proxies alive. The stream remains open across multiple runs on the same session.

**Event shapes (from docs/agentscope-v2/building-blocks/message-and-event.md)**

All events carry `{ id, created_at }` from `EventBase` plus a `reply_id` linking to the message, and a `type` discriminator (uppercase snake-case in TS, e.g. `"REPLY_START"`).

| Event type                 | Key fields                                                                        | UI rendering note                                                |
| -------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `ReplyStartEvent`          | `reply_id`, `session_id`, `name`, `role`                                          | Create new `AssistantMsg({ name, content: [], id: reply_id })`   |
| `TextBlockStartEvent`      | `reply_id`, `block_id`                                                            | Start new text bubble                                            |
| `TextBlockDeltaEvent`      | `reply_id`, `block_id`, `delta: str`                                              | Append `delta` to running text — primary incremental text stream |
| `TextBlockEndEvent`        | `reply_id`, `block_id`                                                            | Finalise text block                                              |
| `ThinkingBlockStartEvent`  | `reply_id`, `block_id`                                                            | Start collapsible thinking panel                                 |
| `ThinkingBlockDeltaEvent`  | `reply_id`, `block_id`, `delta: str`                                              | Append to thinking text                                          |
| `ThinkingBlockEndEvent`    | `reply_id`, `block_id`                                                            | Finalise thinking block                                          |
| `DataBlockStartEvent`      | `reply_id`, `block_id`, `media_type`                                              | Prepare image/audio/video receiver                               |
| `DataBlockDeltaEvent`      | `reply_id`, `block_id`, `data: str (base64)`, `media_type`                        | Accumulate base64 data                                           |
| `DataBlockEndEvent`        | `reply_id`, `block_id`                                                            | Render media block                                               |
| `ToolCallStartEvent`       | `reply_id`, `tool_call_id`, `tool_call_name`                                      | Open tool_call card (ToolCardShell)                              |
| `ToolCallDeltaEvent`       | `reply_id`, `tool_call_id`, `delta: str (JSON fragment)`                          | Stream tool input                                                |
| `ToolCallEndEvent`         | `reply_id`, `tool_call_id`                                                        | Finalise tool call input                                         |
| `ToolResultStartEvent`     | `reply_id`, `tool_call_id`, `tool_call_name`                                      | Open tool_result card                                            |
| `ToolResultTextDeltaEvent` | `reply_id`, `tool_call_id`, `delta: str`                                          | Stream tool output text                                          |
| `ToolResultDataDeltaEvent` | `reply_id`, `tool_call_id`, `block_id`, `media_type`, `data\|url`                 | Binary tool output                                               |
| `ToolResultEndEvent`       | `reply_id`, `tool_call_id`, `state: SUCCESS\|ERROR\|INTERRUPTED\|DENIED\|RUNNING` | Finalise tool result                                             |
| `RequireUserConfirmEvent`  | `reply_id`, `tool_calls: ToolCallBlock[]`                                         | Triggers `ApprovalCard` — sets tool call state to `ASKING`       |
| `ReplyEndEvent`            | `reply_id`, `session_id`                                                          | Mark message `finished_at`, hide loading indicator               |
| `HintBlockEvent`           | `reply_id`, `block_id`, `hint: str\|list`, `source: str\|null`                    | Out-of-band hint (scheduled task trigger, team message)          |
| `CustomEvent`              | `reply_id`, `name`, `value: dict`                                                 | Service signals (`tasks_context`, `team_updated`, etc.)          |
| `ModelCallStartEvent`      | `reply_id`, `model_name`                                                          | Optional loading indicator                                       |
| `ModelCallEndEvent`        | `reply_id`, `input_tokens`, `output_tokens`                                       | Token count display                                              |
| `ExceedMaxItersEvent`      | `reply_id`, `name`                                                                | Error state in bubble                                            |

**responseParser in Chat/index.tsx lines 1607–1625**: The host's `responseParser` receives each parsed JSON chunk. It checks:

- `payload.type === "rate_limited"` — shows banner with alternative models
- `payloadRequestsHistoryClear(payload)` (checks `metadata.clear_history === true`) — queues a message history wipe
- `payloadCompletesResponse(payload)` (checks `object === "response" && status === "completed"`) — fires the clear

All other payloads are returned as-is for the SDK to render. The host never directly processes text delta, thinking, or tool events — those are handled entirely inside `@agentscope-ai/chat`.

**Reconnect**: `options.api.reconnect` POSTs `{ reconnect: true, session_id, user_id, channel }` to `/console/chat`.

**Cancel**: `options.api.cancel` calls `chatApi.stopChat(chatId)` — POST `/console/chat/stop?chat_id=<id>`.

**File: `console/src/pages/Chat/sessionApi/index.ts`** — `SessionApi` class implements `IAgentScopeRuntimeWebUISessionAPI`. Key callbacks registered in Chat/index.tsx: `onSessionIdResolved`, `onSessionRemoved`, `onSessionSelected`, `onSessionCreated` — all update `react-router-dom` navigation.

**File: `console/src/api/types/chat.ts`** — `ChatStatus = "idle" | "running"`. `Message.content` is `unknown` (may be `string` or `ContentItem[]`). `ContentItem` types encountered in sessionApi: `text`, `image` (`image_url`), `audio` (`data`), `video` (`video_url`), `file` (`file_url`/`file_id`).

### 10.3 antd Table usages and Form usages (heavy migration targets)

**Table usages (antd `Table` + `ColumnsType`):**

| File                                                                 | Table source                       | ColumnsType target                     |
| -------------------------------------------------------------------- | ---------------------------------- | -------------------------------------- |
| `console/src/pages/Settings/Agents/components/AgentTable.tsx:1`      | `antd`                             | `ColumnsType<AgentSummary>` (line 71)  |
| `console/src/pages/Settings/Backups/list/BackupTable.tsx:11`         | `antd`                             | `ColumnsType<BackupMeta>` (line 86)    |
| `console/src/pages/Settings/Backups/restore/RestoreAgentTable.tsx:9` | `antd`                             | `TableColumnsType<AgentRow>` (line 93) |
| `console/src/pages/Settings/PluginManager/index.tsx:2`               | `antd`                             | inline columns                         |
| `console/src/pages/Control/Sessions/index.tsx:3`                     | `@agentscope-ai/design`            | `ColumnsType<Session>` via columns.tsx |
| `console/src/pages/Settings/TokenUsage/components/DataTables.tsx:1`  | `@agentscope-ai/design`            | inline columns                         |
| `console/src/pages/Control/CronJobs/components/columns.tsx:2`        | `ColumnsType` from `antd/es/table` | `ColumnsType<CronJob>` (line 50)       |
| `console/src/pages/Control/Sessions/components/columns.tsx:4`        | `ColumnsType` from `antd/es/table` | `ColumnsType<Session>` (line 26)       |

All `columns.tsx` files define `createColumns(handlers): ColumnsType<T>` factory functions. Migration path: replace `ColumnsType` with `@tanstack/react-table` `ColumnDef<T>` and render via shadcn `Table` + `useReactTable`.

**Form usages (heavy — 37 files):**

Top files with full antd Form:

- `console/src/pages/Login/index.tsx` — login form (email/password, Form + Form.Item)
- `console/src/pages/Settings/Agents/components/AgentModal.tsx` — agent create/edit Form
- `console/src/layouts/Sidebar.tsx` — rename session Form inside Modal
- `console/src/pages/Agent/Config/index.tsx` and `Agent/Config/components/**` (8 files) — agent config forms (LLM config, memory, rate limiter, retry, etc.)
- `console/src/pages/Agent/ACP/index.tsx` + `ACPDrawer.tsx` — ACP form
- `console/src/pages/Agent/Skills/useSkillsPage.tsx` + `SkillDrawer.tsx` — skill form
- `console/src/pages/Control/CronJobs/components/JobDrawer.tsx` — cron job form with DatePicker/TimePicker
- `console/src/pages/Control/Channels/components/ChannelDrawer.tsx` + `AccessControlDrawer.tsx` — channel forms
- `console/src/pages/Control/Sessions/components/SessionDrawer.tsx` — session form
- `console/src/pages/Settings/Models/components/modals/ProviderConfigModal.tsx` + `RemoteModelManageModal.tsx` + `CustomProviderModal.tsx` — model provider forms
- `console/src/pages/Settings/Security/useSecurityPage.ts` + `ToolGuardTab.tsx` + `RuleModal.tsx` — security forms
- `console/src/pages/Settings/PluginManager/hooks/useInstallModal.ts` + `InstallPluginModal.tsx` — plugin install form
- `console/src/pages/Inbox/components/CreateHarvestModal.tsx` — harvest creation form

Migration: all use `Form.useForm()` / `Form.Item` validation pattern. Replace with `react-hook-form` + `zod` + shadcn `Form` (FormField, FormItem, FormControl, FormMessage).

### 10.4 antd-style `createStyles` / `createGlobalStyle` usages

| File                       | Pattern                               | Notes                                                                                                                                                                    |
| -------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `console/src/App.tsx:1,56` | `createGlobalStyle` from `antd-style` | Single usage: CSS reset (`* { margin:0; box-sizing:border-box }`). **Trivial** — remove `antd-style` dep, move content to `src/index.css` Tailwind layer or as bare CSS. |

No `createStyles` usages found in the codebase. The only `antd-style` usage is this single `createGlobalStyle` in `App.tsx`. All component-level styles use `.module.less` files.

### 10.5 ApprovalCard + ApprovalContext flow

**Files involved:**

- `console/src/contexts/ApprovalContext.tsx` — context provider
- `console/src/components/ApprovalCard/ApprovalCard.tsx` — floating overlay card (used in Chat)
- `console/src/components/ApprovalCard/ApprovalCard.module.less` — styles
- `console/src/pages/Inbox/components/ApprovalCard.tsx` — Inbox variant (simpler)

**ApprovalContext (`ApprovalContext.tsx`):**

```
interface ApprovalContextValue {
  approvals: PendingApproval[];          // from api/modules/console
  setApprovals: Dispatch<SetStateAction<PendingApproval[]>>;
}
```

`useApprovalContext()` throws if called outside `ApprovalProvider`. `ApprovalProvider` wraps the whole app in `App.tsx`. Approvals are polled from the backend (via `console` module) and stored here; `Chat/index.tsx` subscribes and filters by `root_session_id`.

**`ApprovalCard` props (components/ApprovalCard/ApprovalCard.tsx:11-29):**

```typescript
interface ApprovalCardProps {
  requestId: string;
  toolName: string;
  severity: string; // "critical"|"high"|"medium"|"low"
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  createdAt: number; // unix seconds
  timeoutSeconds: number; // countdown timer
  agentId: string;
  ownerAgentId?: string;
  showInboxAgentContext?: boolean; // true in Inbox, false in Chat overlay
  sessionId?: string;
  rootSessionId?: string;
  onApprove: (requestId: string) => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel?: () => void; // only in Chat overlay — calls chatApi.stopChat
  onAcknowledge?: (requestId: string) => Promise<void>; // only in Inbox (timed-out)
}
```

**Internal states:**

- `loading: "approve" | "deny" | "acknowledge" | null` — button loading state
- `remaining: number` — countdown (seconds) from `timeoutSeconds - elapsed`; reaches 0 → `isTimedOut`
- `copiedField: string | null` — copy-to-clipboard feedback for summary/params

**Rendering logic:**

- Header: Shield icon + "Security Approval Required" title + countdown timer (MM:SS)
- Agent context row (Inbox only): Owner Agent tag + Executing Agent tag (cross-session)
- Info rows: Tool (code), Severity (Badge/Tag with color: error/warning/default), Findings count
- Cross-session source tag (Chat overlay when `sessionId !== rootSessionId`)
- `findingsSummary` in a summary box with copy button
- `toolParams` in a `<details>/<summary>` collapsible code block with copy button
- Actions:
  - **Normal state**: [Cancel Task?] [Deny (danger)] [Approve (primary)]
  - **Timed-out** (`isTimedOut && showInboxAgentContext`): "Timed out, auto denied" message + [Got It] button

**Severity → color mapping:**
`critical/high → "error"` | `medium → "warning"` | `low/other → "default"`

**Chat integration** (`Chat/index.tsx`): Cards are rendered as `position: fixed, bottom: 80, right: 24` overlays stacked by `requestId`. Exit animation via CSS class `approvalCardExit`. `handleApprove` / `handleDeny` call `commandsApi.sendApprovalCommand("approve"|"deny", requestId, rootSessionId)`.

**Inbox variant** (`pages/Inbox/components/ApprovalCard.tsx`): Simpler — receives `ApprovalItem` (type: `tool_call|config_change|file_access`, priority: `low|normal|high|urgent`), shows type icon + priority tag, no countdown, no params expansion.

**shadcn migration target:** Replace `Card` wrapper with shadcn `Card`. Replace `Tag` with `Badge`. Replace `Button` with shadcn `Button`. The overlay positioning and animation stay as CSS/Tailwind. The `<details>` code block is pure HTML — keep it. Countdown timer is pure JS — keep it. No need for Dialog/AlertDialog here; the card IS the approval surface (not a modal). However, `Popconfirm` usages elsewhere in the app (AgentTable, BackupTable) should become `AlertDialog`.

### 10.6 Summary: top-priority shadcn components to generate (Phase 0/1)

Ordered by breadth of usage:

1. **Button** (`ui/button`) — ~60 sites; highest ROI. Map `type="primary"→default variant`, `danger→destructive`, `type="link"→link`, `type="text"→ghost`, `loading` → spinner + disabled.
2. **Input** + **Textarea** — ~25 sites; needed for Login, Sidebar rename, all Form drawers.
3. **Select** (`ui/select`) — ~17 sites; also need `Command`/combobox for searchable/multi usage (AgentSelector, Models).
4. **Card** (`ui/card`) — ~22 sites; ApprovalCard, Agent/Config cards, Inbox cards.
5. **Badge** (`ui/badge`) — replaces antd `Tag` (~18 sites) and antd `Badge` (~6 sites).
6. **Tooltip** (`ui/tooltip`) — ~20 sites; wrap root in `TooltipProvider`.
7. **Dialog** (`ui/dialog`) — replaces antd `Modal` (~30 sites). Confirm variants → `AlertDialog`.
8. **Sheet** (`ui/sheet`) — replaces antd `Drawer` (~12 sites); Chat sidebar, Settings drawers.
9. **Form** + react-hook-form + zod — ~37 files with Form.Item; Login, Agent/Config, all drawers.
10. **Table** (`ui/table`) + `@tanstack/react-table` — 8 Table files + 2 columns.tsx; CronJobs, Sessions, Agents, Backups.
11. **Tabs** (`ui/tabs`) — ~9 sites; Agent/MCP, Agent/Config, Settings/Security.
12. **Switch** (`ui/switch`) — ~8 sites; agent toggles, workspace file toggle.
13. **DropdownMenu** (`ui/dropdown-menu`) — ~8 sites; Header, ThemeToggleButton, LanguageSwitcher, CronJobs columns.
14. **Skeleton** + Loader spinner (lucide `Loader2` + `animate-spin`) — ~15 Spin sites.
15. **Accordion** (`ui/accordion`) — replaces antd `Collapse` (tool cards).
16. **Slider** (`ui/slider`) — 1 site: `Agent/Config/SliderWithValue.tsx`.
17. **Progress** (`ui/progress`) — ~5 sites; Backups, tauri loading.
18. **Checkbox** / **RadioGroup** — ~5 each; Backups scope form, Environments, Skills.
19. **Avatar** (`ui/avatar`) — 1 site: `Inbox/PushMessageCard.tsx`.
20. **Sonner** `<Toaster/>` + adapter shim — replaces all `message.success/error/warning` calls (~20 call sites).

Not blocking Phase 0/1: `Calendar`+`Popover` (DatePicker replacement, Phase 2), `recharts`/shadcn chart (replaces `@ant-design/plots`, Phase 2), `Pagination` (1 site, Phase 2), `Progress` (Phase 2).

---

## Review — Phase 0/1

Reviewed by: code-review agent, 2026-06-11.
Scope: all files listed in the Phase 0 + Phase 1 progress log entries, plus supporting hooks and CSS modules.

---

### Blocker

**B-1 — Wrong dark variant in multiple Phase 1 files (dark mode broken for those elements)**
Files and lines:

- `src/layouts/Header.tsx:58` — `dark:hover:bg-white/10` (inside `UpdateCodeBlock`)
- `src/components/ApprovalCard/ApprovalCard.tsx:181,193,239` — `dark:bg-green-900/30 dark:text-green-400`, `dark:bg-blue-900/30 dark:text-blue-400`
- `src/pages/Inbox/components/ApprovalCard.tsx:29,30` — `dark:bg-blue-900/30`, `dark:bg-orange-900/30`
- `src/pages/Inbox/components/HarvestCard.tsx:101` — `dark:bg-green-900/30`
- `src/pages/Inbox/components/CreateHarvestModal.tsx:132` — `dark:bg-orange-950/20`
- `src/pages/Inbox/components/PushMessageCard.tsx:129` — `dark:bg-orange-900/30`
- `src/pages/Inbox/index.tsx:603` — `dark:bg-green-900/30`

The project uses `@custom-variant dark (&:is(.dark-mode *))` (toggling `.dark-mode` on `<html>`). The default Tailwind `dark:` variant targets `@media (prefers-color-scheme: dark)` or the `.dark` class — neither of which is set by `ThemeContext`. All of the `dark:` utility classes above will never activate.
Fix: replace every `dark:` with `dark-mode:` in the migrated files (or use CSS-variable tokens from `index.css` so no per-element dark override is needed).

---

**B-2 — `Dialog` in `Header.tsx` (update modal) has no `DialogTitle` or `DialogDescription`**
File: `src/layouts/Header.tsx:263-349`
The `<Dialog>` wrapping the update modal renders `<DialogContent>` but imports only `DialogContent` and `DialogFooter` — `DialogTitle` and `DialogDescription` are not imported and not rendered. Radix UI emits a console warning and screen readers have no announced name/description for this modal.
Fix: import `DialogHeader`, `DialogTitle`, and `DialogDescription`; add a title (e.g. `{t("sidebar.updateModal.title", ...)}`) and a brief description, or add `aria-describedby={undefined}` to silence the warning if a description is genuinely not wanted.

---

**B-3 — `Dialog` in `CodingModeToggle/index.tsx` has no `DialogDescription`**
File: `src/components/CodingModeToggle/index.tsx:147-176`
`DialogTitle` is present but `DialogDescription` is absent. Radix will warn at runtime and VoiceOver/NVDA will not announce a description.
Fix: add `<DialogDescription>` inside `<DialogHeader>` with the experimental warning text, or at minimum add `aria-describedby={undefined}` to suppress the console error.

---

**B-4 — `Dialog` in `Sidebar.tsx` (account modal) has no `DialogDescription`**
File: `src/layouts/Sidebar.tsx:511-613`
`DialogTitle` is present; `DialogDescription` is absent.
Fix: same pattern — add a brief `<DialogDescription>` (e.g. the i18n key `"account.description"`) or suppress with `aria-describedby={undefined}`.

---

### Should-Fix

**S-1 — `src/pages/Inbox/index.tsx` still imports and heavily uses `index.module.less`**
File: `src/pages/Inbox/index.tsx:68`, then `styles.*` on ~35 lines.
The Less module (`src/pages/Inbox/index.module.less`) contains antd-specific `:global(.ant-tabs-nav)`, `:global(.ant-descriptions-item-label)`, `:global(.ant-collapse-*)` selectors that will never match now that the Inbox page uses shadcn Tabs/Accordion. The module also hardcodes `background: #fff` in multiple places (`.inboxPage`, `.traceContainer`, `.traceUserMessage`, etc.) without dark-mode equivalents except inside `:global(.dark-mode)` overrides that do exist but are incomplete. The partial migration leaves this page only half-themed.
Fix: migrate the remaining layout and trace-viewer styles to Tailwind utility classes and remove the Less module dependency in a follow-up slice within Phase 2. At minimum, mark these antd-targeted rules as dead code so they are cleaned up in Phase 3.

---

**S-2 — `src/pages/Inbox/components/PushMessageCard.tsx` still imports `PushMessageCard.module.less`**
File: `src/pages/Inbox/components/PushMessageCard.tsx:29`
Residual Less module import; the component itself uses shadcn/Tailwind but still consumes module classes for `.messageCard` and `.unread`. Not critical but inconsistent with the migration goal.
Fix: convert the two remaining Less class usages to Tailwind utilities and remove the import.

---

**S-3 — `createGlobalStyle` from `antd-style` still present in `App.tsx`**
File: `src/App.tsx:1,58-63,177`
The `GlobalStyle` component sets only `* { margin:0; box-sizing:border-box }`. The brief explicitly identifies this as a trivial removal. The `@layer base` block in `index.css` already applies `box-sizing` via Tailwind preflight; the `margin:0` is also covered. Keeping `antd-style` imported prolongs its dependency in the bundle.
Fix: remove `createGlobalStyle` import and `<GlobalStyle />` usage; move `margin: 0` to `src/index.css` `@layer base` if it is actually needed (preflight handles it).

---

**S-4 — `Toaster` in `App.tsx` has no `theme` prop wired to `isDark`**
File: `src/App.tsx:195`
`<Toaster />` is rendered without a `theme` prop. Sonner defaults to the system colour scheme, not to `ThemeContext`'s `.dark-mode` toggle. When a user switches to dark mode via the toggle (not the OS setting) the Toaster will remain light.
Fix: pass `theme={isDark ? "dark" : "light"}` to `<Toaster />` (must be done inside `AppInner` where `isDark` is available).

---

**S-5 — `console.log` debug statements left in production `ApprovalCard`**
File: `src/components/ApprovalCard/ApprovalCard.tsx:111,115,325`
Three `console.log` calls were added during development and not removed. They will appear in production builds.
Fix: remove all three `console.log` calls.

---

**S-6 — `handleDeny` has no `catch` — errors are silently swallowed**
File: `src/components/ApprovalCard/ApprovalCard.tsx:123-130`
`handleApprove` logs errors in a `catch`; `handleDeny` (line 123) and `handleAcknowledge` (line 132) use only `try/finally` with no `catch`, so API errors go unnoticed by the user.
Fix: add `catch` blocks that call `toast.error(...)` (or rethrow) in `handleDeny` and `handleAcknowledge`, matching `handleApprove`'s error logging pattern.

---

**S-7 — `isDark` imported but suppressed with `void isDark` in `Sidebar.tsx`**
File: `src/layouts/Sidebar.tsx:19,166,177`
`isDark` is destructured from `useTheme()` and immediately voided. The sidebar renders dark-mode styles exclusively via `dark-mode:` Tailwind variants (correctly), so the value is genuinely unused. The suppression pattern is unusual; just remove the destructure from the hook call.
Fix: change `const { isDark } = useTheme()` to remove `isDark`; keep only the properties that are used, or remove the `useTheme()` call entirely since `isDark` is the only import from it.

---

**S-8 — `UpdateCodeBlock` button in `Header.tsx` has no accessible name**
File: `src/layouts/Header.tsx:56-65`
The copy button has a `title="Copy"` but no `aria-label`. Screen readers may announce the `title` attribute but it is inconsistently supported. The `ThemeToggleButton` uses `<span className="sr-only">` correctly; the same pattern should be applied here.
Fix: add `<span className="sr-only">Copy</span>` inside the button (matching the pattern used in `ThemeToggleButton` and `LanguageSwitcher`).

---

**S-9 — Hardcoded `background-image` path uses `/public/` prefix (wrong in production)**
File: `src/layouts/Header.tsx:269`
`url('/public/qwenpawBack.png')` — Vite serves `public/` files at the root, so the correct runtime path is `/qwenpawBack.png`, not `/public/qwenpawBack.png`. In development with `vite dev` both may resolve, but the production build will produce a 404.
Fix: change to `url('/qwenpawBack.png')`.

---

### Nice-to-Have

**N-1 — `Inbox/index.tsx` SimplePagination uses hardcoded English strings**
File: `src/pages/Inbox/index.tsx:108,127`
`"Prev"` and `"Next"` labels are not wrapped in `t(...)`. All other user-visible strings in the file go through i18n.
Fix: replace with `{t("common.prev")}` / `{t("common.next")}` (add the keys if missing) for consistency.

---

**N-2 — `vite.config.ts` `manualChunks` still buckets `antd`/`@ant-design`/`@agentscope-ai` into `ui-vendor`**
File: `console/vite.config.ts:143-149`
This is intentional during the transition (per the brief's coexistence rule), but the shadcn/Radix/Tailwind stack is not chunked at all — every shadcn component lands in the main chunk. As Phase 1+ grows, consider adding a `shadcn-vendor` entry for `@radix-ui/*`, `class-variance-authority`, `tailwind-merge`, `clsx`, `sonner`.
Fix: add to `manualChunks` when Phase 3 cleanup removes antd, or sooner if bundle analysis shows size regression.

---

**N-3 — `LanguageSwitcher` lists `pt-BR` but the i18n `dayjsLocaleMap` in `App.tsx` does not include it**
File: `src/components/LanguageSwitcher/index.tsx:30` / `src/App.tsx:50-56`
`dayjsLocaleMap` maps `zh`, `en`, `ja`, `ru`, `id` — `pt-BR` is absent. Selecting Português will fall back to `"en"` for dayjs locale. The pt-BR locale file exists in `src/locales/pt-BR.json`. This is a pre-existing gap rather than a regression, but Phase 1 surfaces it by adding pt-BR to the switcher.
Fix: add `"pt-BR": "pt-br"` (and import `"dayjs/locale/pt-br"`) to `App.tsx`; also add `pt: "pt-br"` for `resolvedLanguage` short-code fallback.

---

**N-4 — `Inbox/index.tsx` mixes `styles.inboxPage` (Less) with Tailwind for identical layout concerns**
File: `src/pages/Inbox/index.tsx:337,340`
`.inboxPage` sets `height:100%; display:flex; flex-direction:column; overflow:hidden` — identical to the Tailwind pattern used in `MainLayout` (`flex flex-col h-screen overflow-hidden`). The dual-source approach makes future Less removal harder.
Fix (Phase 2 cleanup): replace `.inboxPage` and `.pageContent` with Tailwind equivalents when the rest of the Less module is migrated.

---

**Summary table**

| ID  | Severity     | File                                                              | One-line fix                                                                                   |
| --- | ------------ | ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| B-1 | blocker      | Multiple (see above)                                              | Replace every `dark:` with `dark-mode:` in all Phase 1 migrated files                          |
| B-2 | blocker      | `src/layouts/Header.tsx:263`                                      | Add `DialogTitle` + `DialogDescription` to the update modal                                    |
| B-3 | blocker      | `src/components/CodingModeToggle/index.tsx:147`                   | Add `DialogDescription` to experimental confirm dialog                                         |
| B-4 | blocker      | `src/layouts/Sidebar.tsx:511`                                     | Add `DialogDescription` to the account update dialog                                           |
| S-1 | should-fix   | `src/pages/Inbox/index.tsx:68`                                    | Schedule Less module removal in Phase 2; mark antd CSS selectors as dead                       |
| S-2 | should-fix   | `src/pages/Inbox/components/PushMessageCard.tsx:29`               | Convert last 2 Less classes to Tailwind; remove Less import                                    |
| S-3 | should-fix   | `src/App.tsx:1`                                                   | Remove `createGlobalStyle` / `antd-style` import; styles already covered by Tailwind preflight |
| S-4 | should-fix   | `src/App.tsx:195`                                                 | Pass `theme={isDark ? "dark" : "light"}` to `<Toaster />`                                      |
| S-5 | should-fix   | `src/components/ApprovalCard/ApprovalCard.tsx:111,115,325`        | Remove debug `console.log` calls                                                               |
| S-6 | should-fix   | `src/components/ApprovalCard/ApprovalCard.tsx:123,132`            | Add `catch` to `handleDeny` and `handleAcknowledge` with `toast.error`                         |
| S-7 | should-fix   | `src/layouts/Sidebar.tsx:166,177`                                 | Remove unused `isDark` destructure                                                             |
| S-8 | should-fix   | `src/layouts/Header.tsx:56`                                       | Add `aria-label` or `<span className="sr-only">Copy</span>` to copy button                     |
| S-9 | should-fix   | `src/layouts/Header.tsx:269`                                      | Fix image path `/public/qwenpawBack.png` → `/qwenpawBack.png`                                  |
| N-1 | nice-to-have | `src/pages/Inbox/index.tsx:108,127`                               | Wrap "Prev"/"Next" in `t()`                                                                    |
| N-2 | nice-to-have | `console/vite.config.ts:143`                                      | Add `shadcn-vendor` chunk for `@radix-ui/*`                                                    |
| N-3 | nice-to-have | `src/App.tsx:50` + `src/components/LanguageSwitcher/index.tsx:30` | Add `pt-BR` to `dayjsLocaleMap` + import dayjs pt-br locale                                    |
| N-4 | nice-to-have | `src/pages/Inbox/index.tsx:337`                                   | Replace `.inboxPage`/`.pageContent` Less classes with Tailwind equivalents                     |

- Review fixes applied — 2026-06-11 (CODER, Phase 0/1 review): Applied all real findings from "Review — Phase 0/1". B-1 skipped (confirmed false positive — `@custom-variant dark (&:is(.dark-mode *))` makes `dark:` correct). Changes: B-2 `Header.tsx` update modal → added `DialogHeader`/`DialogTitle`/`DialogDescription` (sr-only); B-3 `CodingModeToggle/index.tsx` → added `DialogDescription` (sr-only); B-4 `Sidebar.tsx` account dialog → added `DialogDescription` (sr-only); S-3 `App.tsx` → removed `createGlobalStyle` import + `<GlobalStyle/>` + `antd-style` dep usage; S-4 `App.tsx` → `<Toaster theme={isDark ? "dark" : "light"} />`; S-5 `ApprovalCard.tsx` → removed 3 `console.log` calls; S-6 `ApprovalCard.tsx` → added `catch (err) { toast.error(...) }` to `handleDeny` + `handleAcknowledge`; S-7 `Sidebar.tsx` → removed unused `isDark` destructure + `void isDark` + `useTheme` import; S-8 `Header.tsx` copy button → added `aria-label="Copy"` + `<span className="sr-only">Copy</span>`; S-9 `Header.tsx` → fixed bg image path `/public/qwenpawBack.png` → `/qwenpawBack.png`; S-1/S-2/N-4 `pages/Inbox/index.tsx` + `pages/Inbox/components/PushMessageCard.tsx` → converted all `styles.*` Less module usage to Tailwind classes, removed both Less imports, deleted orphan `index.module.less` + `PushMessageCard.module.less`; N-3 `App.tsx` → added `pt: "pt-br"` + `"pt-BR": "pt-br"` to `dayjsLocaleMap` + `import "dayjs/locale/pt-br"`. Verification: zero tsc errors in touched files; `npx vite build` SUCCESS (34.24s).
- Phase 2 — Chat core done — 2026-06-11: Migrated all files in `pages/Chat/**` and `components/Chat/**` (ToolCards). antd/`@ant-design/icons`/`antd-style`/`@agentscope-ai/design`/`@agentscope-ai/icons` = ZERO in slice. `@agentscope-ai/chat` intentionally retained (Phase 3 cleanup) in: `pages/Chat/index.tsx` (AgentScopeRuntimeWebUI, useChatAnywhereInput), `pages/Chat/HostBubbles.tsx` (VendorRequestCard/VendorResponseCard), `pages/Chat/sessionApi/index.ts` (IAgentScopeRuntimeWebUISessionAPI), `pages/Chat/components/ChatSessionDrawer/index.tsx` (useChatAnywhereSessionsState, useChatAnywhereSessions), `pages/Chat/components/ChatActionGroup/index.tsx` (useChatAnywhereSessionsState), `pages/Chat/components/ChatHeaderTitle/index.tsx` (useChatAnywhereSessionsState), `pages/Chat/components/ChatSearchPanel/index.tsx` (useChatAnywhereSessions), `pages/Chat/components/ChatSessionInitializer/index.tsx` (IAgentScopeRuntimeWebUISession), `components/Chat/ToolCards/adapters/v1Adapter.tsx`, `components/Chat/ToolCards/registerBuiltinCards.ts`. Key migrations: Modal→Dialog (Chat/index model prompt + ModelSelector nav confirm + OAuthConfirmModal), Drawer→Sheet (ChatSessionDrawer + ChatSearchPanel), antd Tooltip→shadcn Tooltip everywhere, message/notification→sonner toast, antd Input/Button→native input + shadcn Button, all 22 tool-card `@ant-design/icons` → lucide-react (FilePlus/Globe/MessageSquare/RefreshCw/Webhook/Monitor/Pencil/Clock/FolderOpen/Search/Users/Zap/Lightbulb/FileText/Send/Terminal/Rocket/BarChart2/ImageIcon/Film/FilePlus), `@agentscope-ai/chat Markdown`→ReactMarkdown+remarkGfm, `@agentscope-ai/design Audio/Video`→native html5. `npx tsc -b` — PASS (zero errors in slice). grep antd/`@ant-design`/`antd-style` in slice = ZERO.
- Phase 3 — cosmetic cleanup done — 2026-06-11 (CODER): Replaced all remaining `@agentscope-ai/icons` and `@ant-design/x-markdown` usages in the four target files; replaced antd `Progress` in BackendLoadingPage; added `shadcn-vendor` chunk. Files changed: `src/components/LanguageSwitcher/index.tsx` (Spark* icons → emoji flags + lucide Globe), `src/layouts/Sidebar.tsx` (6 Spark* icons → MessageSquare/Minimize2/UserSearch/PanelLeftOpen/PanelLeftClose/Mail), `src/layouts/registry/builtinMenu.ts` (22 Spark* icons → lucide equivalents), `src/pages/Agent/Workspace/components/FileEditor.tsx` (XMarkdown → ReactMarkdown+remarkGfm, `as never` cast removed), `src/components/MermaidCodeBlock/mermaidComponents.tsx` (updated to react-markdown v10 `code` API), `src/tauri/BackendLoadingPage.tsx` (antd Progress → inline SVG CircularProgress), `vite.config.ts` (added `shadcn-vendor` bucket for @radix-ui/*/clsx/tailwind-merge/cva/sonner/lucide-react/motion). Verification: `npx tsc -b` PASS (zero errors); `npm run build` SUCCESS (58.60s); `shadcn-vendor` chunk present (268 kB); grep `@agentscope-ai/icons` in 3 target files = ZERO; grep `@ant-design/x-markdown` in FileEditor = ZERO; grep `from "antd"` in BackendLoadingPage = ZERO.
- Phase 3 — tests updated — 2026-06-11 (TESTER): Fixed 51 tests broken by the antd→shadcn migration across 9 test files. Final run: **479 passed / 0 failed** (46 test files). Root causes: (1) `renderWithProviders` in `src/test/common_setup.tsx` lacked `TooltipProvider` — shadcn `Tooltip` requires it, causing crashes in ModelSelector, ChatActionGroup, ChatSessionDrawer, ChatHeaderTitle, AgentSelector tests; (2) icon-selector tests used `[data-icon="Spark*"]` antd/`@agentscope-ai/icons` attributes — replaced with lucide CSS class selectors (`.lucide-sun`, `.lucide-moon`, `.lucide-pencil`, `.lucide-trash-2`, `.lucide-chevron-right`, `.lucide-history`, `.lucide-message-square-plus`) or `svg` queries; (3) `MarkdownCopy.test.tsx` mocked `@ant-design/x-markdown` XMarkdown — source now uses `ReactMarkdown`, mock updated to `react-markdown`; (4) `LanguageSwitcher.test.tsx` mocked `@agentscope-ai/design` Dropdown — source now uses shadcn DropdownMenu (requires click-to-open), test rewritten with `userEvent` + `waitFor`; (5) `AgentSelector.test.tsx` checked `role="combobox"` from antd `Select` — source now uses Popover+button, updated to `getByRole("button", { name: /agent\.selectAgent/ })`; (6) `ModelSelector.test.tsx` partial lucide mock missing `ChevronUp`/`AlertTriangle`/`Link`/`Settings` icons added after migration; (7) `agent.test.ts` expected `/agent/process` endpoint which was migrated to `/console/chat`. No real source regressions found — all failures were test-side assertions against antd DOM artifacts.
- Phase 2 — Settings pages done — 2026-06-11: Migrated all files under `pages/Settings/**`. Key changes: `Security/*` (RuleModal, RuleTable, ToolGuardTab, FileGuardSection, AllowNoAuthHostsTab, SkillScannerSection, ShellEvasionSection, useSecurityPage, PreviewModal, index) — antd Form/Table/Switch/Select/Tabs/Collapse/Popconfirm/Modal.confirm → shadcn + custom TagInput + AlertDialog + Accordion. `SkillPool/*` (PoolSkillCard, PoolSkillListItem, SkillPoolListItem, BroadcastModal, ImportBuiltinModal, PoolSkillDrawer, useSkillPool, index) — antd Modal.confirm (×4) → confirmOverwrite Promise pattern + AlertDialog; antd Form.useForm → useState object with resetFields/setFieldsValue/validateFields API. `TokenUsage/*` (LoadingState, SummaryCards, ModelTrendChart, TokenTypeChart, DataTables, index, hooks/useModelTrendConfig, hooks/useTokenTypeConfig) — `@ant-design/plots` Line → recharts ResponsiveContainer/LineChart + pivoted data; antd DatePicker.RangePicker → native `<input type="date">`; antd Card/Table → shadcn. `AgentStats/index.tsx` — `@ant-design/plots` Column/Pie → recharts BarChart/PieChart; antd Spin/Tooltip/DatePicker/Card/Empty/Button → shadcn+lucide; TrendCard/PieCard subcomponents encapsulate recharts. `Agents/components/AgentTable.tsx` — antd Table/Popconfirm/Button/Tag/Tooltip → shadcn Table + AlertDialog (single confirm state); DnD kept via @dnd-kit. `Agents/components/SortableAgentRow.tsx` — antd `<tr>` → shadcn TableRow; uses `id` prop instead of `data-row-key`. `Agents/components/AgentModal.tsx` — antd Modal/Form.useForm/Select/Input/Spin/Empty → shadcn Dialog + `useAgentForm()` hook (useState-backed formRef with getValues/setValues/resetFields/validateFields API). `Agents/index.tsx` — antd Form.useForm/Card/Button/PlusOutlined → shadcn + lucide. `npx tsc -b` — PASS (zero errors). grep antd/`@ant-design`/`@agentscope-ai` in Settings slice = ZERO.

---

## 11. Final state & remaining legacy (intentional)

This section documents what antd-family packages remain in the app and WHY they must stay. Agents must NOT remove these.

### antd — kept for the plugin host and chat SDK context

- **`antd` remains in `package.json`** — it is a deliberate runtime dependency.
- **`src/plugins/hostExternals.ts`** and **`src/plugins/hostSdk/`** expose `antd` and `@ant-design/icons` as shared externals to dynamically-loaded plugins. Removing antd would break every plugin that renders antd components.
- **`src/App.tsx`** keeps `ConfigProvider` (from `@agentscope-ai/design`) and the `bailianTheme`/`bailianDarkTheme` wrappers. The embedded `@agentscope-ai/chat` SDK and all plugins rely on antd's `ConfigProvider`/`theme` React context being present in the tree. Removing it would silently break chat rendering and plugin theming.
- **`antd/locale/*`** imports in `App.tsx` supply the antd locale for any remaining antd components rendered inside plugins.

### @agentscope-ai/chat — kept as the chat engine SDK

- **`src/pages/Chat/index.tsx`** — `AgentScopeRuntimeWebUI` is the SSE-backed chat runtime; `useChatAnywhereInput` provides the send/reconnect/cancel interface.
- **`src/pages/Chat/HostBubbles.tsx`** — `VendorRequestCard`/`VendorResponseCard` render SDK-owned message frames.
- **`src/pages/Chat/sessionApi/`**, `ChatSessionDrawer`, `ChatActionGroup`, `ChatHeaderTitle`, `ChatSearchPanel`, `ChatSessionInitializer` — all rely on `useChatAnywhereSessions*` / `IAgentScopeRuntimeWebUISession*` from the SDK.
- **`src/components/Chat/ToolCards/`** — tool card adapters and the built-in card registry integrate with the SDK's event model.
- Replacing the SDK is a future major milestone (post-Phase 3), not in scope for this cleanup.

### vite.config.ts `ui-vendor` chunk

The `ui-vendor` manualChunk continues to bundle `antd`/`@ant-design`/`@agentscope-ai` together. This is intentional: it keeps the plugin-host surface isolated and avoids circular-dependency issues between antd and the SDK.
