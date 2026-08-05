/**
 * AppMarket.tsx — Official/community market views for the App Center.
 *
 * Reuses the existing plugin-market proxy (`/plugins/market/search`) and the
 * `installPlugin` flow, filtered to UI extensions (category "app") so the
 * market surfaces installable PawApps. The current market contract uses
 * `is_featured` to separate official apps from community apps.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Spin,
  Typography,
} from "antd";
import {
  AppWindow,
  Download,
  ExternalLink,
  Search,
  Sparkles,
} from "lucide-react";
import { useAppMessage } from "@/hooks/useAppMessage";
import { openExternalLink } from "@/utils/openExternalLink";
import {
  buildMarketDownloadUrl,
  fetchMarketPlugins,
  type MarketPluginEntry,
} from "@/api/modules/pluginMarket";
import { installPlugin } from "@/api/modules/plugin";
import { rootApi } from "@/api/modules/root";
import { isMarketPluginCompatible } from "@/utils/pluginCompatibility";
import styles from "./index.module.less";

const { Text, Paragraph } = Typography;

const APP_CATEGORY = "app";
const MARKET_PAGE_SIZE = 100;

function pickDescription(entry: MarketPluginEntry, language: string): string {
  const locales = entry.locales;
  if (!locales || Object.keys(locales).length === 0) return "";
  if (locales[language]) return locales[language].description;
  const prefix = language.split("-")[0].toLowerCase();
  for (const key of Object.keys(locales)) {
    if (key.toLowerCase().startsWith(prefix)) return locales[key].description;
  }
  if (locales.en) return locales.en.description;
  return Object.values(locales)[0]?.description ?? "";
}

interface AppMarketProps {
  onInstalled: () => void | Promise<void>;
  channel?: "official" | "community";
}

export function AppMarket({
  onInstalled,
  channel = "community",
}: AppMarketProps) {
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const tRef = useRef(t);
  tRef.current = t;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<MarketPluginEntry[]>([]);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [qwenpawVersion, setQwenpawVersion] = useState<string | null>(null);
  const [versionChecked, setVersionChecked] = useState(false);
  const installingIdRef = useRef<string | null>(null);

  const load = useCallback(
    async (keyword: string, signal: AbortSignal) => {
      setLoading(true);
      setError(null);
      try {
        const entries: MarketPluginEntry[] = [];
        let pageNumber = 1;
        let total = 0;

        do {
          const data = await fetchMarketPlugins(
            {
              page_number: pageNumber,
              page_size: MARKET_PAGE_SIZE,
              search: keyword || undefined,
              category: APP_CATEGORY,
            },
            { signal },
          );
          const pageEntries = data.plugins ?? [];
          entries.push(...pageEntries);
          total = data.total;
          pageNumber += 1;
          if (pageEntries.length === 0) break;
        } while (entries.length < total);

        if (signal.aborted) return;
        setPlugins(
          entries.filter((entry) =>
            channel === "official"
              ? entry.is_featured === true
              : entry.is_featured !== true,
          ),
        );
      } catch (err) {
        if (
          signal.aborted ||
          (err instanceof DOMException && err.name === "AbortError")
        ) {
          return;
        }
        setError(
          tRef.current(
            "pluginManager.marketUnavailable",
            "App market is currently unavailable.",
          ),
        );
        setPlugins([]);
      } finally {
        if (!signal.aborted) setLoading(false);
      }
    },
    [channel],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(search, controller.signal);
    return () => controller.abort();
  }, [search, load]);

  useEffect(() => {
    const controller = new AbortController();
    void rootApi
      .getVersion(controller.signal)
      .then(({ version }) => setQwenpawVersion(version))
      .catch((err) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          setQwenpawVersion(null);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setVersionChecked(true);
      });
    return () => controller.abort();
  }, []);

  const handleInstall = useCallback(
    async (entry: MarketPluginEntry) => {
      if (installingIdRef.current !== null) return;
      installingIdRef.current = entry.id;
      setInstallingId(entry.id);

      // Show loading message
      const loadingKey = `install-${entry.id}`;
      message.loading({
        content: `${tRef.current("appCenter.installing", "正在安装")}: ${
          entry.display_name
        }...`,
        key: loadingKey,
        duration: 0,
      });

      try {
        const result = await installPlugin(buildMarketDownloadUrl(entry), {
          force: true,
        });
        message.success({
          content: `${tRef.current("appCenter.installSuccess", "安装成功")}: ${
            result.name
          }`,
          key: loadingKey,
        });
        await onInstalled();
      } catch (err) {
        message.error({
          content:
            err instanceof Error
              ? err.message
              : tRef.current("appCenter.installFailed", "安装失败"),
          key: loadingKey,
        });
      } finally {
        installingIdRef.current = null;
        setInstallingId(null);
      }
    },
    [message, onInstalled],
  );

  const requestInstall = useCallback(
    (entry: MarketPluginEntry) => {
      if (installingIdRef.current !== null) return;
      if (isMarketPluginCompatible(entry, qwenpawVersion)) {
        void handleInstall(entry);
        return;
      }

      Modal.confirm({
        title: tRef.current(
          "pluginManager.compatWarningTitle",
          "Compatibility Warning",
        ),
        content: tRef.current("pluginManager.compatWarningContent", {
          defaultValue:
            "This plugin is labeled for QwenPaw {{labels}}. Your QwenPaw version is {{version}}. Installing it may cause errors. Are you sure you want to continue?",
          labels: entry.qwenpaw_compat_labels?.join(", ") ?? "unknown",
          version: qwenpawVersion ?? "unknown",
        }),
        okText: tRef.current(
          "pluginManager.compatWarningConfirm",
          "Install anyway",
        ),
        cancelText: tRef.current("common.cancel", "Cancel"),
        onOk: () => handleInstall(entry),
      });
    },
    [handleInstall, qwenpawVersion],
  );

  const lang = i18n.language;

  const isOfficial = channel === "official";
  const searchLabel = isOfficial
    ? t("appCenter.searchOfficial", "Search official apps...")
    : t("appCenter.searchMarket", "Search app market...");

  return (
    <div>
      <div className={styles.toolbar}>
        <Input
          prefix={<Search size={14} />}
          placeholder={searchLabel}
          aria-label={searchLabel}
          value={searchInput}
          onChange={(e) => {
            setSearchInput(e.target.value);
            if (!e.target.value) setSearch("");
          }}
          onPressEnter={() => setSearch(searchInput)}
          className={styles.searchInput}
          allowClear
        />
      </div>

      {error && (
        <Alert
          type="warning"
          showIcon
          message={error}
          style={{ marginBottom: 16 }}
        />
      )}

      <Spin spinning={loading}>
        {!loading && plugins.length === 0 && !error ? (
          <Empty
            image={<AppWindow size={44} strokeWidth={1} />}
            description={
              isOfficial
                ? t("appCenter.officialAppsEmpty", "No official apps found")
                : t("appCenter.marketEmpty", "No apps found")
            }
            className={styles.stateBlock}
          />
        ) : (
          <div className={styles.grid}>
            {plugins.map((entry) => (
              <Card key={entry.id} className={styles.appCard}>
                <div className={styles.cardIcon}>
                  {entry.logo_url ? (
                    <img
                      src={entry.logo_url}
                      alt=""
                      className={styles.marketLogo}
                    />
                  ) : (
                    <AppWindow size={22} strokeWidth={1.75} />
                  )}
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.cardHeader}>
                    <Text strong className={styles.cardTitle} ellipsis>
                      {entry.display_name}
                    </Text>
                    {isOfficial && (
                      <span className={styles.featuredTag}>
                        <Sparkles size={11} strokeWidth={2} />
                        {t("appCenter.featured", "精选")}
                      </span>
                    )}
                  </div>
                  <Paragraph
                    type="secondary"
                    className={styles.cardDesc}
                    ellipsis={{ rows: 2 }}
                  >
                    {pickDescription(entry, lang) ||
                      t("appCenter.noDescription", "No description")}
                  </Paragraph>
                  <span className={styles.cardMeta}>
                    v{entry.version}
                    {entry.developer ? ` · ${entry.developer}` : ""}
                    {entry.downloads != null && (
                      <span className={styles.metaDownloads}>
                        <Download size={12} strokeWidth={2} />
                        {entry.downloads}
                      </span>
                    )}
                  </span>
                  <div className={styles.cardActions}>
                    <Button
                      type="primary"
                      size="small"
                      icon={<Download size={14} />}
                      loading={installingId === entry.id}
                      disabled={
                        !versionChecked ||
                        (installingId !== null && installingId !== entry.id)
                      }
                      onClick={() => requestInstall(entry)}
                    >
                      {installingId === entry.id
                        ? t("appCenter.installing", "安装中...")
                        : t("appCenter.install", "安装")}
                    </Button>
                    {entry.details_url && (
                      <Button
                        size="small"
                        icon={<ExternalLink size={14} />}
                        onClick={() => openExternalLink(entry.details_url!)}
                      >
                        {t("appCenter.details", "详情")}
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Spin>
    </div>
  );
}
