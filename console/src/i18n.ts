import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import zh from "./locales/zh.json";
import ja from "./locales/ja.json";
import { request } from "./api/request";

const resources = {
  en: {
    translation: en,
  },
  ru: {
    translation: ru,
  },
  zh: {
    translation: zh,
  },
  ja: {
    translation: ja,
  },
};

i18n.use(initReactI18next).init({
  resources,
  lng: localStorage.getItem("language") || "en",
  fallbackLng: "en",
  interpolation: {
    escapeValue: false,
  },
});

// Fetch server-saved language before first render; exported for main.tsx to await
export const languageReady = request<{ language: string }>(
  "/config/user-language",
)
  .then(({ language }) => {
    if (language && language !== i18n.language) {
      i18n.changeLanguage(language);
      localStorage.setItem("language", language);
    }
  })
  .catch((error) => {
    console.error("Failed to fetch user language from server:", error);
    /* server unavailable, keep localStorage value */
  });

export default i18n;
