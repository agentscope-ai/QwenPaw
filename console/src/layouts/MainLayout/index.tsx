import { Suspense, useEffect, useMemo, useRef } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation, matchPath } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { useSyncCodingMode } from "../../stores/useSyncCodingMode";
import { notificationsApi } from "../../api/modules/notifications";
import styles from "../index.module.less";
import { useRoutes } from "../../plugins/registry/hooks";
import { Slot } from "../../plugins/registry/Slot";

const { Content } = Layout;

/**
 * Find the registered route whose path pattern matches the current URL.
 * Falls back to "core.chat" so the sidebar always has a sensible
 * highlight, mirroring the old `pathToKey` default.
 */
function pickSelectedKey(
  currentPath: string,
  routes: ReturnType<typeof useRoutes>,
): string {
  for (const r of routes) {
    if (matchPath({ path: r.path, end: r.path === "/" }, currentPath)) {
      return r.id;
    }
  }
  return "core.chat";
}

export default function MainLayout() {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const currentPath = location.pathname;
  const routes = useRoutes();

  // Backend is the source of truth for Coding Mode state — refill the
  // in-memory store every time the selected agent changes.
  useSyncCodingMode();

  // Sync console language to notification config so popups match UI language
  const syncedLangRef = useRef<string | null>(null);
  useEffect(() => {
    const lang = (i18n.resolvedLanguage ?? i18n.language ?? "en").split("-")[0];
    if (lang === syncedLangRef.current) return;
    syncedLangRef.current = lang;
    notificationsApi
      .getConfig()
      .then((cfg) => {
        const cfgLang = (cfg.language || "en").split("-")[0];
        if (cfgLang !== lang) {
          void notificationsApi.updateConfig({ ...cfg, language: lang });
        }
      })
      .catch(() => {});
  }, [i18n.language, i18n.resolvedLanguage]);

  const selectedKey = useMemo(
    () => pickSelectedKey(currentPath, routes),
    [currentPath, routes],
  );

  return (
    <Layout className={styles.mainLayout}>
      <Header />
      <Layout>
        <Sidebar selectedKey={selectedKey} />
        <Content className="page-container">
          <ConsolePollService />
          <Slot name="content.statusBar" kind="fill" />
          <div className="page-content">
            <ChunkErrorBoundary resetKey={currentPath}>
              <Suspense
                fallback={
                  <Spin
                    tip={t("common.loading")}
                    style={{ display: "block", margin: "20vh auto" }}
                  />
                }
              >
                <Routes>
                  {routes.map((r) => (
                    <Route key={r.id} path={r.path} element={<r.Component />} />
                  ))}
                </Routes>
              </Suspense>
            </ChunkErrorBoundary>
          </div>
        </Content>
      </Layout>
      <Slot name="overlay.global" kind="fill" />
    </Layout>
  );
}
