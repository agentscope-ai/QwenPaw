import { createGlobalStyle } from "antd-style";
import {
  ConfigProvider,
  bailianDarkTheme,
  bailianTheme,
} from "@agentscope-ai/design";
import {
  Alert,
  App as AntdApp,
  ConfigProvider as AntdConfigProvider,
} from "antd";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import jaJP from "antd/locale/ja_JP";
import ruRU from "antd/locale/ru_RU";
import idID from "antd/locale/id_ID";
import type { Locale } from "antd/es/locale";
import { theme as antdTheme } from "antd";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import "dayjs/locale/ja";
import "dayjs/locale/ru";
import "dayjs/locale/id";
dayjs.extend(relativeTime);
import { ThemeProvider, useTheme } from "./contexts/ThemeContext";
import { PluginProvider, usePlugins } from "./plugins/PluginContext";
import { ApprovalProvider } from "./contexts/ApprovalContext";
import { DesktopUpdateProvider } from "./contexts/DesktopUpdateContext";
import { UpdateTakeoverGate } from "./components/UpdateTakeoverPage";
import { Suspense } from "react";
import { lazyImportWithRetry, lazyWithRetry } from "./utils/lazyWithRetry";
import LoadingStatus from "./components/LoadingStatus";
import AuthBootstrapStatus from "./components/AuthBootstrapStatus";
import { ChunkErrorBoundary } from "./components/ChunkErrorBoundary";
import {
  getLoginHref,
  getLoginPath,
  getRouterBasename,
  isOsPath,
} from "./utils/navigationMode";

const LoginPage = lazyImportWithRetry("./pages/Login/index");
// Login does not need the application shell or tool renderers. Register cards
// before either shell mounts; external plugin overrides retain their priority.
async function withBuiltinCards<T>(factory: () => Promise<T>): Promise<T> {
  const [module, cards] = await Promise.all([
    factory(),
    import("./components/Chat/ToolCards/registerBuiltinCards"),
  ]);
  cards.registerBuiltinCards();
  return module;
}
const MainLayout = lazyWithRetry(() =>
  withBuiltinCards(() => import("./layouts/MainLayout")),
);
const DesktopOSPage = lazyWithRetry(() =>
  withBuiltinCards(() => import("./os/DesktopOS")),
);
import { languageApi } from "./api/modules/language";
import { useUploadLimitStore } from "./stores/uploadLimitStore";
import { useAuthStore } from "./stores/authStore";
import CloseWindowPrompt from "./tauri/CloseWindowPrompt";
import { isTauri } from "@tauri-apps/api/core";
import { isDesktopTauriRuntime } from "./utils/openExternalLink";
import { interceptBlankLinkClicks } from "./utils/interceptBlankLinkClicks";
import "./styles/layout.css";
import "./styles/form-override.css";

const antdLocaleMap: Record<string, Locale> = {
  zh: zhCN,
  en: enUS,
  ja: jaJP,
  ru: ruRU,
  id: idID,
};

const dayjsLocaleMap: Record<string, string> = {
  zh: "zh-cn",
  en: "en",
  ja: "ja",
  ru: "ru",
  id: "id",
};

const GlobalStyle = createGlobalStyle`
* {
  margin: 0;
  box-sizing: border-box;
}
`;

function AuthGuard({
  children,
  useHardRedirect = false,
}: {
  children: React.ReactNode;
  useHardRedirect?: boolean;
}) {
  const phase = useAuthStore((state) => state.phase);
  const bootstrap = useAuthStore((state) => state.bootstrap);

  useEffect(() => {
    if (phase === "loading") void bootstrap();
  }, [bootstrap, phase]);

  if (phase === "loading") return <AuthBootstrapStatus />;
  if (phase === "anonymous") {
    const loginTo = getLoginPath(window.location);
    if (useHardRedirect) {
      // The OS shell renders outside a Router, so <Navigate> is unavailable.
      window.location.replace(getLoginHref(window.location));
      return null;
    }
    return <Navigate to={loginTo} replace />;
  }
  return <>{children}</>;
}

function AppInner() {
  const basename = getRouterBasename(window.location.pathname);
  const { i18n } = useTranslation();
  const { isDark } = useTheme();
  const { loading: pluginsLoading, error: pluginError } = usePlugins();
  const authPhase = useAuthStore((state) => state.phase);
  const authMode = useAuthStore((state) => state.mode);
  const preferredLanguage = useAuthStore(
    (state) => state.preferences?.language,
  );
  const selectedTheme = isDark ? bailianDarkTheme : bailianTheme;
  const lang = i18n.resolvedLanguage || i18n.language || "zh";
  const [antdLocale, setAntdLocale] = useState<Locale>(
    antdLocaleMap[lang.split("-")[0]] ?? zhCN,
  );

  useEffect(() => {
    useUploadLimitStore.getState().fetch();
  }, []);

  useEffect(() => {
    if (authPhase === "loading") return;

    if (authMode === "multi_user") {
      if (preferredLanguage && preferredLanguage !== i18n.language) {
        void i18n.changeLanguage(preferredLanguage);
        localStorage.setItem("language", preferredLanguage);
      }
      return;
    }

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
  }, [authMode, authPhase, i18n, preferredLanguage]);

  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      const shortLng = lng.split("-")[0];
      setAntdLocale(antdLocaleMap[shortLng] ?? zhCN);
      dayjs.locale(dayjsLocaleMap[shortLng] ?? "zh-cn");
    };

    // Set initial dayjs locale
    dayjs.locale(dayjsLocaleMap[lang.split("-")[0]] ?? "zh-cn");

    i18n.on("languageChanged", handleLanguageChanged);
    return () => {
      i18n.off("languageChanged", handleLanguageChanged);
    };
  }, [i18n]);

  // Static Modal/message calls mount outside App's tree. Supply the same
  // locale and prefix so their buttons do not silently fall back to English.
  useEffect(() => {
    AntdConfigProvider.config({
      prefixCls: "qwenpaw",
      holderRender: (children) => (
        <AntdConfigProvider locale={antdLocale} prefixCls="qwenpaw">
          {children}
        </AntdConfigProvider>
      ),
    });
    return () => AntdConfigProvider.config({ holderRender: undefined });
  }, [antdLocale]);

  // Disable the default browser context menu in the Tauri desktop build so
  // users cannot open DevTools via right-click. DevTools is still available
  // through the hidden 8-click logo gesture handled in Header.tsx.
  useEffect(() => {
    if (!isTauri()) return;
    const preventContextMenu = (e: MouseEvent) => e.preventDefault();
    window.addEventListener("contextmenu", preventContextMenu);
    return () => window.removeEventListener("contextmenu", preventContextMenu);
  }, []);

  // Vendor-rendered markdown (e.g. chat bubbles) emits native
  // `<a target="_blank">` anchors we cannot override at the React level. The
  // Tauri WebView ignores such clicks, so route them to the system browser.
  useEffect(() => {
    if (!isDesktopTauriRuntime()) return;
    return interceptBlankLinkClicks();
  }, []);

  // Isolated plugins cannot patch core pages. Only a direct plugin URL needs
  // its registrations before the router can resolve the page.
  if (pluginsLoading && window.location.pathname.includes("/plugin/")) {
    return <LoadingStatus />;
  }

  const osActive = isOsPath(window.location.pathname);

  // The Desktop OS shell renders OUTSIDE any Router: each window supplies its
  // own MemoryRouter (WindowRouter.tsx) and React Router forbids nesting a
  // <Router> inside another. The classic browser layout keeps its BrowserRouter.
  const routedContent = osActive ? (
    <AuthGuard useHardRedirect>
      <ChunkErrorBoundary resetKey="desktop-shell">
        <Suspense fallback={<LoadingStatus />}>
          <DesktopOSPage />
        </Suspense>
      </ChunkErrorBoundary>
    </AuthGuard>
  ) : (
    <BrowserRouter basename={basename}>
      <Routes>
        <Route
          path="/login"
          element={
            <Suspense fallback={<LoadingStatus />}>
              <LoginPage />
            </Suspense>
          }
        />
        <Route
          path="/*"
          element={
            <AuthGuard>
              <ChunkErrorBoundary resetKey="main-shell">
                <Suspense fallback={<LoadingStatus />}>
                  <MainLayout />
                </Suspense>
              </ChunkErrorBoundary>
            </AuthGuard>
          }
        />
      </Routes>
    </BrowserRouter>
  );

  return (
    <>
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
          {pluginError &&
            (authPhase === "authenticated" || authPhase === "disabled") && (
              <Alert
                key={pluginError}
                type="warning"
                showIcon
                closable
                message="部分前端插件未加载"
                description={
                  <details>
                    <summary>查看原因</summary>
                    {pluginError}
                  </details>
                }
                style={{
                  position: "fixed",
                  bottom: 16,
                  right: 16,
                  maxWidth: 520,
                  zIndex: 2000,
                }}
              />
            )}
          <CloseWindowPrompt />
          <DesktopUpdateProvider>
            <UpdateTakeoverGate>
              <ApprovalProvider>{routedContent}</ApprovalProvider>
            </UpdateTakeoverGate>
          </DesktopUpdateProvider>
        </AntdApp>
      </ConfigProvider>
    </>
  );
}

function App() {
  return (
    <ThemeProvider>
      <PluginProvider>
        <AppInner />
      </PluginProvider>
    </ThemeProvider>
  );
}

export default App;
