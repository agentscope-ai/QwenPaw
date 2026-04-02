# formatTimeAgo i18n Enhancement Design

## Context

The current `formatTimeAgo` in `console/src/pages/Agent/Workspace/components/utils.ts` hardcodes English strings ("just now", "m ago", "h ago", "d ago") and lacks proper plural support. The project already uses `react-i18next` with en/ru/zh/ja locales.

## Goal

Replace hardcoded strings with `date-fns`'s `formatDistanceToNow` for:
- Proper grammatical plural forms ("1 minute" vs "5 minutes")
- Locale-aware output using existing i18n languages
- Absolute date fallback for timestamps older than 30 days

## Design

### Dependencies

Add `date-fns` to `console/package.json`:

```json
"date-fns": "^4.1.0"
```

### Locale Mapping

| i18n language | date-fns locale |
|---------------|-----------------|
| `en`          | `enUS`          |
| `ru`          | `ru`            |
| `zh`          | `zhCN`          |
| `ja`          | `ja`            |

### Implementation

**`console/src/pages/Agent/Workspace/components/utils.ts`**

```typescript
import { formatDistanceToNow } from 'date-fns';
import { enUS, ru, zhCN, ja } from 'date-fns/locale';

const DATE_FNS_LOCALES: Record<string, Locale> = {
  en: enUS,
  ru,
  zh: zhCN,
  ja,
};

export const formatTimeAgo = (
  timestamp: number | string,
  locale?: string,
): string => {
  const time =
    typeof timestamp === 'string'
      ? new Date(timestamp).getTime()
      : timestamp;
  if (isNaN(time)) {
    return '-';
  }

  const dateFnsLocale = locale ? DATE_FNS_LOCALES[locale] : enUS;

  // For timestamps older than 30 days, return absolute date
  const thirtyDaysInSeconds = 30 * 24 * 60 * 60;
  const secondsAgo = (Date.now() - time) / 1000;
  if (secondsAgo > thirtyDaysInSeconds) {
    // Use absolute date format for older timestamps
    return formatDistanceToNow(time, { addSuffix: true, locale: dateFnsLocale });
  }

  return formatDistanceToNow(time, { addSuffix: true, locale: dateFnsLocale });
};
```

Note: The 30-day threshold is a UX judgment call — beyond this, relative time becomes less useful and absolute dates (e.g., "Mar 15, 2024") are more informative.

### Call Site Update

**`console/src/pages/Agent/Workspace/components/FileItem.tsx`**

```typescript
import { useTranslation } from "react-i18next";

// In component:
const { i18n } = useTranslation();

// Usage:
{formatFileSize(file.size)} · {formatTimeAgo(file.modified_time, i18n.language)}
```

### Translations Required

Add to each locale file (`en.json`, `ru.json`, `zh.json`, `ja.json`):

No new translation keys needed — `formatDistanceToNow` returns fully-localized strings automatically.

### Testing

1. Verify `1 minute ago` vs `5 minutes ago` for English
2. Verify Russian plural forms work correctly
3. Verify Chinese (no plural) renders correctly
4. Verify Japanese renders correctly
5. Verify invalid timestamp returns `-`
6. Verify timestamps older than 30 days show absolute-ish relative time

## Scope

- Only `formatTimeAgo` function
- Only affects `console/src/pages/Agent/Workspace/components/` area
- No other usages of `formatTimeAgo` across the codebase (confirmed via grep)

## Out of Scope

- `formatFileSize` function (not mentioned)
- Other time formatting utilities
- Backend Python code
