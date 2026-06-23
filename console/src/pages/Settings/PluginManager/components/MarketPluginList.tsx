import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Input, Pagination, Spin, Tag, Typography } from "antd";
import { Download, ExternalLink, Package, RefreshCw } from "lucide-react";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { useMarketPlugins } from "../hooks/useMarketPlugins";
import styles from "./OfficialPluginList.module.less";
import marketStyles from "./MarketPluginList.module.less";

const { Text } = Typography;

const PLUGIN_CATEGORIES = [
  { code: "agent-tool", zh: "Agent 工具", en: "Agent Tool" },
  { code: "provider", zh: "模型接入", en: "Provider" },
  { code: "command", zh: "Slash 命令", en: "Slash Command" },
  { code: "hook", zh: "生命周期 Hook", en: "Lifecycle Hook" },
  { code: "frontend", zh: "UI 扩展", en: "UI Extension" },
  { code: "general", zh: "通用插件", en: "General" },
];

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

  const {
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
  } = useMarketPlugins({ onInstalled });

  const lang = i18n.language.split("-")[0].toLowerCase();

  const isSearchMode = !!activeSearch;

  const onSearch = (val: string) => {
    setActiveSearch(val);
    handleSearch(val);
    if (val) handleCategoryChange(undefined);
  };

  const onCategoryClick = (code: string | null) => {
    handleCategoryChange(code || undefined);
  };

  return (
    <div className={styles.catalogSection}>
      <div className={marketStyles.toolbar}>
        {!isSearchMode ? (
          <div className={marketStyles.categoryTabs}>
            <span
              className={`${marketStyles.categoryTab} ${
                !category ? marketStyles.categoryTabActive : ""
              }`}
              onClick={() => onCategoryClick(null)}
            >
              {t("pluginManager.marketAll")}
            </span>
            {PLUGIN_CATEGORIES.map((cat) => (
              <span
                key={cat.code}
                className={`${marketStyles.categoryTab} ${
                  category === cat.code ? marketStyles.categoryTabActive : ""
                }`}
                onClick={() => onCategoryClick(cat.code)}
              >
                {lang === "zh" ? cat.zh : cat.en}
              </span>
            ))}
          </div>
        ) : (
          <div className={marketStyles.searchHint}>
            {!loading &&
              !error &&
              t("pluginManager.marketSearchResult", {
                keyword: activeSearch,
                count: total,
              })}
          </div>
        )}
        <div className={marketStyles.toolbarRight}>
          <Input.Search
            placeholder={t("pluginManager.marketSearch")}
            allowClear
            value={searchInput}
            onChange={(e) => {
              setSearchInput(e.target.value);
              if (!e.target.value) onSearch("");
            }}
            onSearch={onSearch}
            style={{ width: 220 }}
          />
          <Button
            type="default"
            size="small"
            icon={<RefreshCw size={14} />}
            onClick={handleRefresh}
            disabled={loading}
          >
            {t("pluginManager.catalogRefresh")}
          </Button>
        </div>
      </div>

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
                  {entry.locales?.[lang]?.category && (
                    <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>
                      {entry.locales[lang].category}
                    </Tag>
                  )}
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
                    size="small"
                    icon={<ExternalLink size={14} />}
                    onClick={() => window.open(entry.details_url!, "_blank")}
                  >
                    {t("pluginManager.marketDetails")}
                  </Button>
                )}
                <Button
                  type="primary"
                  size="small"
                  icon={<Download size={14} />}
                  loading={installingId === entry.id}
                  disabled={installingId !== null && installingId !== entry.id}
                  onClick={() => void handleInstall(entry)}
                >
                  {t("pluginManager.catalogInstall")}
                </Button>
              </div>
            </div>
          ))}
        </div>

        {total > pageSize && (
          <div style={{ marginTop: 16, textAlign: "center" }}>
            <Pagination
              current={page}
              pageSize={pageSize}
              total={total}
              onChange={handlePageChange}
              showSizeChanger={false}
              size="small"
            />
          </div>
        )}
      </Spin>
    </div>
  );
}
