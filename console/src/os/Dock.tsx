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
import { useShallow } from "zustand/react/shallow";
import { useOsWindows } from "./osWindowStore";
import { useOsNotify } from "./osNotifyStore";
import { useOsApps } from "./osAppRegistry";
import { buttonRoleProps } from "./a11y";
import { useOsStyles } from "./useOsStyles";

export default function Dock({ revealed = true }: { revealed?: boolean }) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  // Narrow subscriptions: actions are referentially stable and `order`
  // only changes on open/close, so window drags never re-render the Dock.
  const { open, setLauncher, close, focus } = useOsWindows(
    useShallow((s) => ({
      open: s.open,
      setLauncher: s.setLauncher,
      close: s.close,
      focus: s.focus,
    })),
  );
  const launcherOpen = useOsWindows((s) => s.launcherOpen);
  const order = useOsWindows((s) => s.order);
  const { approvalCount, inboxCount } = useOsNotify();
  const { apps } = useOsApps();
  const inboxBadge = approvalCount + inboxCount;
  const [hovered, setHovered] = useState<string | null>(null);

  const runningIds = useMemo(() => new Set(order), [order]);

  return (
    <div
      className={cx(styles.dock, !revealed && styles.dockHidden)}
      role="toolbar"
      aria-label={t("os.dock", "Dock")}
    >
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
        const running = runningIds.has(a.routeId);
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
                  onClick: () => (running ? focus(a.routeId) : open(a.routeId)),
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
              onClick={() => (running ? focus(a.routeId) : open(a.routeId))}
              {...buttonRoleProps(
                () => (running ? focus(a.routeId) : open(a.routeId)),
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
