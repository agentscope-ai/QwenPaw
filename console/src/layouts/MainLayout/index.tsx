import { useMemo } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import AmbientLight from "../AmbientLight";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { AgentStatusPollingController } from "../../components/AgentStatusPollingController";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { ChunkRecoverySuspense } from "../../components/ChunkRecoverySuspense";
import { useSyncCodingMode } from "../../stores/useSyncCodingMode";
import styles from "../index.module.less";
import { useRoutes } from "../../plugins/registry/hooks";
import { Slot } from "../../plugins/registry/Slot";
import { PageShell } from "../../components/PageShell";
import { pickSelectedKey } from "./routeSelection";
import { RouteDocumentTitle } from "./RouteDocumentTitle";
import { getRouteTitle } from "./routeTitle";

import { HubModeContext } from "../../contexts/HubModeContext";

const { Content } = Layout;

export default function MainLayout({ hubMode = false }: { hubMode?: boolean }) {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const currentPath = location.pathname;
  const routes = useRoutes();

  // Backend is the source of truth for Coding Mode state — refill the
  // in-memory store every time the selected agent changes.
  useSyncCodingMode();

  const selectedKey = useMemo(
    () => pickSelectedKey(currentPath, routes),
    [currentPath, routes],
  );
  const settingsCenterActive = selectedKey === "core.settings-center";
  const selectedRoute = routes.find((route) => route.id === selectedKey);
  const pageTitle = getRouteTitle(selectedRoute, i18n.language);

  // PawApp inline routes (`/apps/<id>`) are rendered *inside* the App Center
  // page (with its "← App Center" bar), never as standalone full-page routes.
  // They stay in the registry so the App Center can look up their component;
  // we just skip them here. The App Center's own `/apps/:appId` route (with a
  // colon) is kept, so a deep-link / refresh lands on the App Center wrapper.
  const renderableRoutes = useMemo(
    () => routes.filter((r) => !/^\/apps\/(?!:)/.test(r.path)),
    [routes],
  );

  return (
    <HubModeContext.Provider value={hubMode}>
      <Layout className={styles.mainLayout}>
        <RouteDocumentTitle title={pageTitle} />
        <a
          className={styles.skipLink}
          href="#main-content"
          onClick={() => document.getElementById("main-content")?.focus()}
        >
          {t("accessibility.skipToContent", "Skip to content")}
        </a>
        <AmbientLight />
        {!settingsCenterActive && (
          <Sidebar selectedKey={selectedKey} hubMode={hubMode} />
        )}
        <Layout className={styles.mainContentLayout}>
          <Header showBrand={settingsCenterActive} />
          <Content
            id="main-content"
            role="main"
            tabIndex={-1}
            className="page-container"
          >
            <ConsolePollService />
            <AgentStatusPollingController />
            <Slot name="content.statusBar" kind="fill" />
            <div className="page-content">
              <ChunkErrorBoundary
                resetKey={currentPath}
                canRestartRuntime={hubMode}
              >
                <ChunkRecoverySuspense
                  fallback={
                    <Spin
                      aria-label={t("common.loading")}
                      style={{ display: "block", margin: "20vh auto" }}
                    />
                  }
                >
                  <Routes>
                    {renderableRoutes.map((r) => (
                      <Route
                        key={r.id}
                        path={r.path}
                        caseSensitive={r.caseSensitive}
                        element={
                          <PageShell
                            title={getRouteTitle(r, i18n.language)}
                            mode="compat"
                          >
                            <r.Component />
                          </PageShell>
                        }
                      />
                    ))}
                  </Routes>
                </ChunkRecoverySuspense>
              </ChunkErrorBoundary>
            </div>
          </Content>
        </Layout>
        <Slot name="overlay.global" kind="fill" />
      </Layout>
    </HubModeContext.Provider>
  );
}
