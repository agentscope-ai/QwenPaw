import type * as ReactNS from "react";
import { resolvePetLocale, t, type MessageKey, type PetLocale } from "./locale";
import { subscribeConsoleLanguage } from "./watchConsoleLanguage";

/** Sync pet UI language with the QwenPaw console language switcher. */
export function usePetLocale(React: typeof ReactNS) {
  const [locale, setLocale] = React.useState<PetLocale>(() =>
    resolvePetLocale(),
  );

  React.useEffect(() => {
    const sync = (language?: string) => {
      setLocale((prev) => {
        const next = resolvePetLocale(language);
        return prev === next ? prev : next;
      });
    };

    return subscribeConsoleLanguage((language) => sync(language));
  }, []);

  const tr = React.useCallback(
    (key: MessageKey, params?: Record<string, string | number>) =>
      t(locale, key, params),
    [locale],
  );

  return { locale, tr };
}
