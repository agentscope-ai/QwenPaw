---
name: theme-token-check
description: Background knowledge of the Console design system (shadcn/ui + Tailwind v4, AionUi tokens). Apply whenever writing or reviewing console/ UI so colors, dark mode, radius, and component choices stay consistent. Claude-invoked only.
user-invocable: false
---

# Console Theme & Token Rules

Reference knowledge for any work under `console/`. The authoritative, longer
version lives in `console/MIGRATION_SHADCN.md` — consult it for the antd→shadcn map
and migration history. This skill is the quick checklist to apply while coding.

## Design language (AionUi-inspired)

- Canvas: warm off-white (light) / deep navy-ink `#13111c` (dark).
- Ink foreground; **monochrome ink is the primary** (black pill buttons). No orange
  chrome — orange was removed during the AionUi re-theme.
- Soft, layered violet-tinted elevation (`shadow-aion`, `shadow-aion-sm`).
- Generous rounding: cards `rounded-2xl`, controls `rounded-xl`, buttons pill
  (`rounded-full`). Typography: Inter, tight heading tracking.

## Tokens (use these classes — never hardcode colors)

`bg-background` / `text-foreground` · `bg-card` / `text-card-foreground` ·
`bg-popover` · `bg-primary` / `text-primary-foreground` · `bg-secondary` /
`text-secondary-foreground` · `bg-muted` / `text-muted-foreground` · `bg-accent`
/ `text-accent-foreground` · `bg-destructive` · `border-border` · `bg-input` ·
`ring-ring` · `bg-sidebar` / `text-sidebar-foreground` / `bg-sidebar-accent` /
`border-sidebar-border` · optional accent `bg-brand` · utilities `shadow-aion`,
`shadow-aion-sm`. All are defined in `console/src/index.css` (`:root` + `.dark-mode`).

## Dark mode

- Toggled by the `.dark-mode` class on `<html>` (managed by
  `console/src/contexts/ThemeContext.tsx`).
- Registered Tailwind variants: **`dark:`** and **`dark-mode:`** (both map to
  `.dark-mode` via `@custom-variant`). Any other prefix will NOT theme.
- **Prefer tokens** (they theme automatically) over paired
  `bg-[#light] dark:bg-[#dark]` literals.

## Component choices

- Icons → `lucide-react`. Toasts → `sonner`. Forms → `react-hook-form` + `zod` +
  `@/components/ui/form`. Tables → `@/components/ui/table` (+ `@tanstack/react-table`
  if sorting/paging). Dialogs/Sheets/Dropdowns/Tabs/etc. → `@/components/ui/*`.
- Always merge `className` with `cn()` from `@/lib/utils`.
- Do NOT import `antd`/`@ant-design/*`/`antd-style` in pages/layouts/components.
  Intentional legacy: `@agentscope-ai/chat` (chat engine) and
  `plugins/hostExternals.ts` (antd for the plugin host).

## Accessibility (non-negotiable)

- `Dialog`/`Sheet`/`AlertDialog` content needs `*Title` + `*Description`
  (use `sr-only` when hidden).
- Icon-only buttons need `aria-label`; inputs need an associated `Label`.

## Quick self-check before finishing

```bash
# hardcoded colors outside the ui kit (should be ~0 for new work)
grep -rnoE "#[0-9a-fA-F]{6}|rgba?\(" console/src --include=*.tsx | grep -v "/ui/"
# residual antd in app UI (must be 0)
grep -rlE "from \"(antd|@ant-design/icons|antd-style)\"" console/src/{pages,layouts,components} | grep -v "/ui/"
cd console && npx tsc -b
```
