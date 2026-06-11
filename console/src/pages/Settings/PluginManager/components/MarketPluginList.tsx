import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Download,
  ExternalLink,
  Package,
  RefreshCw,
  Search,
} from "lucide-react";
import type { MarketPluginEntry } from "@/api/modules/pluginMarket";
import { useMarketPlugins } from "../hooks/useMarketPlugins";
import styles from "./OfficialPluginList.module.less";
import marketStyles from "./MarketPluginList.module.less";

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
          <div className="relative" style={{ width: 220 }}>
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              className="pl-8"
              placeholder={t("pluginManager.marketSearch")}
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                if (!e.target.value) onSearch("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSearch(searchInput);
              }}
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={loading}
          >
            <RefreshCw size={14} className="mr-1" />
            {t("pluginManager.catalogRefresh")}
          </Button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200 mb-3">
          {error}
        </div>
      )}

      <div className={loading ? "opacity-60 pointer-events-none" : ""}>
        {!loading && plugins.length === 0 && !error && (
          <span className="text-sm text-muted-foreground">
            {t("pluginManager.marketEmpty")}
          </span>
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
                  <span className="font-medium">{entry.display_name}</span>
                  {entry.locales?.[lang]?.category && (
                    <Badge variant="outline" className="text-xs">
                      {entry.locales[lang].category}
                    </Badge>
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
                    variant="outline"
                    size="sm"
                    onClick={() => window.open(entry.details_url!, "_blank")}
                  >
                    <ExternalLink size={14} className="mr-1" />
                    {t("pluginManager.marketDetails")}
                  </Button>
                )}
                <Button
                  size="sm"
                  disabled={installingId !== null}
                  onClick={() => void handleInstall(entry)}
                >
                  <Download size={14} className="mr-1" />
                  {t("pluginManager.catalogInstall")}
                </Button>
              </div>
            </div>
          ))}
        </div>

        {total > pageSize && (
          <div className="mt-4 flex justify-center items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => handlePageChange(page - 1)}
            >
              &lt;
            </Button>
            <span className="text-sm text-muted-foreground">
              {page} / {Math.ceil(total / pageSize)}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= Math.ceil(total / pageSize)}
              onClick={() => handlePageChange(page + 1)}
            >
              &gt;
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
