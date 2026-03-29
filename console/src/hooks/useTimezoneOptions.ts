import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { getTimezoneOptions, type TimezoneOption } from "../constants/timezone";

export function useTimezoneOptions(): TimezoneOption[] {
  const { i18n } = useTranslation();
  return useMemo(() => getTimezoneOptions(i18n.language), [i18n.language]);
}
