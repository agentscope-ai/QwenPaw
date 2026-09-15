import { useTranslation } from "react-i18next";

export function useGovernanceText() {
  const { i18n } = useTranslation();
  return (zh: string, en: string) => (i18n.language.startsWith("zh") ? zh : en);
}
export function editable<T extends { id: string; revision: number }>(value: T) {
  return Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== "id" && key !== "revision"),
  ) as Omit<T, "id" | "revision">;
}
