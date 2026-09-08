import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Input,
  Modal,
  Select,
  Spin,
  Tag,
  Typography,
} from "antd";
import { Download, Package, RefreshCw } from "lucide-react";
import { useIsMobile } from "@/hooks/useIsMobile";
import { compareVersions } from "@/layouts/constants";
import type {
  InstallPluginResult,
  OfficialPluginCatalogEntry,
} from "@/api/modules/plugin";
import { useOfficialPlugins } from "../hooks/useOfficialPlugins";
import {
  getOfficialPluginInstallAction,
  groupOfficialPlugins,
  type OfficialPluginGroup,
} from "../officialPluginVersions";
import { PluginViewToggle, type PluginViewMode } from "./PluginViewToggle";
import styles from "./OfficialPluginList.module.less";
import cardStyles from "./MarketPluginList.module.less";
import toolbarStyles from "./PluginListToolbar.module.less";

const { Text } = Typography;

function pickLocalizedDescription(
  entry: OfficialPluginCatalogEntry,
  language: string,
): string {
  const i18nMap = entry.description_i18n;
  if (!i18nMap || Object.keys(i18nMap).length === 0) {
    return entry.description || "";
  }

  if (i18nMap[language]) return i18nMap[language];

  const prefix = language.split("-")[0].toLowerCase();
  for (const key of Object.keys(i18nMap)) {
    if (key.toLowerCase().startsWith(prefix)) return i18nMap[key];
  }

  return entry.description || "";
}

function kindLabelKey(kind: string): string {
  return `pluginManager.kind${kind.charAt(0).toUpperCase()}${kind
    .slice(1)
    .toLowerCase()}`;
}

interface OfficialPluginListProps {
  onInstalled: (result: InstallPluginResult) => void | Promise<void>;
}

export function OfficialPluginList({ onInstalled }: OfficialPluginListProps) {
  const { t, i18n } = useTranslation();
  const [nameFilter, setNameFilter] = useState("");
  const [kindFilter, setKindFilter] = useState<string | undefined>();
  const [viewMode, setViewMode] = useState<PluginViewMode>("card");
  const [selectedVersions, setSelectedVersions] = useState<
    Record<string, string>
  >({});
  const isMobile = useIsMobile();

  const {
    loading,
    catalogError,
    plugins,
    installingId,
    loadCatalog,
    handleInstall,
  } = useOfficialPlugins({ onInstalled });

  const pluginGroups = useMemo(() => groupOfficialPlugins(plugins), [plugins]);

  const selectedPlugins = useMemo(
    () =>
      pluginGroups.map((group) => ({
        group,
        entry:
          group.versions.find(
            (entry) => entry.version === selectedVersions[group.key],
          ) ?? group.defaultVersion,
      })),
    [pluginGroups, selectedVersions],
  );

  const filteredPlugins = useMemo(() => {
    const keyword = nameFilter.trim().toLocaleLowerCase();
    return selectedPlugins.filter(({ entry }) => {
      const matchesName =
        !keyword || entry.name.toLocaleLowerCase().includes(keyword);
      const matchesKind =
        !kindFilter || entry.kind?.toLowerCase() === kindFilter;
      return matchesName && matchesKind;
    });
  }, [kindFilter, nameFilter, selectedPlugins]);

  const kindOptions = useMemo(
    () => [
      ...new Set(
        pluginGroups.map((group) => group.defaultVersion.kind).filter(Boolean),
      ),
    ],
    [pluginGroups],
  );

  const renderKindTag = (entry: OfficialPluginCatalogEntry) =>
    entry.kind ? (
      <Tag
        color={entry.kind.toLowerCase() === "bundle" ? "purple" : "blue"}
        style={{ margin: 0, fontSize: 11 }}
      >
        {t(kindLabelKey(entry.kind), { defaultValue: entry.kind })}
      </Tag>
    ) : null;

  const renderStatusTag = (entry: OfficialPluginCatalogEntry) => {
    const action = getOfficialPluginInstallAction(entry);
    if (action === "upgrade") {
      return (
        <Tag color="processing" style={{ margin: 0, fontSize: 11 }}>
          {t("pluginManager.catalogUpgrade")}
        </Tag>
      );
    }
    if (action !== "install") {
      return (
        <Tag color="success" style={{ margin: 0, fontSize: 11 }}>
          {t("pluginManager.catalogInstalled")}
        </Tag>
      );
    }
    return null;
  };

  const requestInstall = (entry: OfficialPluginCatalogEntry) => {
    if (getOfficialPluginInstallAction(entry) === "downgrade") {
      Modal.confirm({
        title: t("pluginManager.catalogDowngradeTitle"),
        content: t("pluginManager.catalogDowngradeConfirm", {
          name: entry.name,
          installedVersion: entry.installed_version,
          selectedVersion: entry.version,
        }),
        okText: t("pluginManager.catalogDowngrade"),
        cancelText: t("common.cancel"),
        okType: "danger",
        onOk: () => handleInstall(entry),
      });
      return;
    }
    void handleInstall(entry);
  };

  const renderInstallButton = (entry: OfficialPluginCatalogEntry) => {
    const action = getOfficialPluginInstallAction(entry);
    const buttonText = {
      install: t("pluginManager.catalogInstall"),
      upgrade: t("pluginManager.catalogUpgradeBtn"),
      reinstall: t("pluginManager.catalogReinstall"),
      downgrade: t("pluginManager.catalogDowngrade"),
    }[action];

    return (
      <Button
        type={
          action === "install" || action === "upgrade" ? "primary" : "default"
        }
        icon={<Download size={14} />}
        loading={installingId === entry.id}
        disabled={installingId !== null && installingId !== entry.id}
        onClick={() => requestInstall(entry)}
      >
        {buttonText}
      </Button>
    );
  };

  const renderVersionSelect = (
    group: OfficialPluginGroup,
    entry: OfficialPluginCatalogEntry,
  ) => (
    <Select
      className={styles.versionSelect}
      aria-label={t("pluginManager.catalogVersion")}
      value={entry.version}
      onChange={(version) =>
        setSelectedVersions((current) => ({
          ...current,
          [group.key]: version,
        }))
      }
      options={group.versions.map((candidate) => {
        const isInstalled = Boolean(
          candidate.installed_version &&
            compareVersions(candidate.version, candidate.installed_version) ===
              0,
        );
        return {
          value: candidate.version,
          label: isInstalled
            ? `v${candidate.version} · ${t(
                "pluginManager.catalogInstalledVersion",
              )}`
            : `v${candidate.version}`,
        };
      })}
    />
  );

  return (
    <div className={styles.catalogSection}>
      <div className={toolbarStyles.filterRow}>
        <button
          type="button"
          className={`${toolbarStyles.filterTag} ${
            !kindFilter ? toolbarStyles.filterTagActive : ""
          }`}
          onClick={() => setKindFilter(undefined)}
        >
          {t("pluginManager.marketAll")}
        </button>
        {kindOptions.map((kind) => {
          const normalizedKind = kind.toLowerCase();
          return (
            <button
              type="button"
              key={kind}
              className={`${toolbarStyles.filterTag} ${
                kindFilter === normalizedKind
                  ? toolbarStyles.filterTagActive
                  : ""
              }`}
              onClick={() => setKindFilter(normalizedKind)}
            >
              {t(kindLabelKey(kind), { defaultValue: kind })}
            </button>
          );
        })}
      </div>

      <div className={toolbarStyles.controlRow}>
        <Input
          className={toolbarStyles.search}
          placeholder={t("pluginManager.filterByName")}
          allowClear
          value={nameFilter}
          onChange={(event) => setNameFilter(event.target.value)}
        />
        <div className={toolbarStyles.controlActions}>
          <Button
            type="default"
            className={toolbarStyles.iconButton}
            icon={<RefreshCw size={14} />}
            onClick={() => void loadCatalog()}
            disabled={loading}
            aria-label={t("pluginManager.catalogRefresh")}
            title={t("pluginManager.catalogRefresh")}
          />
          {!isMobile && (
            <PluginViewToggle value={viewMode} onChange={setViewMode} />
          )}
        </div>
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
        {isMobile || viewMode === "card" ? (
          <div className={cardStyles.cardGrid}>
            {filteredPlugins.map(({ group, entry }) => (
              <article
                className={cardStyles.pluginCard}
                key={group.key}
                aria-label={entry.name}
              >
                <div className={cardStyles.cardTopRow}>
                  <div className={cardStyles.cardIcon}>
                    <Package size={18} />
                  </div>
                  {renderStatusTag(entry)}
                </div>
                <div className={cardStyles.cardTitleRow}>
                  <Text
                    strong
                    ellipsis={{ tooltip: entry.name }}
                    className={cardStyles.cardTitle}
                  >
                    {entry.name}
                  </Text>
                  {renderKindTag(entry)}
                </div>
                <div className={cardStyles.cardDescription}>
                  {pickLocalizedDescription(entry, i18n.language) ||
                    t("market.noDescription")}
                </div>
                <div className={cardStyles.cardFooter}>
                  <span className={cardStyles.cardMetadata}>
                    v{entry.version}
                    {entry.size ? ` · ${entry.size}` : ""}
                    {entry.author ? ` · ${entry.author}` : ""}
                  </span>
                </div>
                <div className={cardStyles.cardActions}>
                  {renderVersionSelect(group, entry)}
                  {renderInstallButton(entry)}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className={styles.catalogList}>
            {filteredPlugins.map(({ group, entry }) => (
              <div className={styles.catalogRow} key={group.key}>
                <div className={styles.catalogIcon}>
                  <Package size={18} />
                </div>
                <div className={styles.catalogInfo}>
                  <div className={styles.catalogNameRow}>
                    <Text strong>{entry.name}</Text>
                    {renderKindTag(entry)}
                    {renderStatusTag(entry)}
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
                  {renderVersionSelect(group, entry)}
                  {renderInstallButton(entry)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Spin>
    </div>
  );
}
