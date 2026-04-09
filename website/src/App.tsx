import { lazy, useEffect, useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { loadSiteConfig, type SiteConfig, defaultConfig } from "@/config";
import { SiteConfigProvider } from "@/config-context";
import { SiteLayout } from "@/components/SiteLayout";
import "@/index.css";

const GA_ID = "G-BEX1XSB9KE";

// Lazy load page components for better performance
const Home = lazy(() => import("@/pages/Home"));
const Docs = lazy(() => import("@/pages/Docs"));
const ReleaseNotes = lazy(() => import("@/pages/ReleaseNotes"));
const Downloads = lazy(() => import("@/pages/Downloads"));

declare global {
  interface Window {
    dataLayer: unknown[];
    gtag?: (...args: unknown[]) => void;
  }
}

/**
 * Load Google Analytics script asynchronously
 * @param id - Google Analytics measurement ID
 */
function loadGoogleAnalytics(id: string) {
  // Skip if already loaded or in development
  if (window.gtag || import.meta.env.DEV) {
    if (import.meta.env.DEV) {
      console.log("[GA] Skipped in development environment");
    }
    return;
  }

  console.log("[GA] Starting to load Google Analytics...");

  // Initialize dataLayer
  window.dataLayer = window.dataLayer || [];
  function gtag(...args: unknown[]) {
    window.dataLayer.push(args);
  }
  window.gtag = gtag;

  // Configure GA
  gtag("js", new Date());
  gtag("config", id);

  // Load GA script with timeout protection
  const script = document.createElement("script");
  script.src = `https://www.googletagmanager.com/gtag/js?id=${id}`;
  script.async = true;

  let isLoaded = false;
  const timeoutId = setTimeout(() => {
    if (!isLoaded) {
      console.warn("[GA] Load timeout - removing script");
      script.remove();
      delete window.gtag;
    }
  }, 6000);

  script.onload = () => {
    isLoaded = true;
    clearTimeout(timeoutId);
    console.log("[GA] Loaded successfully");
  };

  script.onerror = () => {
    isLoaded = true;
    clearTimeout(timeoutId);
    console.warn("[GA] Failed to load (may be blocked)");
    delete window.gtag;
  };

  document.head.appendChild(script);
}

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
