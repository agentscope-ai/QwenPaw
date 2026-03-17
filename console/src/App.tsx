import { createGlobalStyle } from "antd-style";
import { ConfigProvider, bailianTheme } from "@agentscope-ai/design";
import { BrowserRouter } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import type { Locale } from "antd/es/locale";
import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import MainLayout from "./layouts/MainLayout";
import "./styles/layout.css";
import "./styles/form-override.css";

const antdLocaleMap: Record<string, Locale> = {
  zh: zhCN,
  en: enUS,
  ja: jaJP,
  ru: ruRU,
};

const dayjsLocaleMap: Record<string, string> = {
  zh: "zh-cn",
  en: "en",
  ja: "ja",
  ru: "ru",
};

const GlobalStyle = createGlobalStyle`
* {
  margin: 0;
  box-sizing: border-box;
}
`;

function getRouterBasename(pathname: string): string | undefined {
  return /^\/console(?:\/|$)/.test(pathname) ? "/console" : undefined;
}

function App() {
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const lang = i18n.resolvedLanguage || i18n.language || "en";
  const [antdLocale, setAntdLocale] = useState<Locale>(
    antdLocaleMap[lang] ?? enUS,
  );

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      const shortLng = lng.split("-")[0];
      setAntdLocale(antdLocaleMap[shortLng] ?? enUS);
      dayjs.locale(dayjsLocaleMap[shortLng] ?? "en");
    };

    // Set initial dayjs locale
    dayjs.locale(dayjsLocaleMap[lang.split("-")[0]] ?? "en");

    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [i18n]);

  return (
    <BrowserRouter basename={basename}>
      <GlobalStyle />
      <ConfigProvider
        {...bailianTheme}
        prefix="copaw"
        prefixCls="copaw"
        locale={antdLocale}
      >
        <MainLayout />
      </ConfigProvider>
    </BrowserRouter>
  );
}

export default App;
