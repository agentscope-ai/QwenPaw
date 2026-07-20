/**
 * AppCenter/index.tsx — App Center page: grid of installed PawApps.
 *
 * Lists all plugins with `meta.pawapp` from the backend. Clicking an
 * app renders its registered route component INLINE within this page
 * (no full-page navigation). The URL bar is mirrored via history.pushState
 * so path-based SDK helpers (getAppId) keep resolving.
 */
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Empty, Input, Spin, Select, Modal, Button, Dropdown } from "antd";
import type { MenuProps } from "antd";
import { AppWindow, Search, RefreshCw, Info, RotateCcw, X } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import { pawappApi } from "../../api/modules/pawapp";
import { useRoutes } from "../../plugins/registry/hooks";
import { AppCard, type AppCardData } from "./AppCard";
import { ChunkErrorBoundary } from "@/components/ChunkErrorBoundary";
import styles from "./index.module.less";

// Code-split the market so its bundle + network fetch never block the
// installed-apps section from rendering or being interacted with.
const AppMarket = lazy(() =>
  import("./AppMarket").then((m) => ({ default: m.AppMarket })),
);

const { Option } = Select;

export default function AppCenterPage() {
  const { t } = useTranslation();
  const { appId } = useParams();
  const { message } = useAppMessage();
  const routes = useRoutes();
  const [apps, setApps] = useState<AppCardData[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [activeApp, setActiveApp] = useState<AppCardData | null>(null);
  const [loadError, setLoadError] = useState(false);

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
          category: app.category ?? "",
          icon: app.icon ?? "",
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

  // Compute available categories
  const categories = useMemo(() => {
    const cats = new Set<string>();
    for (const app of apps) {
      if (app.category) cats.add(app.category);
    }
    return Array.from(cats).sort();
  }, [apps]);

  // Filter apps
  const filteredApps = useMemo(() => {
    return apps.filter((app) => {
      const matchesSearch =
        !searchQuery ||
        app.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        app.description.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCategory =
        categoryFilter === "all" || app.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [apps, searchQuery, categoryFilter]);

  const appTarget = (app: AppCardData) => app.entry_page || `/apps/${app.id}`;

  // Resolve the registered route component for the active app so it can be
  // rendered inline (no full-page navigation).
  const activeRoute = useMemo(() => {
    if (!activeApp) return null;
    const target = appTarget(activeApp);
    return routes.find((r) => r.path === target) ?? null;
  }, [activeApp, routes]);

  const handleAppClick = (app: AppCardData) => {
    // Reflect the app path in the URL bar (so path-based SDK helpers keep
    // working) WITHOUT triggering a react-router navigation, then render the
    // app inline within this page.
    window.history.pushState({ pawappInline: true }, "", appTarget(app));
    setActiveApp(app);
  };

  const handleBack = () => {
    window.history.pushState({}, "", "/apps");
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
    const onPop = () => {
      if (!/\/apps\//.test(window.location.pathname)) setActiveApp(null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

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
        key: "refresh",
        icon: <RotateCcw size={14} />,
        label: t("appCenter.refreshApp", "刷新应用"),
        onClick: () => {
          // Force reload by unmounting and remounting the app component
          setActiveApp(null);
          setTimeout(() => setActiveApp(activeApp), 0);
          message.success(t("appCenter.appRefreshed", "应用已刷新"));
        },
      },
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
                    {activeApp.description}
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
            <svg
              className={styles.capsuleCloseIcon}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
            >
              <circle cx="12" cy="12" r="9" />
            </svg>
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
                "This app is not loaded yet. Open it once from the sidebar, then retry.",
              )}
              style={{ marginTop: 48 }}
            />
          )}
        </div>
      </div>
    );
  }

  const installedContent = (
    <>
      {/* Search & Filter */}
      <div className={styles.toolbar}>
        <Input
          prefix={<Search size={14} />}
          placeholder={t("appCenter.search", "Search apps...")}
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
      </div>

      {/* App Grid */}
      <div className={styles.container}>
        {loading ? (
          <Spin
            tip={t("common.loading")}
            style={{ display: "block", margin: "10vh auto" }}
          />
        ) : loadError ? (
          <Empty
            image={<AppWindow size={48} strokeWidth={1} />}
            description={t(
              "appCenter.loadFailed",
              "Failed to load apps. Please retry.",
            )}
            style={{ marginTop: 48 }}
          >
            <Button icon={<RefreshCw size={14} />} onClick={fetchApps}>
              {t("common.retry", "Retry")}
            </Button>
          </Empty>
        ) : filteredApps.length === 0 ? (
          <Empty
            image={<AppWindow size={48} strokeWidth={1} />}
            description={
              apps.length === 0
                ? t("appCenter.noApps", "No apps installed yet")
                : t("appCenter.noResults", "No apps match your search")
            }
            style={{ marginTop: 48 }}
          />
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
      </div>
    </>
  );

  return (
    <div className={styles.page}>
      <PageHeader
        current={t("nav.apps", "Apps")}
        extra={
          <button
            className={styles.refreshBtn}
            onClick={fetchApps}
            title={t("common.refresh", "Refresh")}
          >
            <RefreshCw size={16} />
          </button>
        }
      />

      <div className={styles.pageBody}>
        {installedContent}

        {/* Deferred: only mount the market after the installed apps have
            finished loading, so it never blocks their rendering/use. The
            lazy chunk + its fetch then run asynchronously in the background. */}
        {!loading && (
          <div className={styles.marketSection}>
            <h2 className={styles.sectionTitle}>
              {t("appCenter.marketSectionTitle", "来自应用市场的更多内容")}
            </h2>
            <Suspense
              fallback={
                <Spin style={{ display: "block", margin: "24px auto" }} />
              }
            >
              <AppMarket onInstalled={fetchApps} />
            </Suspense>
          </div>
        )}
      </div>
    </div>
  );
}
