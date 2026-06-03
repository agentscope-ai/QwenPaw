import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Select, Spin, Typography, Alert, Tag } from "antd";
import { Download, RefreshCw, Package } from "lucide-react";
import type { OfficialPluginCatalogEntry } from "@/api/modules/plugin";
import { useOfficialPlugins } from "../hooks/useOfficialPlugins";
import styles from "./OfficialPluginList.module.less";

const { Text } = Typography;

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
            allowClear
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
            style={{ width: 220 }}
          />
          <Select
            placeholder={t("pluginManager.filterByKind")}
            allowClear
            value={kindFilter}
            onChange={(val) => setKindFilter(val)}
            options={kindOptions}
            style={{ width: 150 }}
          />
        </div>
        <Button
          type="default"
          size="small"
          icon={<RefreshCw size={14} />}
          onClick={() => void loadCatalog()}
          disabled={loading}
        >
          {t("pluginManager.catalogRefresh")}
        </Button>
      </div>

      {catalogError && (
        <Alert
          type="warning"
          showIcon
          message={catalogError}
          style={{ marginBottom: 12 }}
        />
      )}

      <Spin spinning={loading}>
        {!loading && filteredPlugins.length === 0 && !catalogError && (
          <Text type="secondary">{t("pluginManager.catalogEmpty")}</Text>
        )}
        <div className={styles.catalogList}>
          {filteredPlugins.map((entry) => (
            <div className={styles.catalogRow} key={entry.id}>
              <div className={styles.catalogIcon}>
                <Package size={18} />
              </div>
              <div className={styles.catalogInfo}>
                <div className={styles.catalogNameRow}>
                  <Text strong>{entry.name}</Text>
                  {entry.kind && (
                    <Tag
                      color={
                        entry.kind.toLowerCase() === "bundle"
                          ? "purple"
                          : "blue"
                      }
                      style={{ margin: 0, fontSize: 11 }}
                    >
                      {t(
                        `pluginManager.kind${entry.kind
                          .charAt(0)
                          .toUpperCase()}${entry.kind.slice(1).toLowerCase()}`,
                        { defaultValue: entry.kind },
                      )}
                    </Tag>
                  )}
                  {entry.installed && !entry.upgrade_available && (
                    <Tag color="success" style={{ margin: 0, fontSize: 11 }}>
                      {t("pluginManager.catalogInstalled")}
                    </Tag>
                  )}
                  {entry.upgrade_available && (
                    <Tag color="processing" style={{ margin: 0, fontSize: 11 }}>
                      {t("pluginManager.catalogUpgrade")}
                    </Tag>
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
                  type={
                    entry.installed && !entry.upgrade_available
                      ? "default"
                      : "primary"
                  }
                  size="small"
                  icon={<Download size={14} />}
                  loading={installingId === entry.id}
                  disabled={installingId !== null && installingId !== entry.id}
                  onClick={() => void handleInstall(entry)}
                >
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
      </Spin>
    </div>
  );
}
