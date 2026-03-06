import { useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { loadSiteConfig, type SiteConfig } from "./config";
import { type Lang, t } from "./i18n";
import { Home } from "./pages/Home";
import { Docs } from "./pages/Docs";
import { ReleaseNotes } from "./pages/ReleaseNotes";
import "./index.css";

const LANG_KEY = "site-lang";

function getStoredLang(): Lang {
  const v = localStorage.getItem(LANG_KEY);
  return v === "en" ? "en" : "zh";
}

export default function App() {
  const [config, setConfig] = useState<SiteConfig | null>(null);
  const [lang, setLang] = useState<Lang>(getStoredLang);

  useEffect(() => {
    loadSiteConfig().then(setConfig);
  }, []);

  const toggleLang = () => {
    const next: Lang = lang === "zh" ? "en" : "zh";
    setLang(next);
    localStorage.setItem(LANG_KEY, next);
  };

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
        {t(lang, "nav.docs")}
      </div>
    );
  }

  return (
    <Routes>
      <Route
        path="/"
        element={<Home config={config} lang={lang} onLangClick={toggleLang} />}
      />
      <Route path="/docs" element={<Navigate to="/docs/intro" replace />} />
      <Route
        path="/docs/:slug"
        element={<Docs config={config} lang={lang} onLangClick={toggleLang} />}
      />
      <Route
        path="/release-notes"
        element={
          <ReleaseNotes config={config} lang={lang} onLangClick={toggleLang} />
        }
      />
    </Routes>
  );
}
