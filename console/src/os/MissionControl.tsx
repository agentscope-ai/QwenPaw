/**
 * MissionControl.tsx — macOS-style Spaces switcher.
 *
 * Each agent is a "Space" with its own window layout (persisted in
 * osWindowStore.saved). The top row lists agent-spaces; clicking one switches
 * the whole desktop to that agent (like switching full-screen apps in macOS).
 * The lower grid shows the current space's open windows for quick focus.
 */
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { useAgentStore } from "../stores/agentStore";
import { useShallow } from "zustand/react/shallow";
import { useOsWindows } from "./osWindowStore";
import { OS_APPS } from "./osApps";
import { resolveAppDef } from "./osAppRegistry";
import { buttonRoleProps } from "./a11y";
import { useOsStyles } from "./useOsStyles";

const SPACE_COLORS = [
  "#FF7F16",
  "#3b82f6",
  "#8b5cf6",
  "#10b981",
  "#ec4899",
  "#06b6d4",
  "#f59e0b",
];

function colorFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1)
    hash = id.charCodeAt(i) + ((hash << 5) - hash);
  return SPACE_COLORS[Math.abs(hash) % SPACE_COLORS.length];
}

export default function MissionControl() {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const { agents, selectedAgent, setSelectedAgent } = useAgentStore();
  // Narrow subscription: Mission Control is an overlay — it needs layout
  // fields, not per-frame geometry (drags don't happen while it's open).
  const {
    spaceId,
    saved,
    windows,
    order,
    switchSpace,
    focus,
    setMissionControl,
  } = useOsWindows(
    useShallow((s) => ({
      spaceId: s.spaceId,
      saved: s.saved,
      windows: s.windows,
      order: s.order,
      switchSpace: s.switchSpace,
      focus: s.focus,
      setMissionControl: s.setMissionControl,
    })),
  );

  // Ensure the current agent always appears as a space even before the agent
  // list loads from the backend.
  const spaces = useMemo(() => {
    const list = agents.map((a) => ({ id: a.id, name: a.name }));
    if (!list.some((s) => s.id === selectedAgent)) {
      list.unshift({ id: selectedAgent, name: selectedAgent });
    }
    return list;
  }, [agents, selectedAgent]);

  const windowCountFor = (id: string): number => {
    if (id === spaceId) return order.length;
    return saved[id]?.order.length ?? 0;
  };

  const openWindows = order
    .map((id) => windows[id])
    .filter((w): w is NonNullable<typeof w> => Boolean(w));

  const selectSpace = (id: string) => {
    setSelectedAgent(id);
    switchSpace(id);
  };

  return (
    <div
      className={styles.mcOverlay}
      role="dialog"
      aria-modal="true"
      aria-label={t("os.missionControl", "Mission Control")}
      onClick={() => setMissionControl(false)}
    >
      {/* Spaces row */}
      <div className={styles.mcSpaces} onClick={(e) => e.stopPropagation()}>
        {spaces.map((s) => {
          const active = s.id === spaceId;
          const initial = (s.name || s.id).charAt(0).toUpperCase();
          return (
            <div
              key={s.id}
              className={cx(styles.mcSpaceCard, active && styles.mcSpaceActive)}
              onClick={() => selectSpace(s.id)}
              {...buttonRoleProps(() => selectSpace(s.id), s.name || s.id)}
            >
              <div className="avatar" style={{ background: colorFor(s.id) }}>
                {initial}
              </div>
              <div className="name">{s.name}</div>
              <div className="count">
                {windowCountFor(s.id)} {t("os.windows", "windows")}
              </div>
            </div>
          );
        })}
      </div>

      {/* Current space windows */}
      <div className={styles.mcWindows} onClick={(e) => e.stopPropagation()}>
        {openWindows.length === 0 ? (
          <div className={styles.mcHint} style={{ gridColumn: "1 / -1" }}>
            {t("os.noOpenWindows", "No open windows in this space")}
          </div>
        ) : (
          openWindows.map((win) => {
            const def = resolveAppDef(win.id) ?? OS_APPS[0];
            const Icon = def.Icon;
            const focusWindow = () => {
              focus(win.id);
              setMissionControl(false);
            };
            return (
              <div
                key={win.id}
                className={styles.mcWindowCard}
                onClick={focusWindow}
                {...buttonRoleProps(focusWindow, t(def.labelKey, def.fallback))}
              >
                <div
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 12,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: `${def.accent}22`,
                    color: def.accent,
                  }}
                >
                  <Icon size={22} />
                </div>
                <div className="title">{t(def.labelKey, def.fallback)}</div>
              </div>
            );
          })
        )}
      </div>

      <button
        className={styles.winBtn}
        style={{ position: "absolute", top: 20, right: 24 }}
        onClick={() => setMissionControl(false)}
        title={t("common.close", "Close")}
        aria-label={t("common.close", "Close")}
      >
        <X size={18} />
      </button>
    </div>
  );
}
