import { Suspense, useMemo } from "react";
import { Loader2 } from "lucide-react";
import { Routes, Route, useLocation, matchPath } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { useSyncCodingMode } from "../../stores/useSyncCodingMode";
import { useRoutes } from "../../plugins/registry/hooks";
import { Slot } from "../../plugins/registry/Slot";

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

  return (
    <div className="flex flex-col h-screen">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar selectedKey={selectedKey} />
        <main className="flex-1 flex flex-col overflow-auto page-container">
          <ConsolePollService />
          <Slot name="content.statusBar" kind="fill" />
          <div className="flex-1 page-content">
            <ChunkErrorBoundary resetKey={currentPath}>
              <Suspense
                fallback={
                  <div className="flex items-center justify-center mt-[20vh]">
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    <span className="ml-2 text-muted-foreground text-sm">
                      {t("common.loading")}
                    </span>
                  </div>
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
        </main>
      </div>
      <Slot name="overlay.global" kind="fill" />
    </div>
  );
}
