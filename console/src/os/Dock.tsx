/**
 * Dock.tsx — macOS-style bottom Dock.
 *
 * Shows the App Store (system) plus installed apps as magnifying icons. A
 * running app gets an indicator dot; clicking opens or focuses its window.
 * The launcher and Mission Control both remain reachable from the menu bar,
 * so the Dock stays focused on apps like macOS.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown } from "antd";
import { LayoutGrid, LogIn, X } from "lucide-react";
import { useRoutes } from "../plugins/registry/hooks";
import { useOsWindows } from "./osWindowStore";
import { useOsPlugins } from "./osPluginStore";
import { useOsNotify } from "./osNotifyStore";
import { OS_APPS, STORE_APP, SETTINGS_APP, type OsAppDef } from "./osApps";
import { usePluginApps } from "./usePluginApps";
import { buttonRoleProps } from "./a11y";
import { useOsStyles } from "./useOsStyles";

export default function Dock({ revealed = true }: { revealed?: boolean }) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const routes = useRoutes();
  const { windows, open, launcherOpen, setLauncher, close, focus } =
    useOsWindows();
  const { installed } = useOsPlugins();
  const { approvalCount, inboxCount } = useOsNotify();
  const pluginApps = usePluginApps();
  const inboxBadge = approvalCount + inboxCount;
  const [hovered, setHovered] = useState<string | null>(null);

  const apps: OsAppDef[] = useMemo(() => {
    const availableIds = new Set(routes.map((r) => r.id));
    const installedSet = new Set(installed);
    const catalog = OS_APPS.filter(
      (a) => availableIds.has(a.routeId) && installedSet.has(a.routeId),
    );
    return [STORE_APP, ...catalog, ...pluginApps, SETTINGS_APP];
  }, [routes, installed, pluginApps]);

  return (
    <div className={cx(styles.dock, !revealed && styles.dockHidden)}>
      {/* Launchpad-style entry */}
      <div
        className={styles.dockItem}
        onMouseEnter={() => setHovered("__launcher")}
        onMouseLeave={() => setHovered(null)}
        onClick={() => setLauncher(!launcherOpen)}
        {...buttonRoleProps(
          () => setLauncher(!launcherOpen),
          t("os.launchpad", "Launchpad"),
        )}
      >
        <div className={styles.dockIcon} style={{ background: "#334155" }}>
          <LayoutGrid size={24} />
        </div>
        <div
          className={styles.dockTooltip}
          style={{ opacity: hovered === "__launcher" ? 1 : 0 }}
        >
          {t("os.launchpad", "Launchpad")}
        </div>
      </div>

      <div className={styles.dockDivider} />

      {apps.map((a) => {
        const Icon = a.Icon;
        const running = Boolean(windows[a.routeId]);
        return (
          <Dropdown
            key={a.routeId}
            trigger={["contextMenu"]}
            menu={{
              items: [
                {
                  key: "open",
                  icon: <LogIn size={14} />,
                  label: running
                    ? t("os.focusApp", "Focus")
                    : t("os.openApp", "Open"),
                  onClick: () =>
                    running
                      ? focus(a.routeId)
                      : open(a.routeId, { w: a.defaultW, h: a.defaultH }),
                },
                ...(running
                  ? [
                      {
                        key: "close",
                        danger: true,
                        icon: <X size={14} />,
                        label: t("os.closeApp", "Close"),
                        onClick: () => close(a.routeId),
                      },
                    ]
                  : []),
              ],
            }}
          >
            <div
              className={styles.dockItem}
              onMouseEnter={() => setHovered(a.routeId)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => open(a.routeId, { w: a.defaultW, h: a.defaultH })}
              {...buttonRoleProps(
                () => open(a.routeId, { w: a.defaultW, h: a.defaultH }),
                t(a.labelKey, a.fallback),
              )}
            >
              <div className={styles.dockIcon} style={{ background: a.accent }}>
                <Icon size={24} />
              </div>
              {a.routeId === "core.inbox" && inboxBadge > 0 && (
                <span className={styles.dockBadge}>
                  {inboxBadge > 99 ? "99+" : inboxBadge}
                </span>
              )}
              {running && <span className={styles.dockDot} />}
              <div
                className={styles.dockTooltip}
                style={{ opacity: hovered === a.routeId ? 1 : 0 }}
              >
                {t(a.labelKey, a.fallback)}
              </div>
            </div>
          </Dropdown>
        );
      })}
    </div>
  );
}
