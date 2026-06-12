import i18n from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import type { ReactNode } from "react";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import ja from "@/locales/ja.json";
import ru from "@/locales/ru.json";

type LocaleRoot = {
  chat?: {
    dataSource?: Record<string, string>;
    planMode?: Record<string, string>;
  };
  dataConnection?: {
    types?: Record<string, { labelKey?: string }>;
  };
  common?: Record<string, string>;
};

function sliceBundle(full: LocaleRoot): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (full.chat?.dataSource || full.chat?.planMode) {
    out.chat = {
      ...(full.chat.dataSource ? { dataSource: full.chat.dataSource } : {}),
      ...(full.chat.planMode ? { planMode: full.chat.planMode } : {}),
    };
  }
  if (full.dataConnection?.types) {
    out.dataConnection = { types: full.dataConnection.types };
  }
  if (full.common) {
    out.common = full.common;
  }
  return out;
}

const toolbarI18n = i18n.createInstance();
toolbarI18n.use(initReactI18next).init({
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

export function ChatToolbarI18nProvider({ children }: { children: ReactNode }) {
  return <I18nextProvider i18n={toolbarI18n}>{children}</I18nextProvider>;
}
