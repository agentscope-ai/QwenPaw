import { useEffect, useState } from "react";
import enUS from "antd/locale/en_US";
import type { Locale } from "antd/es/locale";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import designI18n from "@agentscope-ai/design/lib/i18n";

dayjs.extend(relativeTime);

export const uiLocaleLoaders = {
  en: () => Promise.resolve(enUS),
  zh: async () => {
    const [locale] = await Promise.all([
      import("antd/locale/zh_CN"),
      import("dayjs/locale/zh-cn"),
    ]);
    return locale.default;
  },
  ja: async () => {
    const [locale] = await Promise.all([
      import("antd/locale/ja_JP"),
      import("dayjs/locale/ja"),
    ]);
    return locale.default;
  },
  ru: async () => {
    const [locale] = await Promise.all([
      import("antd/locale/ru_RU"),
      import("dayjs/locale/ru"),
    ]);
    return locale.default;
  },
  id: async () => {
    const [locale] = await Promise.all([
      import("antd/locale/id_ID"),
      import("dayjs/locale/id"),
    ]);
    return locale.default;
  },
} satisfies Record<string, () => Promise<Locale>>;

type UiLanguage = keyof typeof uiLocaleLoaders;
const cache = new Map<UiLanguage, Promise<Locale>>();

export function loadUiLocale(language: string): Promise<Locale> {
  const shortLanguage = language.toLowerCase().split(/[-_]/)[0];
  const key = (
    Object.prototype.hasOwnProperty.call(uiLocaleLoaders, shortLanguage)
      ? shortLanguage
      : "en"
  ) as UiLanguage;
  const cached = cache.get(key);
  if (cached) return cached;
  const loading = uiLocaleLoaders[key]().catch((error: unknown) => {
    cache.delete(key);
    throw error;
  });
  cache.set(key, loading);
  return loading;
}

export function useUiLocale(language: string): Locale {
  const [locale, setLocale] = useState(enUS);
  useEffect(() => {
    let cancelled = false;
    const apply = (next: Locale) => {
      if (cancelled) return;
      designI18n.updateLocale(next.locale);
      dayjs.locale(next.locale);
      setLocale(next);
    };
    void loadUiLocale(language)
      .then(apply)
      .catch((error: unknown) => {
        if (cancelled) return;
        console.error(
          `Failed to load UI locale "${language}", falling back:`,
          error,
        );
        apply(enUS);
      });
    return () => {
      cancelled = true;
    };
  }, [language]);
  return locale;
}
