import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Download, RefreshCw, Package } from "lucide-react";
import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import { useOfficialPlugins } from "../hooks/useOfficialPlugins";
import styles from "./OfficialPluginList.module.less";

/**
 * Resolve the best-matching description from `description_i18n` based on
 * the current i18n language. Falls back to the default `description` field.
 *
 * Matching strategy:
 *   1. Exact match (e.g. "zh" → "zh", "zh-CN" → "zh-CN")
 *   2. Prefix match (e.g. "zh" → "zh-CN", "en" → "en-US")
 *   3. Fallback to `description`
 */
function pickLocalizedDescription(
  entry: OfficialPluginCatalogEntry,
  language: string,
): string {
  const i18nMap = entry.description_i18n;
  if (!i18nMap || Object.keys(i18nMap).length === 0) {
    return entry.description || "";
  }

  // Exact match
  if (i18nMap[language]) {
    return i18nMap[language];
  }

  // Prefix match: "zh" matches "zh-CN", "en" matches "en-US"
  const prefix = language.split("-")[0].toLowerCase();
  for (const key of Object.keys(i18nMap)) {
    if (key.toLowerCase().startsWith(prefix)) {
      return i18nMap[key];
    }
  }

  return entry.description || "";
}

interface OfficialPluginListProps {
  onInstalled: () => void;
}

export function OfficialPluginList({ onInstalled }: OfficialPluginListProps) {
  const { t, i18n } = useTranslation();
  const [nameFilter, setNameFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<string | undefined>(undefined);

  const {
    loading,
    catalogError,
    plugins,
    installingId,
    loadCatalog,
    handleInstall,
  } = useOfficialPlugins({ onInstalled });

  const filteredPlugins = useMemo(() => {
    return plugins.filter((entry) => {
      const matchesName =
        !nameFilter ||
        entry.name.toLowerCase().includes(nameFilter.toLowerCase());
      const matchesKind =
        !kindFilter || entry.kind?.toLowerCase() === kindFilter;
      return matchesName && matchesKind;
    });
  }, [plugins, nameFilter, kindFilter]);

  const kindOptions = useMemo(() => {
    const kinds = [...new Set(plugins.map((p) => p.kind).filter(Boolean))];
    return kinds.map((kind) => ({
      value: kind!.toLowerCase(),
      label: t(
        `pluginManager.kind${kind!.charAt(0).toUpperCase()}${kind!
          .slice(1)
          .toLowerCase()}`,
        { defaultValue: kind },
      ),
    }));
  }, [plugins, t]);

  return (
    <div className={styles.catalogSection}>
      <div className={styles.catalogToolbar}>
        <div className={styles.catalogFilters}>
          <Input
            placeholder={t("pluginManager.filterByName")}
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            style={{ width: 220 }}
          />
          <Select
            value={kindFilter ?? ""}
            onValueChange={(val) => setKindFilter(val || undefined)}
          >
            <SelectTrigger style={{ width: 150 }}>
              <SelectValue placeholder={t("pluginManager.filterByKind")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">
                {t("pluginManager.allKinds", "All")}
              </SelectItem>
              {kindOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void loadCatalog()}
          disabled={loading}
        >
          <RefreshCw size={14} className="mr-1" />
          {t("pluginManager.catalogRefresh")}
        </Button>
      </div>

      {catalogError && (
        <div className="flex items-center gap-2 rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800 dark-mode:border-yellow-800 dark-mode:bg-yellow-950 dark-mode:text-yellow-200 mb-3">
          {catalogError}
        </div>
      )}

      <div className={loading ? "opacity-60 pointer-events-none" : ""}>
        {!loading && filteredPlugins.length === 0 && !catalogError && (
          <span className="text-sm text-muted-foreground">
            {t("pluginManager.catalogEmpty")}
          </span>
        )}
        <div className={styles.catalogList}>
          {filteredPlugins.map((entry) => (
            <div className={styles.catalogRow} key={entry.id}>
              <div className={styles.catalogIcon}>
                <Package size={18} />
              </div>
              <div className={styles.catalogInfo}>
                <div className={styles.catalogNameRow}>
                  <span className="font-medium">{entry.name}</span>
                  {entry.kind && (
                    <Badge variant="outline" className="text-xs">
                      {t(
                        `pluginManager.kind${entry.kind
                          .charAt(0)
                          .toUpperCase()}${entry.kind.slice(1).toLowerCase()}`,
                        { defaultValue: entry.kind },
                      )}
                    </Badge>
                  )}
                  {entry.installed && !entry.upgrade_available && (
                    <Badge
                      variant="outline"
                      className="text-xs text-green-600 border-green-300"
                    >
                      {t("pluginManager.catalogInstalled")}
                    </Badge>
                  )}
                  {entry.upgrade_available && (
                    <Badge
                      variant="outline"
                      className="text-xs text-blue-600 border-blue-300"
                    >
                      {t("pluginManager.catalogUpgrade")}
                    </Badge>
                  )}
                </div>
                {(entry.description || entry.description_i18n) && (
                  <div className={styles.catalogDescription}>
                    {pickLocalizedDescription(entry, i18n.language)}
                  </div>
                )}
                <div className={styles.catalogMeta}>
                  v{entry.version}
                  {entry.size ? ` · ${entry.size}` : ""}
                  {entry.author ? ` · ${entry.author}` : ""}
                </div>
              </div>
              <div className={styles.catalogActions}>
                <Button
                  variant={
                    entry.installed && !entry.upgrade_available
                      ? "outline"
                      : "default"
                  }
                  size="sm"
                  disabled={installingId !== null}
                  onClick={() => void handleInstall(entry)}
                >
                  <Download size={14} className="mr-1" />
                  {entry.upgrade_available
                    ? t("pluginManager.catalogUpgradeBtn")
                    : entry.installed
                    ? t("pluginManager.catalogReinstall")
                    : t("pluginManager.catalogInstall")}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
