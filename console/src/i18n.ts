import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import zh from "./locales/zh.json";
import ja from "./locales/ja.json";
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

export default i18n;
