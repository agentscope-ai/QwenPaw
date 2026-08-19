/**
 * MenuBar.tsx — macOS-style top menu bar.
 *
 * Left: brand mark + current Space (agent) name + the focused app's title.
 * Right: Mission Control, status glyphs, and a clock. The Space name and the
 * Mission Control button both open the Spaces switcher.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Tooltip } from "antd";
import {
  LayoutPanelTop,
  Bell,
  Wifi,
  Volume2,
  BatteryFull,
  ArrowLeft,
  Monitor,
} from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import { useShallow } from "zustand/react/shallow";
import { useOsWindows } from "./osWindowStore";
import { useOsNotify } from "./osNotifyStore";
import { resolveAppDef } from "./osAppRegistry";
import { useOsStyles } from "./useOsStyles";
import { getConsoleRootHref } from "../utils/navigationMode";
import LanguageSwitcher from "../components/LanguageSwitcher";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export default function MenuBar({ hidden = false }: { hidden?: boolean }) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const { agents } = useAgentStore();
  // Narrow subscription: geometry updates never re-render the menu bar.
  const { spaceId, activeId, missionControlOpen, setMissionControl } =
    useOsWindows(
      useShallow((s) => ({
        spaceId: s.spaceId,
        activeId: s.activeId,
        missionControlOpen: s.missionControlOpen,
        setMissionControl: s.setMissionControl,
      })),
    );
  const { approvalCount, inboxCount, centerOpen, setCenter } = useOsNotify();
  const unread = approvalCount + inboxCount;
  const notificationLabel = t("os.notificationSummary", {
    approvals: approvalCount,
    inbox: inboxCount,
    defaultValue: `Approvals ${approvalCount} · Inbox ${inboxCount}`,
  });
  const now = useClock();

  const spaceName = agents.find((a) => a.id === spaceId)?.name ?? spaceId;
  const activeApp = activeId ? resolveAppDef(activeId) : undefined;
  const activeTitle = activeApp
    ? t(activeApp.labelKey, activeApp.fallback)
    : t("os.finder", "Desktop");

  const time = now.toLocaleTimeString(undefined, {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div
      className={cx(
        styles.menubar,
        hidden ? styles.menubarHidden : styles.menubarShown,
      )}
    >
      <div className={styles.menubarLeft}>
        <Dropdown
          placement="bottomLeft"
          trigger={["click"]}
          menu={{
            items: [
              {
                key: "desktop",
                disabled: true,
                icon: <Monitor size={14} />,
                label: t("os.desktopMode", "Desktop mode"),
              },
              { type: "divider" },
              {
                key: "console",
                icon: <ArrowLeft size={14} />,
                label: t("os.returnToConsole", "Return to console"),
                onClick: () =>
                  window.location.assign(
                    getConsoleRootHref(window.location.pathname),
                  ),
              },
            ],
          }}
        >
          <button
            type="button"
            className={styles.menubarBrand}
            title={t("os.qwenpawMenu", "QwenPaw menu")}
            aria-label={t("os.qwenpawMenu", "QwenPaw menu")}
          >
            <img src="/qwenpaw.png" alt="QwenPaw" />
          </button>
        </Dropdown>
        <Tooltip
          title={t("os.currentSpaceLabel", {
            name: spaceName,
            defaultValue: `Current space: ${spaceName}`,
          })}
        >
          <span
            className={styles.menubarName}
            role="button"
            tabIndex={0}
            aria-label={t("os.currentSpace", "Current space")}
            onClick={() => setMissionControl(!missionControlOpen)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setMissionControl(!missionControlOpen);
              }
            }}
          >
            {spaceName}
          </span>
        </Tooltip>
        <Tooltip
          title={t("os.currentAppLabel", {
            name: activeTitle,
            defaultValue: `Current app: ${activeTitle}`,
          })}
        >
          <span className={styles.menubarItem} style={{ fontWeight: 600 }}>
            {activeTitle}
          </span>
        </Tooltip>
      </div>

      <div className={styles.menubarRight}>
        <LanguageSwitcher />
        <Tooltip title={notificationLabel}>
          <button
            type="button"
            className={styles.notificationMenuButton}
            aria-label={`${t(
              "os.notifications",
              "Notifications",
            )}: ${notificationLabel}`}
            onClick={() => setCenter(!centerOpen)}
          >
            <Bell size={15} />
            {unread > 0 && (
              <span className={styles.notificationMenuCount} aria-hidden>
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </button>
        </Tooltip>
        <button
          className={styles.menubarBtn}
          title={t("os.missionControl", "Mission Control")}
          aria-label={t("os.missionControl", "Mission Control")}
          onClick={() => setMissionControl(!missionControlOpen)}
        >
          <LayoutPanelTop size={15} />
        </button>
        <BatteryFull size={16} />
        <Wifi size={14} />
        <Volume2 size={14} />
        <span>{time}</span>
      </div>
    </div>
  );
}
