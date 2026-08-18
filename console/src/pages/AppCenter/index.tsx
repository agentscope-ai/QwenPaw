/**
 * AppCenter/index.tsx — App Center page: grid of installed PawApps.
 *
 * Lists all plugins with `meta.pawapp` from the backend. Clicking an
 * app renders its registered route component INLINE within this page
 * (no full-page navigation). The classic console mirrors the app path in the
 * URL; the Desktop OS keeps its single `/os` browser entry point.
 */
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Empty,
  Input,
  Spin,
  Select,
  Modal,
  Button,
  Dropdown,
  Tabs,
} from "antd";
import type { MenuProps } from "antd";
import {
  AppWindow,
  BadgeCheck,
  CircleX,
  LayoutGrid,
  Search,
  RefreshCw,
  Info,
  Store,
  X,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import { pawappApi } from "../../api/modules/pawapp";
import type { InstallPluginResult } from "../../api/modules/plugin";
import { useRoutes } from "../../plugins/registry/hooks";
import { loadPawApp } from "../../plugins/usePluginLoader";
import { removePluginAppState } from "../../os/osCleanup";
import { setActivePawAppId } from "../../plugins/pawapp-sdk/context";
import { AppCard, pickAppDescription, type AppCardData } from "./AppCard";
import { ChunkErrorBoundary } from "@/components/ChunkErrorBoundary";
import {
  addRouterBasename,
  getOsPawAppIdFromHistoryState,
  getOsRootHref,
  isOsPath,
  withOsPawAppHistoryState,
} from "../../utils/navigationMode";
import styles from "./index.module.less";

// Code-split market views so their bundle + network fetch never block the
// installed-apps section from rendering or being used.
const AppMarket = lazy(() =>
  import("./AppMarket").then((m) => ({ default: m.AppMarket })),
);

const { Option } = Select;

/** URL-persisted App Center views; unknown values fall back to installed. */
type AppCenterView = "installed" | "official" | "market";
// Featured installed apps (e.g. Creator) are pinned to the top of the grid.
// Lower index = higher placement.
const FEATURED_APP_IDS = ["qwenpaw-creator"];

function featuredRank(id: string): number {
  const index = FEATURED_APP_IDS.indexOf(id);
  return index === -1 ? FEATURED_APP_IDS.length : index;
}

export default function AppCenterPage() {
  const { t, i18n } = useTranslation();
  const { appId } = useParams();
  const { message } = useAppMessage();
  const routes = useRoutes();
  const [searchParams, setSearchParams] = useSearchParams();
  const [apps, setApps] = useState<AppCardData[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [activeApp, setActiveApp] = useState<AppCardData | null>(null);
  const [loadError, setLoadError] = useState(false);

  // View state is URL-driven so refresh / back / forward keep working.
  // Unknown `view` values safely fall back to the installed-apps view.
  const viewParam = searchParams.get("view");
  const view: AppCenterView =
    viewParam === "official" || viewParam === "market"
      ? viewParam
      : "installed";

  const switchView = (next: AppCenterView) => {
    const params = new URLSearchParams(searchParams);
    if (next === "installed") params.delete("view");
    else params.set("view", next);
    setSearchParams(params);
  };

  const fetchApps = async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const data = await pawappApi.list();
      setApps(
        data.apps.map((app) => ({
          id: app.id,
          name: app.name,
          version: app.version,
          description: app.description,
          description_i18n: app.description_i18n ?? {},
          category: app.category ?? "",
          icon: app.icon ?? "",
          icon_url: app.icon_url ?? "",
          entry_page: app.entry_page ?? "",
          launch_scope: app.launch_scope ?? "page",
          status: app.status,
        })),
      );
    } catch (err) {
      console.error("Failed to fetch PawApps:", err);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  };

  const handleMarketInstalled = async (result: InstallPluginResult) => {
    if (apps.some((app) => app.id === result.id)) {
      window.location.reload();
      return;
    }
    await loadPawApp(result.id);
    await fetchApps();
  };

  useEffect(() => {
    fetchApps();
  }, []);

  // Deep-link / refresh support: when the URL carries an app id (e.g. a hard
  // reload at /apps/<id>), open that app inline once the list has loaded so
  // the App Center wrapper (with its back bar) stays in place.
  useEffect(() => {
    if (!appId) return;
    const found = apps.find((a) => a.id === appId);
    if (found) setActiveApp(found);
  }, [appId, apps]);

  useEffect(() => {
    setActivePawAppId(activeApp?.id ?? null);
    return () => setActivePawAppId(null);
  }, [activeApp?.id]);

  // Compute available categories
  const categories = useMemo(() => {
    const cats = new Set<string>();
    for (const app of apps) {
      if (app.category) cats.add(app.category);
    }
    return Array.from(cats).sort();
  }, [apps]);

  // Filter apps (featured apps stay pinned to the top, stable otherwise)
  const filteredApps = useMemo(() => {
    return apps
      .filter((app) => {
        const description = pickAppDescription(app, i18n.language);
        const matchesSearch =
          !searchQuery ||
          app.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          description.toLowerCase().includes(searchQuery.toLowerCase());
        const matchesCategory =
          categoryFilter === "all" || app.category === categoryFilter;
        return matchesSearch && matchesCategory;
      })
      .sort((a, b) => featuredRank(a.id) - featuredRank(b.id));
  }, [apps, searchQuery, categoryFilter, i18n.language]);

  const appTarget = (app: AppCardData) => app.entry_page || `/apps/${app.id}`;

  const activeRoute = useMemo(() => {
    if (!activeApp) return null;
    const target = appTarget(activeApp);
    return routes.find((route) => route.path === target) ?? null;
  }, [activeApp, routes]);

  const handleAppClick = async (app: AppCardData) => {
    const target = appTarget(app);
    try {
      await loadPawApp(app.id, target);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("appCenter.appLoadFailed", "Failed to load app"),
      );
      return;
    }
    if (isOsPath(window.location.pathname)) {
      window.history.pushState(
        withOsPawAppHistoryState(window.history.state, app.id),
        "",
        getOsRootHref(window.location.pathname),
      );
    } else {
      window.history.pushState(
        { pawappInline: true },
        "",
        addRouterBasename(window.location.pathname, target),
      );
    }
    setActiveApp(app);
  };

  const handleBack = () => {
    if (isOsPath(window.location.pathname)) {
      if (getOsPawAppIdFromHistoryState(window.history.state)) {
        window.history.back();
        return;
      }
      window.history.replaceState(
        withOsPawAppHistoryState(window.history.state, null),
        "",
        getOsRootHref(window.location.pathname),
      );
      setActiveApp(null);
      return;
    }
    window.history.pushState(
      {},
      "",
      addRouterBasename(window.location.pathname, "/apps"),
    );
    setActiveApp(null);
  };

  const handleUninstall = (app: AppCardData) => {
    Modal.confirm({
      title: t("appCenter.uninstallConfirmTitle", "Uninstall app?"),
      content: t("appCenter.uninstallConfirmContent", {
        name: app.name,
        defaultValue:
          `This will delete the app directory of "${app.name}". ` +
          "This cannot be undone.",
      }),
      okText: t("appCenter.uninstall", "卸载"),
      okButtonProps: { danger: true },
      cancelText: t("common.cancel", "Cancel"),
      onOk: async () => {
        try {
          await pawappApi.uninstall(app.id);
          removePluginAppState(app.id);
          message.success(t("appCenter.uninstallSuccess", "App uninstalled"));
          await fetchApps();
        } catch (err) {
          message.error(
            err instanceof Error
              ? err.message
              : t("appCenter.uninstallFailed", "Uninstall failed"),
          );
          throw err;
        }
      },
    });
  };

  // Keep the inline view in sync with browser back/forward.
  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      const appId = isOsPath(window.location.pathname)
        ? getOsPawAppIdFromHistoryState(event.state)
        : window.location.pathname.match(/\/apps\/([^/?#]+)/)?.[1];
      if (!appId) {
        setActiveApp(null);
        return;
      }
      setActiveApp(apps.find((app) => app.id === appId) ?? null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [apps]);

  // ESC key to close app and return to list
  useEffect(() => {
    if (!activeApp) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        handleBack();
      }
    };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [activeApp]);

  // ── Embedded app view ─────────────────────────────────────────────────────
  if (activeApp) {
    const AppComponent = activeRoute?.Component;
    // App menu items
    const appMenuItems: MenuProps["items"] = [
      {
        key: "about",
        icon: <Info size={14} />,
        label: t("appCenter.aboutApp", "关于应用"),
        onClick: () => {
          Modal.info({
            title: activeApp.name,
            width: 500,
            content: (
              <div style={{ paddingTop: 16 }}>
                <p>
                  <strong>{t("appCenter.version", "版本")}:</strong>{" "}
                  {activeApp.version}
                </p>
                <p>
                  <strong>{t("appCenter.id", "ID")}:</strong> {activeApp.id}
                </p>
                {activeApp.category && (
                  <p>
                    <strong>{t("appCenter.category", "分类")}:</strong>{" "}
                    {activeApp.category}
                  </p>
                )}
                {activeApp.description && (
                  <p>
                    <strong>{t("appCenter.description", "描述")}:</strong>{" "}
                    {pickAppDescription(activeApp, i18n.language)}
                  </p>
                )}
              </div>
            ),
          });
        },
      },
      {
        type: "divider",
      },
      {
        key: "exit",
        icon: <X size={14} />,
        label: t("appCenter.exitApp", "退出应用"),
        onClick: handleBack,
      },
    ];

    return (
      <div className={styles.embedPage}>
        {/* Floating capsule button - WeChat mini-program style */}
        <div className={styles.floatingCapsule}>
          <Dropdown
            menu={{ items: appMenuItems }}
            trigger={["click"]}
            placement="bottomRight"
          >
            <button
              className={styles.capsuleBtn}
              title={t("appCenter.moreOptions", "更多选项")}
            >
              <span className={styles.capsuleDots}>
                <span></span>
                <span></span>
                <span></span>
              </span>
            </button>
          </Dropdown>
          <div className={styles.capsuleDivider}></div>
          <button
            className={styles.capsuleBtn}
            onClick={handleBack}
            title={t("appCenter.backToListHint", "返回应用列表 (ESC)")}
          >
            <CircleX className={styles.capsuleCloseIcon} size={20} />
          </button>
        </div>

        <div className={styles.embedFrame}>
          {AppComponent ? (
            <ChunkErrorBoundary resetKey={activeApp.id}>
              <AppComponent />
            </ChunkErrorBoundary>
          ) : (
            <Empty
              image={<AppWindow size={48} strokeWidth={1} />}
              description={t(
                "appCenter.appNotLoaded",
                "This app is not loaded yet.",
              )}
              style={{ marginTop: 48 }}
            />
          )}
        </div>
      </div>
    );
  }

  const hasActiveFilters = Boolean(searchQuery) || categoryFilter !== "all";

  const clearFilters = () => {
    setSearchQuery("");
    setCategoryFilter("all");
  };

  const installedContent = (
    <>
      {/* Search & Filter — only useful once apps exist */}
      {apps.length > 0 && (
        <div className={styles.toolbar}>
          <Input
            prefix={<Search size={14} />}
            placeholder={t("appCenter.search", "Search apps...")}
            aria-label={t("appCenter.search", "Search apps...")}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className={styles.searchInput}
            allowClear
          />
          {categories.length > 0 && (
            <Select
              value={categoryFilter}
              onChange={setCategoryFilter}
              className={styles.categorySelect}
            >
              <Option value="all">{t("appCenter.allCategories", "All")}</Option>
              {categories.map((cat) => (
                <Option key={cat} value={cat}>
                  {cat}
                </Option>
              ))}
            </Select>
          )}
          <div className={styles.toolbarSpacer} />
          <button
            className={styles.refreshBtn}
            onClick={fetchApps}
            aria-label={t("common.refresh", "Refresh")}
            title={t("common.refresh", "Refresh")}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      )}

      {/* App Grid */}
      {loading ? (
        <div className={styles.stateBlock}>
          <Spin />
        </div>
      ) : loadError ? (
        <Empty
          image={<AppWindow size={44} strokeWidth={1} />}
          description={t(
            "appCenter.loadFailed",
            "Failed to load apps. Please retry.",
          )}
          className={styles.stateBlock}
        >
          <Button icon={<RefreshCw size={14} />} onClick={fetchApps}>
            {t("common.retry", "Retry")}
          </Button>
        </Empty>
      ) : apps.length === 0 ? (
        <Empty
          image={<AppWindow size={44} strokeWidth={1} />}
          description={t("appCenter.noApps", "No apps installed yet")}
          className={styles.stateBlock}
        >
          <div className={styles.emptyActions}>
            <Button
              type="primary"
              icon={<BadgeCheck size={14} />}
              onClick={() => switchView("official")}
            >
              {t("appCenter.browseOfficialApps", "浏览官方应用")}
            </Button>
            <Button
              icon={<Store size={14} />}
              onClick={() => switchView("market")}
            >
              {t("appCenter.browseMarket", "浏览应用市场")}
            </Button>
          </div>
        </Empty>
      ) : filteredApps.length === 0 ? (
        <Empty
          image={<AppWindow size={44} strokeWidth={1} />}
          description={t("appCenter.noResults", "No apps match your search")}
          className={styles.stateBlock}
        >
          {hasActiveFilters && (
            <Button onClick={clearFilters}>
              {t("appCenter.clearFilters", "清除筛选")}
            </Button>
          )}
        </Empty>
      ) : (
        <div className={styles.gridLarge}>
          {filteredApps.map((app) => (
            <AppCard
              key={app.id}
              app={app}
              onClick={handleAppClick}
              onUninstall={handleUninstall}
            />
          ))}
        </div>
      )}
    </>
  );

  return (
    <div className={styles.page}>
      <PageHeader current={t("nav.apps", "Apps")} />

      <div className={styles.pageBody}>
        <div className={styles.pageInner}>
          <p className={styles.subtitle}>
            {t(
              "appCenter.subtitle",
              "管理已安装的应用，或从官方与社区渠道扩展工作空间。",
            )}
          </p>

          {/* Tabs act purely as the accessible view switcher; content is
              rendered in mutually exclusive branches below so official /
              market data components are only mounted while active. */}
          <Tabs
            activeKey={view}
            onChange={(key) => switchView(key as AppCenterView)}
            className={styles.viewTabs}
            items={[
              {
                key: "installed",
                label: (
                  <span className={styles.tabLabel}>
                    <LayoutGrid size={15} />
                    {t("appCenter.myApps", "我的应用")}
                    {!loading && !loadError && (
                      <span
                        className={styles.countBadge}
                        aria-label={t("appCenter.installedCount", {
                          count: apps.length,
                          defaultValue: `${apps.length} 个应用`,
                        })}
                      >
                        {apps.length}
                      </span>
                    )}
                  </span>
                ),
              },
              {
                key: "official",
                label: (
                  <span className={styles.tabLabel}>
                    <BadgeCheck size={15} />
                    {t("appCenter.officialApps", "官方应用")}
                  </span>
                ),
              },
              {
                key: "market",
                label: (
                  <span className={styles.tabLabel}>
                    <Store size={15} />
                    {t("appCenter.appMarket", "应用市场")}
                  </span>
                ),
              },
            ]}
          />

          {/* External-data views are mounted (chunk + request) only while
              the user is actually on the corresponding tab. */}
          {view === "official" ? (
            <Suspense
              fallback={
                <div className={styles.stateBlock}>
                  <Spin />
                </div>
              }
            >
              <AppMarket
                channel="official"
                onInstalled={handleMarketInstalled}
              />
            </Suspense>
          ) : view === "market" ? (
            <Suspense
              fallback={
                <div className={styles.stateBlock}>
                  <Spin />
                </div>
              }
            >
              <AppMarket onInstalled={handleMarketInstalled} />
            </Suspense>
          ) : (
            installedContent
          )}
        </div>
      </div>
    </div>
  );
}
