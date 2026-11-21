import i18n, { type BackendModule } from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

// Keep the default/fallback languages synchronous. Other dictionaries are
// separate chunks and are requested only when that language is selected.
const localeLoaders = {
  ru: () => import("./locales/ru.json"),
  ja: () => import("./locales/ja.json"),
  "pt-BR": () => import("./locales/pt-BR.json"),
  id: () => import("./locales/id.json"),
  vi: () => import("./locales/vi.json"),
};

const localeBackend: BackendModule = {
  type: "backend",
  init() {},
  read(language, _namespace, callback) {
    const load = localeLoaders[language as keyof typeof localeLoaders];
    if (!load) {
      callback(null, {});
      return;
    }
    let finished = false;
    const finish: typeof callback = (error, data) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      callback(error, data);
    };
    // A failed optional chunk must not leave startup waiting indefinitely.
    const timer = setTimeout(
      () => finish(new Error("Locale load timeout"), false),
      8000,
    );
    load().then(
      (module) => finish(null, module.default),
      (error: Error) => finish(error, false),
    );
  },
};

const resources = {
  en: {
    translation: en,
  },
  zh: {
    translation: zh,
  },
};

export const i18nReady = i18n
  .use(localeBackend)
  .use(initReactI18next)
  .init({
    resources,
    partialBundledLanguages: true,
    initImmediate: false,
    maxRetries: 0,
    lng: localStorage.getItem("language") || "zh",
    fallbackLng: "zh",
    supportedLngs: [...Object.keys(resources), ...Object.keys(localeLoaders)],
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
