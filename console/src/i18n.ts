import { createInstance, type BackendModule, type ReadCallback } from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";

type LocaleResource = Record<string, unknown>;

const localeLoaders = {
  en: () => Promise.resolve(en),
  ru: () => import("./locales/ru.json").then((module) => module.default),
  zh: () => import("./locales/zh.json").then((module) => module.default),
  ja: () => import("./locales/ja.json").then((module) => module.default),
  "pt-BR": () =>
    import("./locales/pt-BR.json").then((module) => module.default),
  id: () => import("./locales/id.json").then((module) => module.default),
  vi: () => import("./locales/vi.json").then((module) => module.default),
} as const satisfies Record<string, () => Promise<LocaleResource>>;

type SupportedLanguage = keyof typeof localeLoaders;

const localeCache = new Map<SupportedLanguage, Promise<LocaleResource>>([
  ["en", Promise.resolve(en)],
]);

function resolveSupportedLanguage(language: string): SupportedLanguage {
  const normalized = language.toLowerCase();
  const exact = (Object.keys(localeLoaders) as SupportedLanguage[]).find(
    (locale) => locale.toLowerCase() === normalized,
  );
  if (exact) return exact;

  const prefix = normalized.split("-")[0];
  const byPrefix = (Object.keys(localeLoaders) as SupportedLanguage[]).find(
    (locale) => locale.toLowerCase().split("-")[0] === prefix,
  );
  return byPrefix ?? "en";
}

function loadLocale(language: string): Promise<LocaleResource> {
  const locale = resolveSupportedLanguage(language);
  const cached = localeCache.get(locale);
  if (cached) return cached;

  const loading = localeLoaders[locale]();
  localeCache.set(locale, loading);
  return loading;
}

const localeBackend: BackendModule = {
  type: "backend",
  init: () => undefined,
  read: (language: string, _namespace: string, callback: ReadCallback) => {
    void loadLocale(language)
      .then((resource) => callback(null, resource))
      .catch((error: unknown) => {
        // English is bundled, so a failed optional locale must not prevent
        // the console from starting.
        callback(
          null,
          resolveSupportedLanguage(language) === "en" ? undefined : en,
        );
        if (resolveSupportedLanguage(language) === "en") {
          console.error("Failed to load English locale:", error);
        }
      });
  },
};

const initialLanguage =
  localStorage.getItem("language") || navigator.language || "en";
const supportedLngs = [...Object.keys(localeLoaders), "pt"];

const i18n = createInstance();

export const i18nReady = i18n
  .use(localeBackend)
  .use(initReactI18next)
  .init({
    lng: initialLanguage,
    fallbackLng: "en",
    supportedLngs,
    nonExplicitSupportedLngs: true,
    partialBundledLanguages: true,
    interpolation: {
      escapeValue: false,
    },
  });

export default i18n;
