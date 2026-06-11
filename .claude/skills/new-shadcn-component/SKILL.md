---
name: new-shadcn-component
description: Scaffold a new Console UI component following the shadcn/ui + Tailwind v4 design system (AionUi tokens). Invoke with /new-shadcn-component <ComponentName> [description].
disable-model-invocation: true
---

# New shadcn Component

Scaffold a new component for the QwenPaw **Console** (`console/`) that follows the
project's design system. Read `console/MIGRATION_SHADCN.md` for the full token map
and conventions before generating.

## Inputs

- **Component name** (PascalCase), e.g. `AgentStatusPill`.
- Optional one-line description of what it renders.

## Rules (must follow)

1. **Location**: feature components go under `console/src/components/<Name>/index.tsx`
   (or the relevant `pages/<Area>/components/`). Generic primitives belong in
   `console/src/components/ui/` and should mirror upstream shadcn source.
2. **Styling**: Tailwind utility classes only. Use the theme **tokens**, never
   hardcoded colors: `bg-background`, `text-foreground`, `bg-card`, `bg-primary`
   `text-primary-foreground`, `bg-secondary`, `bg-muted`/`text-muted-foreground`,
   `bg-accent`, `border-border`, `ring-ring`, `bg-sidebar*`. Elevation via
   `shadow-aion` / `shadow-aion-sm`. Radius via `rounded-xl`/`rounded-2xl`.
   Buttons are pills (`rounded-full`) — reuse `@/components/ui/button`.
3. **Dark mode**: prefer tokens (auto-theme). If you must use a variant, the
   registered ones are `dark:` and `dark-mode:` (both target `.dark-mode`).
4. **className merge**: always accept a `className?: string` prop and merge with
   `cn()` from `@/lib/utils`.
5. **Variants**: if the component has visual variants, use
   `class-variance-authority` (`cva`) like `@/components/ui/button`.
6. **Icons**: `lucide-react`. **Toasts**: `sonner` (`import { toast } from "sonner"`).
   **Forms**: `react-hook-form` + `zod` + `@/components/ui/form`.
7. **Accessibility**: icon-only buttons get `aria-label`; dialogs/sheets always get
   `*Title` + `*Description`; inputs get an associated `Label`.
8. **i18n**: user-facing strings go through `react-i18next` (`const { t } = useTranslation()`),
   never hardcoded — add keys to `console/src/locales/*`.
9. **No antd**: do not import `antd`/`@ant-design/*`/`antd-style`.

## Reference template (adapt; don't paste verbatim)

```tsx
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const xVariants = cva("inline-flex items-center rounded-full text-sm", {
  variants: {
    tone: {
      default: "bg-secondary text-secondary-foreground",
      solid: "bg-primary text-primary-foreground",
      muted: "bg-muted text-muted-foreground",
    },
  },
  defaultVariants: { tone: "default" },
});

export interface XProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof xVariants> {}

export const X = React.forwardRef<HTMLDivElement, XProps>(
  ({ className, tone, ...props }, ref) => (
    <div ref={ref} className={cn(xVariants({ tone }), className)} {...props} />
  ),
);
X.displayName = "X";
```

## Steps

1. Confirm name + target directory; check it doesn't already exist (Glob/Grep).
2. Generate the component per the rules above, with TypeScript props and a default export or named export consistent with neighbors.
3. If it needs a shadcn primitive not yet in `components/ui/`, generate that too (mirror upstream shadcn source, wired to `cn` + tokens).
4. Run `cd console && npx tsc -b` to confirm it type-checks.
5. Tell the user where it was created and show a minimal usage snippet.
