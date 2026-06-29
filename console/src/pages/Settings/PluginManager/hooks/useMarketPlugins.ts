import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchMarketPlugins,
  buildMarketDownloadUrl,
  getQwenPawCompatLabel,
  type MarketPluginEntry,
} from "@/api/modules/pluginMarket";
import { installPlugin } from "@/api/modules/plugin";
import { rootApi } from "@/api/modules/root";

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
  const [qwenpawVersion, setQwenpawVersion] = useState<string>("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [installingId, setInstallingId] = useState<string | null>(null);

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
        const compatLabel = qwenpawVersion
          ? getQwenPawCompatLabel(qwenpawVersion)
          : null;
        const compatiblePlugins = (data.plugins ?? []).filter((entry) => {
          // Entries without compatibility labels are treated as
          // compatible with all versions for backward compatibility.
          if (!compatLabel || !entry.qwenpaw_compat_labels?.length) {
            return true;
          }
          return entry.qwenpaw_compat_labels.includes(compatLabel);
        });
        setPlugins(compatiblePlugins);
        setTotal(data.total);
      } catch {
        setError(tRef.current("pluginManager.marketUnavailable"));
        setPlugins([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [pageSize, qwenpawVersion],
  );

  useEffect(() => {
    void loadPlugins(page, search, category);
  }, [page, search, category, loadPlugins]);

  useEffect(() => {
    rootApi
      .getVersion()
      .then((res) => setQwenpawVersion(res?.version ?? ""))
      .catch(() => {});
  }, []);

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

  const handleInstall = useCallback(
    async (entry: MarketPluginEntry) => {
      setInstallingId(entry.id);
      try {
        const downloadUrl = buildMarketDownloadUrl(entry, qwenpawVersion);
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
    [message, onInstalled, qwenpawVersion],
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
    handleSearch,
    handleCategoryChange,
    handlePageChange,
    handleRefresh,
    handleInstall,
  };
}
