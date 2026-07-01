import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchMarketPlugins,
  buildMarketDownloadUrl,
  type MarketPluginEntry,
} from "@/api/modules/pluginMarket";
import { installPlugin } from "@/api/modules/plugin";

/**
 * Derive a compatibility label (e.g. "2.x") from a version string.
 * Handles leading "v", pre-release suffixes, and invalid inputs gracefully.
 */
function deriveCompatLabel(version: string): string | null {
  const trimmed = version.trim().replace(/^v/i, "");
  const match = trimmed.match(/^(\d+)/);
  if (!match) return null;
  return `${match[1]}.x`;
}

export function isMarketPluginCompatible(
  entry: MarketPluginEntry,
  currentVersion: string | null,
): boolean {
  if (!currentVersion) return true;
  const labels = entry.qwenpaw_compat_labels;
  if (!labels || labels.length === 0) return true;
  const label = deriveCompatLabel(currentVersion);
  if (!label) return true; // Cannot parse version → treat as compatible
  return labels.includes(label);
}

interface UseMarketPluginsOptions {
  onInstalled: () => void;
}

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
  const [pageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | undefined>(undefined);
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
        // eslint-disable-next-line no-console
        console.error("[useMarketPlugins] failed to fetch version:", err);
        setQwenpawVersion(null);
      });
    return () => {
      controller.abort();
    };
  }, []);

  const loadPlugins = useCallback(
    async (pageNum: number, keyword: string, cat?: string) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchMarketPlugins({
          page_number: pageNum,
          page_size: pageSize,
          search: keyword || undefined,
          category: cat || undefined,
        });
        setPlugins(data.plugins ?? []);
        setTotal(data.total);
      } catch {
        setError(tRef.current("pluginManager.marketUnavailable"));
        setPlugins([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [pageSize],
  );

  useEffect(() => {
    void loadPlugins(page, search, category);
  }, [page, search, category, loadPlugins]);

  const handleSearch = useCallback((keyword: string) => {
    setSearch(keyword);
    setPage(1);
  }, []);

  const handleCategoryChange = useCallback((cat: string | undefined) => {
    setCategory(cat);
    setPage(1);
  }, []);

  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
  }, []);

  const handleRefresh = useCallback(() => {
    void loadPlugins(page, search, category);
  }, [loadPlugins, page, search, category]);

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
    pageSize,
    category,
    installingId,
    qwenpawVersion,
    isCompatible,
    handleSearch,
    handleCategoryChange,
    handlePageChange,
    handleRefresh,
    handleInstall,
  };
}
