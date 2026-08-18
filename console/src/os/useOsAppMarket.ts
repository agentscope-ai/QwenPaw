import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  buildMarketDownloadUrl,
  fetchMarketPlugins,
  isMarketPluginApp,
  type MarketPluginEntry,
} from "@/api/modules/pluginMarket";
import { installPlugin, type InstallPluginResult } from "@/api/modules/plugin";
import { isMarketPluginCompatible } from "@/utils/pluginCompatibility";

const APP_CATEGORY = "app";
const APP_MARKET_PAGE_SIZE = 20;
const MARKET_REQUEST_PAGE_SIZE = 100;

interface UseOsAppMarketOptions {
  onInstalled: (result: InstallPluginResult) => void | Promise<void>;
}

export function useOsAppMarket({ onInstalled }: UseOsAppMarketOptions) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const tRef = useRef(t);
  tRef.current = t;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [allApps, setAllApps] = useState<MarketPluginEntry[]>([]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [qwenpawVersion, setQwenpawVersion] = useState<string | null>(null);
  const installingIdRef = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/version", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        const version =
          typeof data === "object" && data !== null ? data.version : null;
        setQwenpawVersion(typeof version === "string" ? version : null);
      })
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") return;
        console.error("[useOsAppMarket] failed to fetch version:", err);
        setQwenpawVersion(null);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    const loadApps = async () => {
      setLoading(true);
      setError(null);
      try {
        const entries: MarketPluginEntry[] = [];
        let pageNumber = 1;
        let serverTotal = 0;

        do {
          const data = await fetchMarketPlugins(
            {
              page_number: pageNumber,
              page_size: MARKET_REQUEST_PAGE_SIZE,
              search: search || undefined,
              category: APP_CATEGORY,
              sort_by: "downloads",
            },
            { signal: controller.signal },
          );
          const pageEntries = data.plugins ?? [];
          entries.push(...pageEntries);
          serverTotal = data.total;
          pageNumber += 1;
          if (pageEntries.length === 0) break;
        } while (entries.length < serverTotal);

        if (controller.signal.aborted) return;
        const apps = entries.filter(isMarketPluginApp);
        setAllApps(apps);
        setPage((currentPage) => {
          const lastPage = Math.max(
            1,
            Math.ceil(apps.length / APP_MARKET_PAGE_SIZE),
          );
          return Math.min(currentPage, lastPage);
        });
      } catch (err) {
        if (
          controller.signal.aborted ||
          (err instanceof DOMException && err.name === "AbortError")
        ) {
          return;
        }
        setError(tRef.current("os.appMarketUnavailable"));
        setAllApps([]);
        setPage(1);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    void loadApps();
    return () => controller.abort();
  }, [refreshKey, search]);

  const plugins = useMemo(() => {
    const start = (page - 1) * APP_MARKET_PAGE_SIZE;
    return allApps.slice(start, start + APP_MARKET_PAGE_SIZE);
  }, [allApps, page]);

  const handleSearch = useCallback((keyword: string) => {
    setSearch(keyword);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
  }, []);

  const handleRefresh = useCallback(() => {
    setRefreshKey((current) => current + 1);
  }, []);

  const isCompatible = useCallback(
    (entry: MarketPluginEntry) =>
      isMarketPluginCompatible(entry, qwenpawVersion),
    [qwenpawVersion],
  );

  const handleInstall = useCallback(
    async (entry: MarketPluginEntry) => {
      if (installingIdRef.current !== null) return;
      installingIdRef.current = entry.id;
      setInstallingId(entry.id);
      try {
        const result = await installPlugin(buildMarketDownloadUrl(entry), {
          force: true,
        });
        message.success(`${tRef.current("os.appInstalled")}: ${result.name}`);
        await onInstalled(result);
      } catch (err) {
        message.error(
          err instanceof Error
            ? err.message
            : tRef.current("os.appInstallFailed"),
        );
      } finally {
        installingIdRef.current = null;
        setInstallingId(null);
      }
    },
    [message, onInstalled],
  );

  return {
    loading,
    error,
    plugins,
    total: allApps.length,
    page,
    pageSize: APP_MARKET_PAGE_SIZE,
    installingId,
    qwenpawVersion,
    isCompatible,
    handleSearch,
    handlePageChange,
    handleRefresh,
    handleInstall,
  };
}
