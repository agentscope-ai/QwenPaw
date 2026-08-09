/**
 * AppStore.tsx — System app for installing desktop and Paw apps.
 *
 * Three sections:
 *   1. Desktop apps  — the curated OS_APPS catalog. Install / uninstall toggles
 *      whether they appear on the desktop + launcher (osPluginStore, local).
 *   2. Installed PawApps — app-type plugins loaded from the backend.
 *   3. App Market — sourced from the real marketplace via useOsAppMarket.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Input, Pagination, Spin, Tag, Tooltip } from "antd";
import {
  Download,
  Trash2,
  RotateCcw,
  Package,
  Puzzle,
  ExternalLink,
  RefreshCw,
} from "lucide-react";
import { useRoutes } from "../plugins/registry/hooks";
import type { MarketPluginEntry } from "../api/modules/pluginMarket";
import { openExternalLink } from "../utils/openExternalLink";
import {
  fetchPlugins,
  uninstallPlugin,
  type PluginInfo,
} from "../api/modules/plugin";
import { OS_APPS } from "./osApps";
import { useOsPlugins } from "./osPluginStore";
import { purgeAppState, purgePluginAppState } from "./osCleanup";
import { useOsModal } from "./useOsModal";
import { useOsStyles } from "./useOsStyles";
import { useOsAppMarket } from "./useOsAppMarket";

/** Pick the description for the active language, with graceful fallbacks. */
function localizedDescription(
  entry: MarketPluginEntry,
  language: string,
): string {
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

export default function AppStore() {
  const { styles, cx } = useOsStyles();
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const routes = useRoutes();
  const { installed, install, uninstall, installAll } = useOsPlugins();
  // App overlay semantics: keep static confirm dialogs inside this window.
  const osModal = useOsModal();

  // Installed PawApps (app-type plugins, e.g. agent-kanban). Sourced from the
  // backend so the list reflects what is actually loaded, enabling in-place
  // uninstall / update alongside the marketplace.
  const [installedApps, setInstalledApps] = useState<PluginInfo[]>([]);
  const [appsLoading, setAppsLoading] = useState(true);

  const refreshInstalledApps = () => {
    setAppsLoading(true);
    fetchPlugins()
      .then((list) =>
        setInstalledApps(list.filter((p) => p.plugin_type === "app")),
      )
      .catch(() => setInstalledApps([]))
      .finally(() => setAppsLoading(false));
  };

  const {
    loading,
    error,
    plugins,
    total,
    page,
    pageSize,
    installingId,
    qwenpawVersion,
    isCompatible,
    handleSearch,
    handlePageChange,
    handleRefresh,
    handleInstall,
    // onInstalled: refresh the installed-apps section after a market
    // install/update so the new PawApp shows up without a full page reload.
  } = useOsAppMarket({
    onInstalled: refreshInstalledApps,
  });

  const [searchInput, setSearchInput] = useState("");

  useEffect(() => {
    refreshInstalledApps();
  }, []);

  /** Matching market entry (same id) — enables the update affordance. */
  const marketEntryForApp = (p: PluginInfo) =>
    plugins.find((e) => e.id === p.id);

  const uninstallApp = (p: PluginInfo) => {
    osModal.confirm({
      title: t("os.uninstallConfirmTitle", "Uninstall app?"),
      content: p.name,
      okText: t("os.uninstall", "Uninstall"),
      okButtonProps: { danger: true },
      cancelText: t("common.cancel", "Cancel"),
      onOk: async () => {
        try {
          await uninstallPlugin(p.id);
          // Confirmed uninstall: purge persisted desktop state before the
          // reload drops the plugin's routes from the registry.
          purgePluginAppState(p.id);
          message.success(
            t("os.uninstalledApp", {
              name: p.name,
              defaultValue: "Uninstalled",
            }),
          );
          setTimeout(() => window.location.reload(), 600);
        } catch (err) {
          message.error(
            err instanceof Error
              ? err.message
              : t("os.uninstallFailed", "Uninstall failed"),
          );
        }
      },
    });
  };

  const availableIds = useMemo(
    () => new Set(routes.map((r) => r.id)),
    [routes],
  );
  const catalog = useMemo(
    () => OS_APPS.filter((a) => availableIds.has(a.routeId)),
    [availableIds],
  );
  const installedSet = useMemo(() => new Set(installed), [installed]);

  const installMarketPlugin = (entry: MarketPluginEntry) => {
    if (isCompatible(entry)) {
      void handleInstall(entry);
      return;
    }
    osModal.confirm({
      title: t("os.appCompatibilityWarningTitle", "Compatibility Warning"),
      content: t("os.appCompatibilityWarningContent", {
        defaultValue:
          "This app is labeled for QwenPaw {{labels}}. Your QwenPaw version is {{version}}. Installing it may cause errors. Continue?",
        labels: entry.qwenpaw_compat_labels?.join(", ") ?? "unknown",
        version: qwenpawVersion ?? "unknown",
      }),
      okText: t("os.appCompatibilityWarningConfirm", "Install anyway"),
      cancelText: t("common.cancel", "Cancel"),
      onOk: () => void handleInstall(entry),
    });
  };

  return (
    <div className={styles.storeRoot}>
      {osModal.holder}
      <div className={styles.storeHead}>
        <h2>{t("os.appStore", "App Store")}</h2>
        <p>{t("os.appStoreDesc", "Install or remove desktop apps")}</p>
      </div>

      <div className={styles.storeToolbar}>
        <span style={{ fontSize: 13, color: "#94a3b8" }}>
          {installedSet.size} / {catalog.length}{" "}
          {t("os.installed", "installed")}
        </span>
        <button
          className={styles.storeBtn}
          onClick={() => {
            installAll();
            message.success(t("os.restoredAll", "Restored all apps"));
          }}
        >
          <RotateCcw size={14} />
          {t("os.restoreAll", "Restore all")}
        </button>
      </div>

      <div className={styles.storeBody}>
        {/* Section 1 — desktop apps (local install simulation) */}
        <div className={styles.storeSectionTitle}>
          {t("os.desktopApps", "Desktop apps")}
        </div>
        <div className={styles.storeGrid}>
          {catalog.map((a) => {
            const Icon = a.Icon;
            const isInstalled = installedSet.has(a.routeId);
            return (
              <div key={a.routeId} className={styles.storeCard}>
                <div className={styles.storeCardTop}>
                  <div
                    className={styles.storeTile}
                    style={{ background: a.accent }}
                  >
                    <Icon size={22} />
                  </div>
                  <div className="meta">
                    <div className="name">{t(a.labelKey, a.fallback)}</div>
                    <div
                      className="status"
                      style={{ color: isInstalled ? "#22c55e" : "#64748b" }}
                    >
                      {isInstalled
                        ? t("os.installed", "installed")
                        : t("os.notInstalled", "not installed")}
                    </div>
                  </div>
                </div>
                {isInstalled ? (
                  <button
                    className={styles.storeBtn}
                    onClick={() => {
                      uninstall(a.routeId);
                      purgeAppState([a.routeId]);
                      message.info(
                        t("os.uninstalledApp", {
                          name: t(a.labelKey, a.fallback),
                          defaultValue: "Uninstalled",
                        }),
                      );
                    }}
                  >
                    <Trash2 size={14} />
                    {t("os.uninstall", "Uninstall")}
                  </button>
                ) : (
                  <button
                    className={cx(styles.storeBtn, styles.storeBtnInstall)}
                    onClick={() => {
                      install(a.routeId);
                      message.success(
                        t("os.installedApp", {
                          name: t(a.labelKey, a.fallback),
                          defaultValue: "Installed",
                        }),
                      );
                    }}
                  >
                    <Download size={14} />
                    {t("os.install", "Install")}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* Section 2 — installed PawApps (app-type plugins) */}
        <div className={styles.storeSectionTitle}>
          {t("os.installedApps", "Installed apps")}
          {!appsLoading && ` · ${installedApps.length}`}
        </div>
        <Spin spinning={appsLoading}>
          {!appsLoading && installedApps.length === 0 && (
            <div className={styles.storeEmpty}>
              {t("os.noInstalledApps", "No apps installed")}
            </div>
          )}
          <div className={styles.storeGrid}>
            {installedApps.map((p) => {
              const marketEntry = marketEntryForApp(p);
              const canUpdate =
                marketEntry != null && marketEntry.version !== p.version;
              return (
                <div key={p.id} className={styles.storeCard}>
                  <div className={styles.storeCardTop}>
                    <div
                      className={styles.storeTile}
                      style={{ background: "#1e293b" }}
                    >
                      <Puzzle size={22} />
                    </div>
                    <div className="meta">
                      <div className="name">{p.name}</div>
                      <div className="status" style={{ color: "#64748b" }}>
                        v{p.version}
                        {canUpdate && (
                          <Tag
                            color="orange"
                            style={{ marginLeft: 6, fontSize: 10 }}
                          >
                            {`→ v${marketEntry!.version}`}
                          </Tag>
                        )}
                      </div>
                    </div>
                  </div>
                  {p.description && (
                    <div className={styles.storeCardDesc}>{p.description}</div>
                  )}
                  <div className={styles.storeActions}>
                    {canUpdate && (
                      <Button
                        type="primary"
                        size="small"
                        icon={<RefreshCw size={14} />}
                        loading={installingId === marketEntry!.id}
                        onClick={() => installMarketPlugin(marketEntry!)}
                      >
                        {t("os.update", "Update")}
                      </Button>
                    )}
                    <Button
                      size="small"
                      danger
                      icon={<Trash2 size={14} />}
                      onClick={() => uninstallApp(p)}
                    >
                      {t("os.uninstall", "Uninstall")}
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </Spin>

        {/* Section 3 — app marketplace (real source) */}
        <div className={styles.storeSectionTitle}>
          {t("os.appMarket", "App Market")}
          {!loading && !error && ` · ${total}`}
        </div>

        <div className={styles.storeToolbarRow}>
          <div className={styles.storeActions}>
            <Input.Search
              placeholder={t("os.appMarketSearch", "Search apps")}
              allowClear
              value={searchInput}
              onChange={(e) => {
                setSearchInput(e.target.value);
                if (!e.target.value) handleSearch("");
              }}
              onSearch={(v) => handleSearch(v)}
              style={{ width: 220 }}
            />
            <Button
              size="small"
              icon={<RefreshCw size={14} />}
              onClick={handleRefresh}
              disabled={loading}
            >
              {t("os.appMarketRefresh", "Refresh")}
            </Button>
          </div>
        </div>

        {error && <div className={styles.storeEmpty}>{error}</div>}

        <Spin spinning={loading}>
          {!loading && !error && plugins.length === 0 && (
            <div className={styles.storeEmpty}>
              {t("os.appMarketEmpty", "No apps found")}
            </div>
          )}
          <div className={styles.storeGrid}>
            {plugins.map((entry) => {
              const compat =
                entry.qwenpaw_compat_labels &&
                entry.qwenpaw_compat_labels.length > 0;
              return (
                <div key={entry.id} className={styles.storeCard}>
                  <div className={styles.storeCardTop}>
                    <div
                      className={styles.storeTile}
                      style={{ background: "#1e293b" }}
                    >
                      {entry.logo_url ? (
                        <img
                          src={entry.logo_url}
                          alt=""
                          style={{
                            width: 26,
                            height: 26,
                            borderRadius: 6,
                            objectFit: "contain",
                          }}
                        />
                      ) : (
                        <Package size={22} />
                      )}
                    </div>
                    <div className="meta">
                      <div className="name">{entry.display_name}</div>
                      <div className="status" style={{ color: "#64748b" }}>
                        v{entry.version}
                        {compat && (
                          <Tag
                            color={isCompatible(entry) ? "green" : "orange"}
                            style={{ marginLeft: 6, fontSize: 10 }}
                          >
                            {`QwenPaw ${entry.qwenpaw_compat_labels!.join(
                              ", ",
                            )}`}
                          </Tag>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className={styles.storeCardDesc}>
                    {localizedDescription(entry, i18n.language)}
                  </div>
                  <div className={styles.storeCardMeta}>
                    {entry.developer
                      ? `${t("os.appMarketDeveloper", "By")}: ${
                          entry.developer
                        }`
                      : ""}
                    {entry.downloads != null
                      ? ` · ${t("os.appMarketDownloads", "Downloads")}: ${
                          entry.downloads
                        }`
                      : ""}
                  </div>

                  <div className={styles.storeActions}>
                    {entry.details_url && (
                      <Button
                        size="small"
                        icon={<ExternalLink size={14} />}
                        onClick={() => openExternalLink(entry.details_url!)}
                      >
                        {t("os.appMarketDetails", "Details")}
                      </Button>
                    )}
                    <Tooltip
                      title={
                        !isCompatible(entry)
                          ? t("os.appCompatibilityUnverified", {
                              defaultValue:
                                "Compatibility with your QwenPaw version is unverified.",
                            })
                          : undefined
                      }
                    >
                      <Button
                        type="primary"
                        size="small"
                        icon={<Download size={14} />}
                        loading={installingId === entry.id}
                        disabled={
                          installingId !== null && installingId !== entry.id
                        }
                        onClick={() => installMarketPlugin(entry)}
                      >
                        {t("os.appMarketInstall", "Install")}
                      </Button>
                    </Tooltip>
                  </div>
                </div>
              );
            })}
          </div>

          {total > pageSize && (
            <div className={styles.storePager}>
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
    </div>
  );
}
