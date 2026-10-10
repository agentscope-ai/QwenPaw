import type { Locale } from "antd/es/locale";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import idID from "antd/locale/id_ID";
import ptBR from "antd/locale/pt_BR";
import viVN from "antd/locale/vi_VN";
import esES from "antd/locale/es_ES";
// Side-effect imports: register the dayjs locales referenced by
// dayjsLocaleMap so dayjs.locale(...) can resolve them wherever this
// module is imported (App boot and tests alike).
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import "dayjs/locale/id";
import "dayjs/locale/pt-br";
import "dayjs/locale/vi";
import "dayjs/locale/es";

/**
 * Both maps are keyed by the language part only ("pt" for "pt-BR"),
 * because consumers normalize regional codes with split("-")[0] — the
 * initial locale lookup in App and the i18next languageChanged handler
 * must agree on the key or a language silently falls back to English
 * for every antd widget and relative date.
 *
 * Every entry in LANGUAGE_LIST (languageList.tsx) must have a key in
 * both maps; i18n.switchLanguage.test.tsx enforces that.
 */
export const antdLocaleMap: Record<string, Locale> = {
  zh: zhCN,
  en: enUS,
  ja: jaJP,
  ru: ruRU,
  id: idID,
  pt: ptBR,
  vi: viVN,
  es: esES,
};

/** Brazilian Portuguese ("pt-br") is the variant registered by dayjs. */
export const dayjsLocaleMap: Record<string, string> = {
  zh: "zh-cn",
  en: "en",
  ja: "ja",
  ru: "ru",
  id: "id",
  pt: "pt-br",
  vi: "vi",
  es: "es",
};
