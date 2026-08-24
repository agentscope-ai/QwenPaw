/**
 * AppMarket.tsx — App market view for the App Center.
 *
 * Reuses the existing plugin-market proxy (`/plugins/market/search`) and the
 * `installPlugin` flow, filtered to UI extensions (category "app") so the
 * market surfaces installable PawApps.
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
  BadgeCheck,
  Download,
  ExternalLink,
  RefreshCw,
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
import { installPlugin, type InstallPluginResult } from "@/api/modules/plugin";
import { rootApi } from "@/api/modules/root";
import { isMarketPluginCompatible } from "@/utils/pluginCompatibility";
import { getMarketAppState, type MarketAppState } from "@/utils/marketAppState";
import styles from "./index.module.less";

const { Text, Paragraph } = Typography;

const APP_CATEGORY = "app";
const MARKET_PAGE_SIZE = 20;

type AppMarketFilter = "all" | "featured" | "trending";

function LoadMoreSentinel({ onVisible }: { onVisible: () => void }) {
  const { t } = useTranslation();
  const nodeRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = nodeRef.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onVisible();
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible]);

  return (
    <div ref={nodeRef} className={styles.sentinel}>
      {t("common.loading", "加载中...")}
    </div>
  );
}

// Curated featured apps use pinned artwork because the market API may not
// provide an icon for them.
const FEATURED_APP_ICONS: Record<string, string> = {
  "@agentscope/qwenpaw-creator": "/creator-logo.png",
};
// Emoji icons from the plugins' own plugin.json (the market API carries no
// icon field), so uninstalled cards match what the installed view shows.
const FEATURED_APP_EMOJIS: Record<string, string> = {
  "@zhijianma/agent-kanban": "📋",
};
// The upstream market entry ships the same English text under every locale
// key, so curated apps carry their real translations here (keyed by language
// prefix). Falls back to the upstream locales for everything else.
const FEATURED_APP_DESCRIPTIONS: Record<string, Record<string, string>> = {
  "@agentscope/qwenpaw-creator": {
    zh: "Agentic 视频创作平台。从一句创意生成短剧，或将已有素材剪成成片：编剧、导演、视觉、动效、剪辑等 Agent 协同完成策划、生成、剪辑与合成；项目中所见皆可选中交给 Agent 精准修改，每个关键决定都由你确认。",
    en: "An agentic video creation platform. Start from an idea or existing footage: an Agent team of screenwriting, directing, visual, motion, and editing Specialists handles planning, generation, editing, and composition; select anything in the project and hand it to the Agent for a precise change, with every key decision staying in your hands.",
  },
  "@zhijianma/agent-kanban": {
    zh: "一个看板应用：创建任务并分配给智能体，由指定智能体自动执行，并实时查看其输出流。",
    en: "A Kanban board to create issues, assign them to agents, auto-run them via the assigned agent, and watch their output stream in real time.",
  },
};

function pickDescription(entry: MarketPluginEntry, language: string): string {
  const curated = FEATURED_APP_DESCRIPTIONS[entry.id];
  if (curated) {
    const prefix = language.split("-")[0].toLowerCase();
    if (curated[prefix]) return curated[prefix];
    if (curated.en) return curated.en;
  }
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
  onInstalled: (result: InstallPluginResult) => void | Promise<void>;
  installedAppVersions?: ReadonlyMap<string, string>;
  channel?: "official" | "community";
}

const EMPTY_INSTALLED_APP_VERSIONS: ReadonlyMap<string, string> = new Map();

export function AppMarket({
  onInstalled,
  installedAppVersions = EMPTY_INSTALLED_APP_VERSIONS,
  channel = "community",
}: AppMarketProps) {
  const { t, i18n } = useTranslation();
  const { message } = useAppMessage();
  const tRef = useRef(t);
  tRef.current = t;

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<MarketPluginEntry[]>([]);
  const [filter, setFilter] = useState<AppMarketFilter>("all");
  const [refreshKey, setRefreshKey] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [autoLoadBlocked, setAutoLoadBlocked] = useState(false);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [qwenpawVersion, setQwenpawVersion] = useState<string | null>(null);
  const [versionChecked, setVersionChecked] = useState(false);
  const installingIdRef = useRef<string | null>(null);
  const loadingMoreRef = useRef(false);
  const loadMoreControllerRef = useRef<AbortController | null>(null);

  const load = useCallback(
    async (
      nextPage: number,
      keyword: string,
      selectedFilter: AppMarketFilter,
      signal: AbortSignal,
      append: boolean,
    ) => {
      if (append) {
        loadingMoreRef.current = true;
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      setError(null);
      try {
        const requestFilter =
          channel === "official" || selectedFilter === "featured"
            ? { is_featured: true as const }
            : selectedFilter === "trending"
            ? { is_trending: true as const }
            : {};
        const data = await fetchMarketPlugins(
          {
            page_number: nextPage,
            page_size: MARKET_PAGE_SIZE,
            search: keyword || undefined,
            category: APP_CATEGORY,
            ...requestFilter,
          },
          { signal },
        );

        if (signal.aborted) return;
        const pageEntries = data.plugins ?? [];
        setPlugins((current) =>
          append ? [...current, ...pageEntries] : pageEntries,
        );
        setPageNumber(nextPage);
        setTotal(data.total);
        if (append) setAutoLoadBlocked(false);
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
        if (!append) {
          setPlugins([]);
          setPageNumber(1);
          setTotal(0);
        } else {
          setAutoLoadBlocked(true);
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
    [channel],
  );

  useEffect(() => {
    loadMoreControllerRef.current?.abort();
    loadingMoreRef.current = false;
    setLoadingMore(false);
    setAutoLoadBlocked(false);
    const controller = new AbortController();
    void load(1, search, filter, controller.signal, false);
    return () => controller.abort();
  }, [filter, refreshKey, search, load]);

  useEffect(
    () => () => {
      loadMoreControllerRef.current?.abort();
    },
    [],
  );

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
        await onInstalled(result);
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

  const loadNextPage = useCallback(() => {
    if (loading || loadingMoreRef.current || plugins.length >= total) return;
    loadingMoreRef.current = true;
    const controller = new AbortController();
    loadMoreControllerRef.current = controller;
    void load(pageNumber + 1, search, filter, controller.signal, true).finally(
      () => {
        if (loadMoreControllerRef.current === controller) {
          loadMoreControllerRef.current = null;
        }
      },
    );
  }, [filter, load, loading, pageNumber, plugins.length, search, total]);

  const handleAutoLoadMore = useCallback(() => {
    if (autoLoadBlocked) return;
    loadNextPage();
  }, [autoLoadBlocked, loadNextPage]);

  const handleRetryLoadMore = useCallback(() => {
    setAutoLoadBlocked(false);
    loadNextPage();
  }, [loadNextPage]);

  const lang = i18n.language;

  const isOfficial = channel === "official";
  const searchLabel = isOfficial
    ? t("appCenter.searchOfficial", "Search official apps...")
    : t("appCenter.searchMarket", "Search app market...");
  const hasMore = plugins.length < total;
  const searchControl = (
    <Input
      prefix={<Search size={14} />}
      placeholder={searchLabel}
      aria-label={searchLabel}
      value={searchInput}
      onChange={(event) => {
        setSearchInput(event.target.value);
        if (!event.target.value) setSearch("");
      }}
      onPressEnter={() => setSearch(searchInput)}
      className={styles.searchInput}
      allowClear
    />
  );

  return (
    <div>
      {isOfficial ? (
        <div className={styles.toolbar}>{searchControl}</div>
      ) : (
        <div className={styles.marketFilterBar}>
          {searchControl}
          <div
            className={styles.marketFilterOptions}
            role="group"
            aria-label={t("appCenter.marketFilters", "应用市场筛选")}
          >
            {(
              [
                ["all", t("appCenter.filterAll", "全部")],
                ["featured", t("appCenter.featured", "精选")],
                ["trending", t("appCenter.trending", "热门")],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`${styles.marketFilter} ${
                  filter === value ? styles.marketFilterActive : ""
                }`}
                aria-pressed={filter === value}
                disabled={loading || loadingMore}
                onClick={() => setFilter(value)}
              >
                {label}
              </button>
            ))}
          </div>
          <div className={styles.marketFilterActions}>
            <Button
              type="default"
              className={styles.refreshBtn}
              icon={<RefreshCw size={14} />}
              onClick={() => setRefreshKey((current) => current + 1)}
              disabled={loading || loadingMore}
              aria-label={t("common.refresh", "Refresh")}
              title={t("common.refresh", "Refresh")}
            />
          </div>
        </div>
      )}

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
          <>
            <div className={styles.grid}>
              {plugins.map((entry) => {
                const iconSrc = entry.logo_url || FEATURED_APP_ICONS[entry.id];
                const marketState: MarketAppState = getMarketAppState(
                  entry,
                  installedAppVersions,
                  channel,
                );
                const isInstalled = marketState === "installed";
                const canUpdate = marketState === "update";
                return (
                  <Card key={entry.id} className={styles.appCard}>
                    <div className={styles.cardIcon}>
                      {iconSrc ? (
                        <img
                          src={iconSrc}
                          alt=""
                          className={styles.marketLogo}
                        />
                      ) : FEATURED_APP_EMOJIS[entry.id] ? (
                        <span className={styles.cardIconEmoji} aria-hidden>
                          {FEATURED_APP_EMOJIS[entry.id]}
                        </span>
                      ) : (
                        <AppWindow size={24} strokeWidth={1.75} />
                      )}
                    </div>
                    <div className={styles.cardBody}>
                      <div className={styles.cardHeader}>
                        <Text strong className={styles.cardTitle} ellipsis>
                          {entry.display_name}
                        </Text>
                        <span className={styles.versionBadge}>
                          v{entry.version}
                        </span>
                        {entry.is_featured === true && (
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
                      <div className={styles.cardFooter}>
                        <span className={styles.cardMeta}>
                          {entry.developer || entry.owner || ""}
                        </span>
                        {entry.downloads != null && (
                          <span className={styles.metaDownloads}>
                            <Download size={12} strokeWidth={2} />
                            {entry.downloads}
                          </span>
                        )}
                      </div>
                      <div
                        className={`${styles.cardActions} ${styles.cardHoverActions}`}
                      >
                        <Button
                          type={isInstalled ? "default" : "primary"}
                          icon={
                            isInstalled ? (
                              <BadgeCheck size={14} />
                            ) : canUpdate ? (
                              <RefreshCw size={14} />
                            ) : (
                              <Download size={14} />
                            )
                          }
                          loading={!isInstalled && installingId === entry.id}
                          disabled={
                            isInstalled ||
                            !versionChecked ||
                            (installingId !== null && installingId !== entry.id)
                          }
                          onClick={() => requestInstall(entry)}
                        >
                          {isInstalled
                            ? t("appCenter.installedStatus", "Installed")
                            : canUpdate
                            ? t("appCenter.update", "Update")
                            : installingId === entry.id
                            ? t("appCenter.installing", "安装中...")
                            : t("appCenter.install", "安装")}
                        </Button>
                        <Button
                          icon={<ExternalLink size={14} />}
                          disabled={!entry.details_url}
                          onClick={() => {
                            if (entry.details_url) {
                              void openExternalLink(entry.details_url);
                            }
                          }}
                        >
                          {t("appCenter.details", "详情")}
                        </Button>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
            {!loading && plugins.length > 0 && (
              <div className={styles.loadMoreRow}>
                {hasMore && autoLoadBlocked ? (
                  <Button onClick={handleRetryLoadMore} loading={loadingMore}>
                    {t("appCenter.loadMore", "加载更多")}
                  </Button>
                ) : hasMore ? (
                  <LoadMoreSentinel
                    key={plugins.length}
                    onVisible={handleAutoLoadMore}
                  />
                ) : (
                  <span className={styles.noMoreText}>
                    {t("appCenter.noMoreApps", "没有更多应用了")}
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </Spin>
    </div>
  );
}
