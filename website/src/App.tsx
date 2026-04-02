import { useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { loadSiteConfig, type SiteConfig } from "@/config";
import { SiteConfigProvider } from "@/config-context";
import { SiteLayout } from "@/components/SiteLayout";
import { Home } from "@/pages/Home";
import { Docs } from "@/pages/Docs";
import { ReleaseNotes } from "@/pages/ReleaseNotes";
import { Downloads } from "@/pages/Downloads";
import "@/index.css";

export default function App() {
  const { t } = useTranslation();
  const [config, setConfig] = useState<SiteConfig | null>(null);

  useEffect(() => {
    loadSiteConfig().then(setConfig);
  }, []);

  if (!config) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--text-muted)",
        }}
      >
        {t("docs.searchLoading")}
      </div>
    );
  }

  return (
    <SiteConfigProvider config={config}>
      <Routes>
        <Route element={<SiteLayout showFooter />}>
          <Route path="/" element={<Home />} />
          <Route path="/downloads" element={<Downloads />} />
        </Route>
        <Route element={<SiteLayout showFooter={false} />}>
          <Route path="/docs" element={<Navigate to="/docs/intro" replace />} />
          <Route path="/docs/:slug" element={<Docs />} />
          <Route path="/release-notes" element={<ReleaseNotes />} />
        </Route>
      </Routes>
    </SiteConfigProvider>
  );
}
