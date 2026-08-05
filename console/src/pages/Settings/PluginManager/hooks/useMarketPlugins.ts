import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchMarketPlugins,
  buildMarketDownloadUrl,
  type MarketPluginEntry,
  type MarketPluginSortBy,
  isMarketPluginApp,
} from "@/api/modules/pluginMarket";
import { installPlugin } from "@/api/modules/plugin";
import { isMarketPluginCompatible } from "@/utils/pluginCompatibility";

export { isMarketPluginCompatible } from "@/utils/pluginCompatibility";

interface UseMarketPluginsOptions {
  onInstalled: () => void;
  /** Restrict this market instance to one category, such as `app`. */
  fixedCategory?: string;
  /** Translation key used for market load failures. */
  unavailableKey?: string;
  /** Translation keys used for install feedback. */
  installSuccessKey?: string;
  installFailedKey?: string;
}

export function useMarketPlugins({
  onInstalled,
  fixedCategory,
  unavailableKey = "pluginManager.marketUnavailable",
  installSuccessKey = "pluginManager.installSuccess",
  installFailedKey = "pluginManager.installFailed",
}: UseMarketPluginsOptions) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const tRef = useRef(t);
  tRef.current = t;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<MarketPluginEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | undefined>(fixedCategory);
  const [sortBy, setSortBy] = useState<MarketPluginSortBy>("downloads");
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [qwenpawVersion, setQwenpawVersion] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/version", { signal: controller.signal })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return res.json();
      })
      .then((data) => {
        const version =
          typeof data === "object" && data !== null ? data.version : null;
        setQwenpawVersion(typeof version === "string" ? version : null);
      })
      .catch((err) => {
        if (err instanceof Error && err.name === "AbortError") {
          return;
        }
        console.error("[useMarketPlugins] failed to fetch version:", err);
        setQwenpawVersion(null);
      });
    return () => {
      controller.abort();
    };
  }, []);

  const loadPlugins = useCallback(
    async (
      pageNum: number,
      keyword: string,
      cat: string | undefined,
      sort: MarketPluginSortBy,
    ) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchMarketPlugins({
          page_number: pageNum,
          page_size: pageSize,
          search: keyword || undefined,
          category: cat || undefined,
          sort_by: sort,
        });
        const entries = data.plugins ?? [];
        setPlugins(
          fixedCategory === "app" ? entries.filter(isMarketPluginApp) : entries,
        );
        setTotal(data.total);
      } catch {
        setError(tRef.current(unavailableKey));
        setPlugins([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [fixedCategory, pageSize, unavailableKey],
  );

  useEffect(() => {
    void loadPlugins(page, search, category, sortBy);
  }, [page, search, category, sortBy, loadPlugins]);

  const handleSearch = useCallback((keyword: string) => {
    setSearch(keyword);
    setPage(1);
  }, []);

  const handleCategoryChange = useCallback((cat: string | undefined) => {
    if (fixedCategory) return;
    setCategory(cat);
    setPage(1);
  }, [fixedCategory]);

  const handleSortChange = useCallback((sort: MarketPluginSortBy) => {
    setSortBy(sort);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
  }, []);

  const handleRefresh = useCallback(() => {
    void loadPlugins(page, search, category, sortBy);
  }, [loadPlugins, page, search, category, sortBy]);

  const isCompatible = useCallback(
    (entry: MarketPluginEntry) =>
      isMarketPluginCompatible(entry, qwenpawVersion),
    [qwenpawVersion],
  );

  const handleInstall = useCallback(
    async (entry: MarketPluginEntry) => {
      setInstallingId(entry.id);
      try {
        const downloadUrl = buildMarketDownloadUrl(entry);
        const result = await installPlugin(downloadUrl, { force: true });
        message.success(
          `${tRef.current(installSuccessKey)}: ${result.name}`,
        );
        onInstalled();
        setTimeout(() => window.location.reload(), 800);
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : tRef.current(installFailedKey);
        message.error(msg);
      } finally {
        setInstallingId(null);
      }
    },
    [installFailedKey, installSuccessKey, message, onInstalled],
  );

  return {
    loading,
    error,
    plugins,
    total,
    page,
    pageSize,
    category,
    sortBy,
    installingId,
    qwenpawVersion,
    isCompatible,
    handleSearch,
    handleCategoryChange,
    handleSortChange,
    handlePageChange,
    handleRefresh,
    handleInstall,
  };
}
