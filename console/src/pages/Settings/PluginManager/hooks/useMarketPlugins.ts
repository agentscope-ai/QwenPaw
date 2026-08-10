import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchMarketPlugins,
  buildMarketDownloadUrl,
  type MarketPluginEntry,
  type MarketPluginSortBy,
} from "@/api/modules/pluginMarket";
import { installPlugin } from "@/api/modules/plugin";
import { isMarketPluginCompatible } from "@/utils/pluginCompatibility";

export { isMarketPluginCompatible } from "@/utils/pluginCompatibility";

interface UseMarketPluginsOptions {
  onInstalled: () => void;
}

const MARKET_PAGE_SIZE = 20;

export type MarketPluginHighlightFilter = "featured" | "trending" | undefined;

export function useMarketPlugins({ onInstalled }: UseMarketPluginsOptions) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const tRef = useRef(t);
  tRef.current = t;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<MarketPluginEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [highlightFilter, setHighlightFilter] =
    useState<MarketPluginHighlightFilter>(undefined);
  const [sortBy, setSortBy] = useState<MarketPluginSortBy>("downloads");
  const [loadingMore, setLoadingMore] = useState(false);
  const [autoLoadBlocked, setAutoLoadBlocked] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [qwenpawVersion, setQwenpawVersion] = useState<string | null>(null);
  const loadingMoreRef = useRef(false);
  const requestControllerRef = useRef<AbortController | null>(null);

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
      highlight: MarketPluginHighlightFilter,
      sort: MarketPluginSortBy,
      append: boolean,
      signal: AbortSignal,
    ) => {
      if (append) {
        loadingMoreRef.current = true;
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);
      try {
        const highlightParams: {
          is_featured?: boolean;
          is_trending?: boolean;
        } = {};
        if (highlight === "featured") {
          highlightParams.is_featured = true;
        } else if (highlight === "trending") {
          highlightParams.is_trending = true;
        }
        const data = await fetchMarketPlugins(
          {
            page_number: pageNum,
            page_size: MARKET_PAGE_SIZE,
            search: keyword || undefined,
            category: cat || undefined,
            sort_by: sort,
            ...highlightParams,
          },
          { signal },
        );
        if (signal.aborted) return;
        const pageEntries = data.plugins ?? [];
        setPlugins((current) =>
          append ? [...current, ...pageEntries] : pageEntries,
        );
        setTotal(data.total);
        setPage(pageNum);
        if (append) setAutoLoadBlocked(false);
      } catch (err) {
        if (
          signal.aborted ||
          (err instanceof DOMException && err.name === "AbortError")
        ) {
          return;
        }
        setError(tRef.current("pluginManager.marketUnavailable"));
        if (append) {
          setAutoLoadBlocked(true);
        } else {
          setPlugins([]);
          setTotal(0);
          setPage(1);
        }
      } finally {
        if (!signal.aborted) {
          if (append) {
            loadingMoreRef.current = false;
            setLoadingMore(false);
          } else {
            setLoading(false);
          }
        }
      }
    },
    [],
  );

  useEffect(() => {
    requestControllerRef.current?.abort();
    loadingMoreRef.current = false;
    setLoadingMore(false);
    setAutoLoadBlocked(false);
    const controller = new AbortController();
    requestControllerRef.current = controller;
    void loadPlugins(
      1,
      search,
      category,
      highlightFilter,
      sortBy,
      false,
      controller.signal,
    );
    return () => {
      controller.abort();
      requestControllerRef.current?.abort();
    };
  }, [category, highlightFilter, loadPlugins, refreshKey, search, sortBy]);

  const handleSearch = useCallback((keyword: string) => {
    setSearch(keyword);
  }, []);

  const handleCategoryChange = useCallback((cat: string | undefined) => {
    setCategory(cat);
    setHighlightFilter(undefined);
  }, []);

  const handleHighlightFilterChange = useCallback(
    (filter: MarketPluginHighlightFilter) => {
      setHighlightFilter(filter);
      setCategory(undefined);
    },
    [],
  );

  const handleSortChange = useCallback((sort: MarketPluginSortBy) => {
    setSortBy(sort);
  }, []);

  const handleRefresh = useCallback(() => {
    setRefreshKey((current) => current + 1);
  }, []);

  const loadNextPage = useCallback(
    (retryBlocked = false) => {
      if (
        loading ||
        loadingMoreRef.current ||
        (!retryBlocked && autoLoadBlocked) ||
        plugins.length >= total
      ) {
        return;
      }
      loadingMoreRef.current = true;
      const controller = new AbortController();
      requestControllerRef.current = controller;
      void loadPlugins(
        page + 1,
        search,
        category,
        highlightFilter,
        sortBy,
        true,
        controller.signal,
      ).finally(() => {
        if (requestControllerRef.current === controller) {
          requestControllerRef.current = null;
        }
      });
    },
    [
      autoLoadBlocked,
      category,
      highlightFilter,
      loadPlugins,
      loading,
      page,
      plugins.length,
      search,
      sortBy,
      total,
    ],
  );

  const handleLoadMore = useCallback(() => {
    loadNextPage();
  }, [loadNextPage]);

  const handleRetryLoadMore = useCallback(() => {
    setAutoLoadBlocked(false);
    loadNextPage(true);
  }, [loadNextPage]);

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
          `${tRef.current("pluginManager.installSuccess")}: ${result.name}`,
        );
        onInstalled();
        setTimeout(() => window.location.reload(), 800);
      } catch (err) {
        const msg =
          err instanceof Error
            ? err.message
            : tRef.current("pluginManager.installFailed");
        message.error(msg);
      } finally {
        setInstallingId(null);
      }
    },
    [message, onInstalled],
  );

  return {
    loading,
    error,
    plugins,
    total,
    page,
    pageSize: MARKET_PAGE_SIZE,
    category,
    highlightFilter,
    sortBy,
    loadingMore,
    hasMore: plugins.length < total,
    autoLoadBlocked,
    installingId,
    qwenpawVersion,
    isCompatible,
    handleSearch,
    handleCategoryChange,
    handleHighlightFilterChange,
    handleSortChange,
    handleRefresh,
    handleLoadMore,
    handleRetryLoadMore,
    handleInstall,
  };
}
