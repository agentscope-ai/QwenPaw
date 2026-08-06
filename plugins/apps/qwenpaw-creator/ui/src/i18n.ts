import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zh from "./locales/zh.json";
import en from "./locales/en.json";

const resources = {
  zh: { translation: zh },
  en: { translation: en },
};

// Node >= 22 exposes a global localStorage stub whose methods throw until
// the experimental web storage is configured; only trust a functional one
// (the browser / jsdom implementation).
function storedLanguage(): string | null {
  try {
    if (
      typeof localStorage !== "undefined" &&
      typeof localStorage.getItem === "function"
    ) {
      return localStorage.getItem("language");
    }
  } catch {
    // Fall through to navigator/default detection.
  }
  return null;
}

i18n.use(initReactI18next).init({
  resources,
  lng:
    storedLanguage() ||
    (typeof navigator !== "undefined" ? navigator.language : null) ||
    "en",
  load: "languageOnly",
  fallbackLng: "en",
  supportedLngs: Object.keys(resources),
  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
