import type { AppCardData } from "./AppCard";
export const CURATED_APP_DESCRIPTIONS: Record<
  string,
  Record<string, string>
> = {
  "agent-kanban": {
    zh: "一个看板应用：创建任务并分配给智能体，由指定智能体自动执行，并实时查看其输出流。",
  },
};

export function pickAppDescription(app: AppCardData, language: string): string {
  const prefix = language.split("-")[0].toLowerCase();
  const i18nMap = app.description_i18n;
  if (i18nMap && Object.keys(i18nMap).length > 0) {
    if (i18nMap[language]) return i18nMap[language];
    for (const key of Object.keys(i18nMap)) {
      if (key.toLowerCase().startsWith(prefix)) return i18nMap[key];
    }
  }
  const curated = CURATED_APP_DESCRIPTIONS[app.id];
  if (curated?.[prefix]) return curated[prefix];
  if (i18nMap) {
    for (const key of Object.keys(i18nMap)) {
      if (key.toLowerCase().startsWith("en")) return i18nMap[key];
    }
  }
  return app.description;
}
