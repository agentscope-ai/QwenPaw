import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import ru from "./locales/ru.json";
import zh from "./locales/zh.json";
import ja from "./locales/ja.json";
import ptBR from "./locales/pt-BR.json";
import id from "./locales/id.json";
import vi from "./locales/vi.json";

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
  "pt-BR": {
    translation: ptBR,
  },
  id: {
    translation: id,
  },
  vi: {
    translation: vi,
  },
};

const resourceCodes = Object.keys(resources);

// nonExplicitSupportedLngs makes i18next reduce a region-qualified code
// to its language part before matching it against supportedLngs, so
// "pt-BR" is looked up as "pt" and rejected unless that alias is also
// registered. When it is rejected the bundle never loads and the UI
// silently falls back to English while the selector still reports the
// language the user picked.
const languageOnlyAliases = resourceCodes
  .filter((code) => code.includes("-"))
  .map((code) => code.split("-")[0])
  .filter((code) => !resourceCodes.includes(code));

i18n.use(initReactI18next).init({
  resources,
  lng: localStorage.getItem("language") || navigator.language || "en",
  fallbackLng: "en",
  supportedLngs: [...resourceCodes, ...languageOnlyAliases],
  nonExplicitSupportedLngs: true,
  interpolation: {
    escapeValue: false,
  },
});

export default i18n;
