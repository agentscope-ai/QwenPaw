import { createGlobalStyle } from "antd-style";
import {
  ConfigProvider,
  bailianDarkTheme,
  bailianTheme,
} from "@agentscope-ai/design";
import { App as AntdApp } from "antd";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import type { Locale } from "antd/es/locale";
import { theme as antdTheme } from "antd";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
dayjs.extend(relativeTime);
import MainLayout from "./layouts/MainLayout";
import { ThemeProvider, useTheme } from "./contexts/ThemeContext";
import { PluginProvider, usePlugins } from "./plugins/PluginContext";
import { ApprovalProvider } from "./contexts/ApprovalContext";
import { Suspense } from "react";
import { lazyImportWithRetry } from "./utils/lazyWithRetry";

const LoginPage = lazyImportWithRetry("./pages/Login/index");
import { authApi } from "./api/modules/auth";
import { languageApi } from "./api/modules/language";
import { getApiUrl, getApiToken, clearAuthToken } from "./api/config";
import BackendReadyGate from "./components/BackendReadyGate";
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

function AuthGuard({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<"loading" | "auth-required" | "ok">(
    "loading",
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authApi.getStatus();
        if (cancelled) return;
        if (!res.enabled) {
          setStatus("ok");
          return;
        }
        const token = getApiToken();
        if (!token) {
          setStatus("auth-required");
          return;
        }
        try {
          const r = await fetch(getApiUrl("/auth/verify"), {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (cancelled) return;
          if (r.ok) {
            setStatus("ok");
          } else {
            clearAuthToken();
            setStatus("auth-required");
          }
        } catch {
          if (!cancelled) {
            clearAuthToken();
            setStatus("auth-required");
          }
        }
      } catch {
        if (!cancelled) setStatus("ok");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "loading") return null;
  if (status === "auth-required")
    return (
      <Navigate
        to={`/login?redirect=${encodeURIComponent(window.location.pathname)}`}
        replace
      />
    );
  return <>{children}</>;
}

function getRouterBasename(pathname: string): string | undefined {
  return /^\/console(?:\/|$)/.test(pathname) ? "/console" : undefined;
}

function AppInner() {
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const { isDark } = useTheme();
  const { loading: pluginsLoading } = usePlugins();
  const selectedTheme = isDark ? bailianDarkTheme : bailianTheme;
  const lang = i18n.resolvedLanguage || i18n.language || "en";
  const [antdLocale, setAntdLocale] = useState<Locale>(
    antdLocaleMap[lang] ?? enUS,
  );

  useEffect(() => {
    if (!localStorage.getItem("language")) {
      languageApi
        .getLanguage()
        .then(({ language }) => {
          if (language && language !== i18n.language) {
            i18n.changeLanguage(language);
            localStorage.setItem("language", language);
          }
        })
        .catch((err) =>
          console.error("Failed to fetch language preference:", err),
        );
    }
  }, []);

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

  // Wait for plugins to load before rendering routes that might be patched
  if (pluginsLoading) {
    return null;
  }

  return (
    <BrowserRouter basename={basename}>
      <GlobalStyle />
      <ConfigProvider
        {...selectedTheme}
        prefix="qwenpaw"
        prefixCls="qwenpaw"
        locale={antdLocale}
        theme={{
          ...(selectedTheme as any)?.theme,
          algorithm: isDark
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
          token: {
            colorPrimary: "#FF7F16",
          },
        }}
      >
        <AntdApp>
          <ApprovalProvider>
            <Routes>
              <Route
                path="/login"
                element={
                  <Suspense fallback={null}>
                    <LoginPage />
                  </Suspense>
                }
              />
              <Route
                path="/*"
                element={
                  <AuthGuard>
                    <MainLayout />
                  </AuthGuard>
                }
              />
            </Routes>
          </ApprovalProvider>
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}

function App() {
  return (
    <ThemeProvider>
      <PluginProvider>
        <BackendReadyGate>
          <AppInner />
        </BackendReadyGate>
      </PluginProvider>
     
    </ThemeProvider>
  );
}

export default App;
