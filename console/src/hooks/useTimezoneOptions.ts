import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { getTimezoneOptions, type TimezoneOption } from "../constants/timezone";

export function useTimezoneOptions(): TimezoneOption[] {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  return useMemo(() => {
    const locale = (language ?? "en").split("-")[0];
    return getTimezoneOptions(locale);
  }, [language]);
}
