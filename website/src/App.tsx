import { Suspense, lazy, useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { defaultConfig, loadSiteConfig, type SiteConfig } from "@/config";
import { SiteConfigProvider } from "@/config-context";
import { SiteLayout } from "@/components/SiteLayout";
import { Home } from "@/pages/Home";
import "@/index.css";

const Docs = lazy(() =>
  import("@/pages/Docs").then((m) => ({ default: m.Docs })),
);
const ReleaseNotes = lazy(() =>
  import("@/pages/ReleaseNotes").then((m) => ({ default: m.ReleaseNotes })),
);
const Downloads = lazy(() =>
  import("@/pages/Downloads").then((m) => ({ default: m.Downloads })),
);

export default function App() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<SiteConfig>(defaultConfig);

  useEffect(() => {
    loadSiteConfig().then(setConfig);
  }, []);

  return (
    <SiteConfigProvider config={config}>
      <Suspense
        fallback={
          <div className="min-h-screen flex items-center justify-center text-[var(--text-muted)]">
            {t("docs.searchLoading")}
          </div>
        }
      >
        <Routes>
          <Route element={<SiteLayout showFooter />}>
            <Route path="/" element={<Home />} />
            <Route path="/downloads" element={<Downloads />} />
          </Route>
          <Route element={<SiteLayout showFooter={false} />}>
            <Route
              path="/docs"
              element={<Navigate to="/docs/intro" replace />}
            />
            <Route path="/docs/:slug" element={<Docs />} />
            <Route path="/release-notes" element={<ReleaseNotes />} />
          </Route>
        </Routes>
      </Suspense>
    </SiteConfigProvider>
  );
}
