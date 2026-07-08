import { lazy, useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { loadSiteConfig, type SiteConfig, defaultConfig } from "@/config";
import { SiteConfigProvider } from "@/config-context";
import { SiteLayout } from "@/components/SiteLayout";
import { GA_ID, loadGoogleAnalytics } from "@/lib/analytics";
import "@/index.css";

// Lazy load page components for better performance
const Home = lazy(() => import("@/pages/Home"));
const Docs = lazy(() => import("@/pages/Docs"));
const Blog = lazy(() => import("@/pages/Blog"));
const BlogPost = lazy(() => import("@/pages/Blog/Post"));
const ReleaseNotes = lazy(() => import("@/pages/ReleaseNotes"));
const Downloads = lazy(() => import("@/pages/Downloads"));

/**
 * Initial loading fallback component
 */
function LoadingFallback() {
  const { t } = useTranslation();

  return (
    <div className="min-h-screen flex items-center justify-center text-[var(--text-muted)]">
      {t("docs.searchLoading")}
    </div>
  );
}

export default function App() {
  const [config, setConfig] = useState<SiteConfig>(defaultConfig);
  const [isLoading, setIsLoading] = useState(true);

  // Load site configuration
  useEffect(() => {
    loadSiteConfig()
      .then((loadedConfig) => {
        setConfig(loadedConfig);
      })
      .catch((error) => {
        console.error("[Config] Failed to load configuration:", error);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  // Load Google Analytics after page is fully loaded
  useEffect(() => {
    const handleLoad = () => {
      loadGoogleAnalytics(GA_ID);
    };

    if (document.readyState === "complete") {
      handleLoad();
    } else {
      window.addEventListener("load", handleLoad, { once: true });
    }

    // Cleanup: remove listener if component unmounts before load
    return () => {
      window.removeEventListener("load", handleLoad);
    };
  }, []);

  // Show loading state while config is being loaded
  if (isLoading) {
    return <LoadingFallback />;
  }

  return (
    <SiteConfigProvider config={config}>
      <Routes>
        <Route element={<SiteLayout showFooter />}>
          <Route path="/" element={<Home />} />
          <Route path="/downloads" element={<Downloads />} />
          <Route path="/blog" element={<Blog />} />
          <Route path="/blog/:slug" element={<BlogPost />} />
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
