import i18n from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import type { ReactNode } from "react";
import en from "../locales/en.json";
import zh from "../locales/zh.json";
import ja from "../locales/ja.json";
import ru from "../locales/ru.json";

type LocaleRoot = {
  taskGraph?: Record<string, string>;
  agent?: Record<string, string>;
};

function sliceBundle(full: LocaleRoot): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (full.taskGraph) out.taskGraph = full.taskGraph;
  if (full.agent) out.agent = full.agent;
  return out;
}

const pluginI18n = i18n.createInstance();
pluginI18n.use(initReactI18next).init({
  resources: {
    en: { translation: sliceBundle(en as LocaleRoot) },
    zh: { translation: sliceBundle(zh as LocaleRoot) },
    ja: { translation: sliceBundle(ja as LocaleRoot) },
    ru: { translation: sliceBundle(ru as LocaleRoot) },
  },
  lng: localStorage.getItem("language") || "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function PluginI18nProvider({ children }: { children: ReactNode }) {
  return <I18nextProvider i18n={pluginI18n}>{children}</I18nextProvider>;
}
