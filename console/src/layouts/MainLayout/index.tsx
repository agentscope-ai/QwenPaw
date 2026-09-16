import { Suspense, useMemo } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { AgentStatusPollingController } from "../../components/AgentStatusPollingController";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { useSyncCodingMode } from "../../stores/useSyncCodingMode";
import styles from "../index.module.less";
import { useRoutes } from "../../plugins/registry/hooks";
import { Slot } from "../../plugins/registry/Slot";
import { pickSelectedKey } from "./routeSelection";

const { Content } = Layout;

export default function MainLayout({ hubMode = false }: { hubMode?: boolean }) {
  const { t } = useTranslation();
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
    <Layout className={styles.mainLayout}>
      {!settingsCenterActive && (
        <Sidebar selectedKey={selectedKey} hubMode={hubMode} />
      )}
      <Layout className={styles.mainContentLayout}>
        <Header showBrand={settingsCenterActive} />
        <Content className="page-container">
          <ConsolePollService />
          <AgentStatusPollingController />
          <Slot name="content.statusBar" kind="fill" />
          <div className="page-content">
            <ChunkErrorBoundary
              resetKey={currentPath}
              canRestartRuntime={hubMode}
            >
              <Suspense
                fallback={
                  <Spin
                    tip={t("common.loading")}
                    style={{ display: "block", margin: "20vh auto" }}
                  />
                }
              >
                <Routes>
                  {renderableRoutes.map((r) => (
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
