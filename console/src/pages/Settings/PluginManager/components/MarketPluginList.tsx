import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Modal,
  Select,
  Spin,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { Download, ExternalLink, Package, RefreshCw } from "lucide-react";
import type {
  MarketPluginEntry,
  MarketPluginSortBy,
} from "@/api/modules/pluginMarket";
import { useIsMobile } from "@/hooks/useIsMobile";
import { openExternalLink } from "@/utils/openExternalLink";
import { useMarketPlugins } from "../hooks/useMarketPlugins";
import { PluginViewToggle } from "./PluginViewToggle";
import styles from "./OfficialPluginList.module.less";
import marketStyles from "./MarketPluginList.module.less";
import toolbarStyles from "./PluginListToolbar.module.less";

const { Text } = Typography;

const PLUGIN_CATEGORIES = [
  { code: "app", zh: "应用", en: "App" },
  { code: "agent-tool", zh: "Agent 工具", en: "Agent Tool" },
  { code: "provider", zh: "模型接入", en: "Provider" },
  { code: "command", zh: "Slash 命令", en: "Slash Command" },
  { code: "hook", zh: "生命周期 Hook", en: "Lifecycle Hook" },
  { code: "frontend", zh: "UI 扩展", en: "UI Extension" },
  { code: "general", zh: "通用插件", en: "General" },
];

const MARKET_SORT_OPTIONS: Array<{
  value: MarketPluginSortBy;
  labelKey: string;
}> = [
  { value: "downloads", labelKey: "pluginManager.marketSortDownloads" },
  { value: "updated_time", labelKey: "pluginManager.marketSortUpdated" },
  { value: "fauvarate", labelKey: "pluginManager.marketSortFavorites" },
];

function LoadMoreSentinel({
  loading,
  onVisible,
}: {
  loading: boolean;
  onVisible: () => void;
}) {
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
    <div ref={nodeRef} className={marketStyles.loadMoreSentinel}>
      {loading && <Spin size="small" />}
    </div>
  );
}

function pickLocalizedDescription(
  entry: MarketPluginEntry,
  language: string,
): string {
  const locales = entry.locales;
  if (!locales || Object.keys(locales).length === 0) return "";

  if (locales[language]) return locales[language].description;

  const prefix = language.split("-")[0].toLowerCase();
  for (const key of Object.keys(locales)) {
    if (key.toLowerCase().startsWith(prefix)) {
      return locales[key].description;
    }
  }

  if (locales.en) return locales.en.description;

  const first = Object.values(locales)[0];
  return first?.description ?? "";
}

interface MarketPluginListProps {
  onInstalled: () => void;
}

export function MarketPluginList({ onInstalled }: MarketPluginListProps) {
  const { t, i18n } = useTranslation();
  const [searchInput, setSearchInput] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const isMobile = useIsMobile();

  const {
    loading,
    error,
    plugins,
    total,
    category,
    highlightFilter,
    sortBy,
    loadingMore,
    hasMore,
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
  } = useMarketPlugins({ onInstalled });

  const lang = i18n.language.split("-")[0].toLowerCase();

  const onSearch = (val: string) => {
    setActiveSearch(val);
    handleSearch(val);
  };

  const onCategoryClick = (code: string | null) => {
    handleCategoryChange(code || undefined);
  };

  const requestInstall = (entry: MarketPluginEntry) => {
    if (!isCompatible(entry)) {
      Modal.confirm({
        title: t("pluginManager.compatWarningTitle", "Compatibility Warning"),
        content: t("pluginManager.compatWarningContent", {
          defaultValue:
            "This plugin is labeled for QwenPaw {{labels}}. Your QwenPaw version is {{version}}. Installing it may cause errors. Are you sure you want to continue?",
          labels: entry.qwenpaw_compat_labels?.join(", ") ?? "unknown",
          version: qwenpawVersion ?? "unknown",
        }),
        okText: t("pluginManager.compatWarningConfirm", "Install anyway"),
        cancelText: t("common.cancel", "Cancel"),
        onOk: () => void handleInstall(entry),
      });
      return;
    }
    void handleInstall(entry);
  };

  const renderInstallButton = (entry: MarketPluginEntry) => (
    <Tooltip
      title={
        !isCompatible(entry)
          ? `This plugin is labeled for QwenPaw ${
              entry.qwenpaw_compat_labels?.join(", ") ?? "unknown"
            }; compatibility with QwenPaw ${
              qwenpawVersion ?? "unknown"
            } is unverified.`
          : undefined
      }
    >
      <Button
        type="primary"
        icon={<Download size={14} />}
        loading={installingId === entry.id}
        disabled={installingId !== null && installingId !== entry.id}
        onClick={() => requestInstall(entry)}
      >
        {t("pluginManager.catalogInstall")}
      </Button>
    </Tooltip>
  );

  const renderCategoryTag = (entry: MarketPluginEntry) => {
    const categoryLabel = entry.locales?.[lang]?.category;
    return categoryLabel ? (
      <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>
        {categoryLabel}
      </Tag>
    ) : null;
  };

  const renderCompatibilityTag = (entry: MarketPluginEntry) =>
    entry.qwenpaw_compat_labels?.length ? (
      <Tag
        color={isCompatible(entry) ? "green" : "orange"}
        style={{ margin: 0, fontSize: 11 }}
      >
        {`QwenPaw ${entry.qwenpaw_compat_labels.join(", ")}`}
      </Tag>
    ) : null;

  return (
    <div className={styles.catalogSection}>
      <div className={toolbarStyles.filterRow}>
        <button
          type="button"
          className={`${toolbarStyles.filterTag} ${
            !category && !highlightFilter ? toolbarStyles.filterTagActive : ""
          }`}
          onClick={() => onCategoryClick(null)}
        >
          {t("pluginManager.marketAll")}
        </button>
        {(
          [
            ["featured", t("pluginManager.marketFeatured")],
            ["trending", t("pluginManager.marketTrending")],
          ] as const
        ).map(([value, label]) => (
          <button
            type="button"
            key={value}
            className={`${toolbarStyles.filterTag} ${
              highlightFilter === value ? toolbarStyles.filterTagActive : ""
            }`}
            aria-pressed={highlightFilter === value}
            onClick={() => handleHighlightFilterChange(value)}
          >
            {label}
          </button>
        ))}
        {PLUGIN_CATEGORIES.map((cat) => (
          <button
            type="button"
            key={cat.code}
            className={`${toolbarStyles.filterTag} ${
              category === cat.code ? toolbarStyles.filterTagActive : ""
            }`}
            onClick={() => onCategoryClick(cat.code)}
          >
            {lang === "zh" ? cat.zh : cat.en}
          </button>
        ))}
      </div>
      <div className={toolbarStyles.controlRow}>
        <Input.Search
          className={toolbarStyles.search}
          placeholder={t("pluginManager.marketSearch")}
          allowClear
          value={searchInput}
          onChange={(e) => {
            setSearchInput(e.target.value);
            if (!e.target.value) onSearch("");
          }}
          onSearch={onSearch}
        />
        <div className={toolbarStyles.controlActions}>
          <Select<MarketPluginSortBy>
            className={toolbarStyles.sort}
            aria-label={t("pluginManager.marketSortLabel")}
            value={sortBy}
            onChange={handleSortChange}
            options={MARKET_SORT_OPTIONS.map((option) => ({
              value: option.value,
              label: t(option.labelKey),
            }))}
          />
          <Button
            type="default"
            className={toolbarStyles.iconButton}
            icon={<RefreshCw size={14} />}
            onClick={handleRefresh}
            disabled={loading}
            aria-label={t("pluginManager.catalogRefresh")}
            title={t("pluginManager.catalogRefresh")}
          />
          {!isMobile && (
            <PluginViewToggle value={viewMode} onChange={setViewMode} />
          )}
        </div>
      </div>
      {activeSearch && !loading && !error && (
        <div className={toolbarStyles.searchHint}>
          {t("pluginManager.marketSearchResult", {
            keyword: activeSearch,
            count: total,
          })}
        </div>
      )}

      {error && (
        <Alert
          type="warning"
          showIcon
          message={<span style={{ fontSize: 15 }}>{error}</span>}
          style={{ marginBottom: 12 }}
        />
      )}

      <Spin spinning={loading}>
        {!loading && plugins.length === 0 && !error && (
          <Text type="secondary">{t("pluginManager.marketEmpty")}</Text>
        )}
        {isMobile || viewMode === "card" ? (
          <div className={marketStyles.cardGrid}>
            {plugins.map((entry) => {
              const description = pickLocalizedDescription(
                entry,
                i18n.language,
              );
              return (
                <article
                  className={marketStyles.pluginCard}
                  key={entry.id}
                  aria-label={entry.display_name}
                >
                  <div className={marketStyles.cardIcon}>
                    <Package size={18} />
                  </div>
                  <div className={marketStyles.cardTitleRow}>
                    <Text
                      strong
                      ellipsis={{ tooltip: entry.display_name }}
                      className={marketStyles.cardTitle}
                    >
                      {entry.display_name}
                    </Text>
                    {renderCategoryTag(entry)}
                    {renderCompatibilityTag(entry)}
                  </div>
                  <div className={marketStyles.cardDescription}>
                    {description || t("market.noDescription")}
                  </div>
                  <div className={marketStyles.cardFooter}>
                    <span className={marketStyles.cardMetadata}>
                      v{entry.version}
                      {(entry.developer || entry.owner) &&
                        ` · ${entry.developer || entry.owner}`}
                    </span>
                    {entry.downloads != null && (
                      <span className={marketStyles.cardDownloads}>
                        <Download size={12} />
                        {entry.downloads.toLocaleString(i18n.language)}
                      </span>
                    )}
                  </div>
                  <div className={marketStyles.cardActions}>
                    {renderInstallButton(entry)}
                    {entry.details_url && (
                      <Button
                        type="default"
                        icon={<ExternalLink size={14} />}
                        onClick={() =>
                          void openExternalLink(entry.details_url!)
                        }
                      >
                        {t("pluginManager.marketDetails")}
                      </Button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className={styles.catalogList}>
            {plugins.map((entry) => (
              <div className={styles.catalogRow} key={entry.id}>
                <div className={styles.catalogIcon}>
                  {entry.logo_url ? (
                    <img
                      src={entry.logo_url}
                      alt=""
                      style={{
                        width: 24,
                        height: 24,
                        borderRadius: 4,
                        objectFit: "contain",
                      }}
                    />
                  ) : (
                    <Package size={18} />
                  )}
                </div>
                <div className={styles.catalogInfo}>
                  <div className={styles.catalogNameRow}>
                    <Text strong>{entry.display_name}</Text>
                    {renderCategoryTag(entry)}
                    {renderCompatibilityTag(entry)}
                  </div>
                  {entry.locales && (
                    <div className={styles.catalogDescription}>
                      {pickLocalizedDescription(entry, i18n.language)}
                    </div>
                  )}
                  <div className={styles.catalogMeta}>
                    v{entry.version}
                    {entry.developer
                      ? ` · ${t("pluginManager.marketDeveloper")}: ${
                          entry.developer
                        }`
                      : ""}
                    {entry.downloads != null
                      ? ` · ${t("pluginManager.marketDownloads")}: ${
                          entry.downloads
                        }`
                      : ""}
                  </div>
                </div>
                <div className={styles.catalogActions}>
                  {entry.details_url && (
                    <Button
                      type="default"
                      icon={<ExternalLink size={14} />}
                      onClick={() => void openExternalLink(entry.details_url!)}
                    >
                      {t("pluginManager.marketDetails")}
                    </Button>
                  )}
                  {renderInstallButton(entry)}
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && plugins.length > 0 && (
          <div className={marketStyles.loadMoreRow}>
            {hasMore && autoLoadBlocked ? (
              <Button onClick={handleRetryLoadMore} loading={loadingMore}>
                {t("common.retry")}
              </Button>
            ) : hasMore ? (
              <LoadMoreSentinel
                key={plugins.length}
                loading={loadingMore}
                onVisible={handleLoadMore}
              />
            ) : (
              <span>{t("market.noMoreResults")}</span>
            )}
          </div>
        )}
      </Spin>
    </div>
  );
}
