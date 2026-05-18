import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import zh from "@/i18n/locales/zh.json";
import en from "@/i18n/locales/en.json";
import ptBR from "@/i18n/locales/pt-BR.json";

export type Lang = "zh" | "en" | "pt-BR";

export const LANG_KEY = "site-lang";

export const i18n = i18next.createInstance();

void i18n.use(initReactI18next).init({
  resources: {
    zh: { translation: zh },
    en: { translation: en },
    "pt-BR": { translation: ptBR },
  },
  lng: "zh",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

export function t(lang: Lang, key: string): string {
  return i18n.getFixedT(lang)(key);
}
