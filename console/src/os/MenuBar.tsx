/**
 * MenuBar.tsx — macOS-style top menu bar.
 *
 * Left: brand mark + current Space (agent) name + the focused app's title.
 * Right: Mission Control, status glyphs, and a clock. The Space name and the
 * Mission Control button both open the Spaces switcher.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Command,
  LayoutPanelTop,
  Bell,
  Wifi,
  Volume2,
  BatteryFull,
} from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import { useShallow } from "zustand/react/shallow";
import { useOsWindows } from "./osWindowStore";
import { useOsNotify, unreadNotifyCount } from "./osNotifyStore";
import { resolveAppDef } from "./osAppRegistry";
import { useOsStyles } from "./useOsStyles";

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
  const { history, centerOpen, setCenter } = useOsNotify();
  const unread = unreadNotifyCount(history);
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
        <span className={styles.menubarBrand}>
          <Command size={15} />
        </span>
        <span
          className={styles.menubarName}
          style={{ cursor: "pointer" }}
          onClick={() => setMissionControl(!missionControlOpen)}
          title={t("os.currentSpace", "Current space")}
        >
          {spaceName}
        </span>
        <span className={styles.menubarItem} style={{ fontWeight: 600 }}>
          {activeTitle}
        </span>
      </div>

      <div className={styles.menubarRight}>
        <span className={styles.bellWrap}>
          <button
            className={styles.menubarBtn}
            title={t("os.notifications", "Notifications")}
            onClick={() => setCenter(!centerOpen)}
          >
            <Bell size={15} />
          </button>
          {unread > 0 && (
            <span className={styles.bellBadge}>
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </span>
        <button
          className={styles.menubarBtn}
          title={t("os.missionControl", "Mission Control")}
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
