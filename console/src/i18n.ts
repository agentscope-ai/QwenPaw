import { createInstance, type BackendModule, type ReadCallback } from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";

type LocaleResource = Record<string, unknown>;

export const localeLoaders = {
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

export function loadLocale(language: string): Promise<LocaleResource> {
  const locale = resolveSupportedLanguage(language);
  const cached = localeCache.get(locale);
  if (cached) return cached;

  const loading = localeLoaders[locale]().catch((error: unknown) => {
    localeCache.delete(locale);
    throw error;
  });
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
        // the console from starting, but the degradation must be visible.
        console.error(
          `Failed to load locale "${language}", falling back:`,
          error,
        );
        callback(null, en);
      });
  },
};

const initialLanguage =
  localStorage.getItem("language") || navigator.language || "en";
const localeCodes = Object.keys(localeLoaders) as SupportedLanguage[];
// nonExplicitSupportedLngs reduces a region-qualified code to its language
// part before matching supportedLngs, so "pt-BR" is looked up as "pt" and
// rejected unless that alias is also registered.
const languageOnlyAliases = localeCodes
  .filter((code) => code.includes("-"))
  .map((code) => code.split("-")[0])
  .filter((code) => !localeCodes.includes(code as SupportedLanguage));
const supportedLngs = [...localeCodes, ...languageOnlyAliases];

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
