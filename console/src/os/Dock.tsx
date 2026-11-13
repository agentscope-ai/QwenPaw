/** macOS-style editable Dock for the Desktop OS shell. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Tooltip } from "antd";
import {
  ArrowLeft,
  ArrowRight,
  LayoutGrid,
  LogIn,
  Pin,
  PinOff,
  X,
} from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useOsWindows } from "./osWindowStore";
import { useOsNotify } from "./osNotifyStore";
import { useOsApps } from "./osAppRegistry";
import type { OsAppDef } from "./osApps";
import { useOsDock } from "./osDockStore";
import { buttonRoleProps } from "./a11y";
import { useOsStyles } from "./useOsStyles";
import { useOsAppLauncher } from "./useOsAppLauncher";

const DRAG_SLOP = 4;

export default function Dock({ revealed = true }: { revealed?: boolean }) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const launchApp = useOsAppLauncher();
  const { setLauncher, close, focus } = useOsWindows(
    useShallow((s) => ({
      setLauncher: s.setLauncher,
      close: s.close,
      focus: s.focus,
    })),
  );
  const launcherOpen = useOsWindows((s) => s.launcherOpen);
  const order = useOsWindows((s) => s.order);
  const { approvalCount, inboxCount } = useOsNotify();
  const { appById } = useOsApps();
  const { pinned, pin, unpin, move } = useOsDock();
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dropBeforeId, setDropBeforeId] = useState<string | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const dragRef = useRef<{
    id: string;
    x: number;
    y: number;
    moved: boolean;
    beforeId: string | null | undefined;
  } | null>(null);
  const suppressClickRef = useRef<string | null>(null);
  const suppressClickTimerRef = useRef<number | null>(null);
  useEffect(() => {
    const onDragOver = (event: Event) => {
      setDropActive((event as CustomEvent<{ active: boolean }>).detail.active);
    };
    window.addEventListener("os-dock-dragover", onDragOver);
    return () => {
      window.removeEventListener("os-dock-dragover", onDragOver);
      if (suppressClickTimerRef.current !== null) {
        window.clearTimeout(suppressClickTimerRef.current);
      }
    };
  }, []);
  const inboxBadge = approvalCount + inboxCount;
  const runningIds = useMemo(() => new Set(order), [order]);
  const pinnedSet = useMemo(() => new Set(pinned), [pinned]);
  const pinnedApps = useMemo(
    () =>
      pinned
        .map((id) => appById.get(id))
        .filter((a): a is NonNullable<typeof a> => Boolean(a)),
    [appById, pinned],
  );
  const runningApps = useMemo(
    () =>
      order
        .filter((id) => !pinnedSet.has(id))
        .map((id) => appById.get(id))
        .filter((a): a is NonNullable<typeof a> => Boolean(a)),
    [appById, order, pinnedSet],
  );

  const activate = (id: string) => {
    if (runningIds.has(id)) {
      focus(id);
      return;
    }
    void launchApp(id);
  };

  const menuFor = (a: OsAppDef) => {
    const isPinned = pinnedSet.has(a.routeId);
    const index = pinned.indexOf(a.routeId);
    const running = runningIds.has(a.routeId);
    return {
      items: [
        {
          key: "open",
          icon: <LogIn size={14} />,
          label: running ? t("os.focusApp", "Focus") : t("os.openApp", "Open"),
          onClick: () => activate(a.routeId),
        },
        ...(isPinned
          ? [
              {
                key: "move-left",
                icon: <ArrowLeft size={14} />,
                disabled: index <= 0,
                label: t("os.moveDockLeft", "Move left"),
                onClick: () => move(a.routeId, pinned[index - 1]),
              },
              {
                key: "move-right",
                icon: <ArrowRight size={14} />,
                disabled: index < 0 || index >= pinned.length - 1,
                label: t("os.moveDockRight", "Move right"),
                onClick: () => move(a.routeId, pinned[index + 2]),
              },
              {
                key: "pin",
                icon: <PinOff size={14} />,
                label: t("os.removeFromDock", "Remove from Dock"),
                onClick: () => unpin(a.routeId),
              },
            ]
          : [
              {
                key: "pin",
                icon: <Pin size={14} />,
                label: t("os.keepInDock", "Keep in Dock"),
                onClick: () => pin(a.routeId),
              },
            ]),
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
    };
  };

  const handlePointerDown = (id: string, event: React.PointerEvent) => {
    if (!pinnedSet.has(id) || event.button !== 0) return;
    dragRef.current = {
      id,
      x: event.clientX,
      y: event.clientY,
      moved: false,
      beforeId: undefined,
    };
  };
  const handlePointerMove = (event: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    if (!drag.moved) {
      if (
        Math.abs(event.clientX - drag.x) <= DRAG_SLOP &&
        Math.abs(event.clientY - drag.y) <= DRAG_SLOP
      )
        return;
      drag.moved = true;
      setDraggingId(drag.id);
      (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    }
    const pointed = document.elementFromPoint?.(event.clientX, event.clientY);
    const target = pointed?.closest<HTMLElement>("[data-os-dock-id]");
    const targetId = target?.dataset.osDockId;
    const overDock = pointed?.closest("[data-os-dock-dropzone]");
    drag.beforeId =
      targetId === drag.id
        ? undefined
        : targetId ?? (overDock ? null : undefined);
    setDropBeforeId(typeof drag.beforeId === "string" ? drag.beforeId : null);
  };
  const handlePointerEnd = (
    event: React.PointerEvent,
    suppressCompatibilityClick: boolean,
  ) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;
    if (drag.moved) {
      suppressClickRef.current = suppressCompatibilityClick ? drag.id : null;
      if (suppressClickTimerRef.current !== null) {
        window.clearTimeout(suppressClickTimerRef.current);
      }
      if (suppressCompatibilityClick) {
        suppressClickTimerRef.current = window.setTimeout(() => {
          suppressClickRef.current = null;
          suppressClickTimerRef.current = null;
        }, 0);
      }
      if (drag.beforeId !== undefined)
        move(drag.id, drag.beforeId ?? undefined);
      setDraggingId(null);
      setDropBeforeId(null);
      try {
        (event.currentTarget as HTMLElement).releasePointerCapture(
          event.pointerId,
        );
      } catch {
        /* capture already released */
      }
    }
  };

  const renderApp = (a: OsAppDef, draggable: boolean) => {
    const Icon = a.Icon;
    const running = runningIds.has(a.routeId);
    const item = (
      <div
        className={cx(
          styles.dockItem,
          draggingId === a.routeId && styles.dockItemDragging,
        )}
        data-os-dock-id={draggable ? a.routeId : undefined}
        onPointerDown={
          draggable ? (e) => handlePointerDown(a.routeId, e) : undefined
        }
        onPointerMove={draggable ? handlePointerMove : undefined}
        onPointerUp={
          draggable ? (event) => handlePointerEnd(event, true) : undefined
        }
        onPointerCancel={
          draggable ? (event) => handlePointerEnd(event, false) : undefined
        }
        onLostPointerCapture={
          draggable ? (event) => handlePointerEnd(event, false) : undefined
        }
        onClick={() => {
          if (suppressClickRef.current === a.routeId) {
            suppressClickRef.current = null;
            if (suppressClickTimerRef.current !== null) {
              window.clearTimeout(suppressClickTimerRef.current);
              suppressClickTimerRef.current = null;
            }
            return;
          }
          activate(a.routeId);
        }}
        {...buttonRoleProps(
          () => activate(a.routeId),
          t(a.labelKey, a.fallback),
        )}
      >
        {dropBeforeId === a.routeId && (
          <span className={styles.dockDropMarker} />
        )}
        <div className={styles.dockIcon} style={{ background: a.accent }}>
          <Icon size={24} />
        </div>
        {a.routeId === "core.inbox" && inboxBadge > 0 && (
          <span className={styles.dockBadge}>
            {inboxBadge > 99 ? "99+" : inboxBadge}
          </span>
        )}
        {running && <span className={styles.dockDot} />}
      </div>
    );
    return (
      <Tooltip
        key={a.routeId}
        title={t(a.labelKey, a.fallback)}
        placement="top"
      >
        <Dropdown trigger={["contextMenu"]} menu={menuFor(a)}>
          {item}
        </Dropdown>
      </Tooltip>
    );
  };

  return (
    <div
      className={cx(
        styles.dock,
        !revealed && styles.dockHidden,
        dropActive && styles.dockDropActive,
      )}
      data-os-dock-dropzone
      role="toolbar"
      aria-label={t("os.dock", "Dock")}
    >
      <Tooltip title={t("os.launchpad", "Launchpad")} placement="top">
        <div
          className={styles.dockItem}
          onClick={() => setLauncher(!launcherOpen)}
          {...buttonRoleProps(
            () => setLauncher(!launcherOpen),
            t("os.launchpad", "Launchpad"),
          )}
        >
          <div className={styles.dockIcon} style={{ background: "#334155" }}>
            <LayoutGrid size={24} />
          </div>
        </div>
      </Tooltip>
      <div className={styles.dockDivider} />
      {pinnedApps.map((a) => renderApp(a, true))}
      {runningApps.length > 0 && <div className={styles.dockDivider} />}
      {runningApps.map((a) => renderApp(a, false))}
    </div>
  );
}
