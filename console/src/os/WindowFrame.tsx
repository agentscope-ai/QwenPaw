/**
 * WindowFrame.tsx — A single draggable / resizable OS window.
 *
 * Reads geometry from osWindowStore and renders app content passed as
 * children. Dragging uses pointer events on the header; resizing works from
 * every edge and corner (8 directions), with a visible grip at the
 * bottom-right. Maximise fills the desktop minus the taskbar.
 * On small viewports windows are forced full-screen and drag is disabled.
 *
 * Gesture geometry is transient: pointermove writes straight to the DOM
 * (coalesced per animation frame) and the final rect is committed to the
 * store once on pointerup — store subscribers and persistence stay off the
 * pointermove hot path.
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { theme as antdTheme } from "antd";
import { Minus, X, Maximize2, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useShallow } from "zustand/react/shallow";
import { useTheme } from "../contexts/ThemeContext";
import { useOsWindows, type OsWindow, type OsRect } from "./osWindowStore";
import { computeSnapRect, type SnapZone } from "./snap";
import { clampWindowY } from "./windowGeometry";
import OsAppHost from "./OsAppHost";
import { useOsStyles, MENUBAR_H } from "./useOsStyles";

interface WindowFrameProps {
  win: OsWindow;
  title: string;
  Icon: LucideIcon;
  accent: string;
  isMobile: boolean;
  /**
   * Route-backed app windows set this so the content area becomes a themed
   * surface (antd token background + text colour). Pages assume the layout
   * beneath them supplies colorBgLayout — the classic MainLayout does, so the
   * OS window must too, or light-theme pages render dark text on the dark
   * glass. OS-native apps (App Store, Settings) keep the dark glass styling.
   */
  themedSurface?: boolean;
  /** Per-app minimum size; falls back to the global window minimums. */
  minW?: number;
  minH?: number;
  children: React.ReactNode;
}

const MIN_W = 360;
const MIN_H = 260;

type ResizeDir = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

/** Invisible hit-area thickness for edge/corner resize zones. */
const RESIZE_EDGE = 6;

/** Edge + corner resize zones (the SE corner keeps the visible grip). */
const RESIZE_HANDLES: { dir: ResizeDir; style: React.CSSProperties }[] = [
  {
    dir: "n",
    style: {
      top: -RESIZE_EDGE / 2,
      left: RESIZE_EDGE,
      right: RESIZE_EDGE,
      height: RESIZE_EDGE,
      cursor: "ns-resize",
    },
  },
  {
    dir: "s",
    style: {
      bottom: -RESIZE_EDGE / 2,
      left: RESIZE_EDGE,
      right: RESIZE_EDGE,
      height: RESIZE_EDGE,
      cursor: "ns-resize",
    },
  },
  {
    dir: "e",
    style: {
      right: -RESIZE_EDGE / 2,
      top: RESIZE_EDGE,
      bottom: RESIZE_EDGE,
      width: RESIZE_EDGE,
      cursor: "ew-resize",
    },
  },
  {
    dir: "w",
    style: {
      left: -RESIZE_EDGE / 2,
      top: RESIZE_EDGE,
      bottom: RESIZE_EDGE,
      width: RESIZE_EDGE,
      cursor: "ew-resize",
    },
  },
  {
    dir: "nw",
    style: {
      top: -RESIZE_EDGE / 2,
      left: -RESIZE_EDGE / 2,
      width: RESIZE_EDGE * 2,
      height: RESIZE_EDGE * 2,
      cursor: "nwse-resize",
    },
  },
  {
    dir: "ne",
    style: {
      top: -RESIZE_EDGE / 2,
      right: -RESIZE_EDGE / 2,
      width: RESIZE_EDGE * 2,
      height: RESIZE_EDGE * 2,
      cursor: "nesw-resize",
    },
  },
  {
    dir: "sw",
    style: {
      bottom: -RESIZE_EDGE / 2,
      left: -RESIZE_EDGE / 2,
      width: RESIZE_EDGE * 2,
      height: RESIZE_EDGE * 2,
      cursor: "nesw-resize",
    },
  },
];

export default function WindowFrame({
  win,
  title,
  Icon,
  accent,
  isMobile,
  themedSurface = false,
  minW = MIN_W,
  minH = MIN_H,
  children,
}: WindowFrameProps) {
  const { styles, cx } = useOsStyles();
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const { token } = antdTheme.useToken();
  // Actions only (referentially stable) + a boolean activity flag — this
  // frame re-renders when ITS activation flips, not on every store change.
  const { focus, close, minimize, toggleMaximize, move, resize, snap } =
    useOsWindows(
      useShallow((s) => ({
        focus: s.focus,
        close: s.close,
        minimize: s.minimize,
        toggleMaximize: s.toggleMaximize,
        move: s.move,
        resize: s.resize,
        snap: s.snap,
      })),
    );
  const isActive = useOsWindows((s) => s.activeId === win.id);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<
    ({ dir: ResizeDir; sx: number; sy: number } & OsRect) | null
  >(null);
  // Transient gesture geometry: applied to the DOM each animation frame and
  // committed to the store once when the gesture ends.
  const frameRef = useRef<HTMLDivElement | null>(null);
  const pendingRef = useRef<Partial<OsRect> | null>(null);
  const rafRef = useRef<number | null>(null);
  // Live edge-snap zone while dragging the header; drives the preview overlay.
  const [snapZone, setSnapZone] = useState<SnapZone | null>(null);
  // Minimize animation: keep the frame mounted briefly to play the transition.
  const [minimizing, setMinimizing] = useState(false);

  const isFull = win.maximized || isMobile;
  const closeLabel = t("common.close", "Close");
  const minimizeLabel = t("os.minimize", "Minimize");
  const zoomLabel = isFull
    ? t("common.restore", "Restore")
    : t("os.zoom", "Zoom");

  const onWindowKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.target !== event.currentTarget || !event.altKey || isFull) {
        return;
      }
      const step = 20;
      const direction = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      }[event.key];
      if (!direction) return;

      event.preventDefault();
      const [dx, dy] = direction;
      if (event.shiftKey) {
        resize(win.id, {
          w: Math.max(minW, win.w + dx),
          h: Math.max(minH, win.h + dy),
        });
      } else {
        move(
          win.id,
          Math.max(0, win.x + dx),
          clampWindowY(win.y + dy, win.h, window.innerHeight),
        );
      }
    },
    [isFull, minH, minW, move, resize, win],
  );

  const writeRect = useCallback((rect: Partial<OsRect>) => {
    const el = frameRef.current;
    if (!el) return;
    if (rect.x !== undefined) el.style.left = `${rect.x}px`;
    if (rect.y !== undefined) el.style.top = `${rect.y}px`;
    if (rect.w !== undefined) el.style.width = `${rect.w}px`;
    if (rect.h !== undefined) el.style.height = `${rect.h}px`;
  }, []);

  // Write the pending gesture rect to the DOM (idempotent, cheap no-op
  // when no gesture is in flight).
  const applyRect = useCallback(() => {
    const rect = pendingRef.current;
    if (rect) writeRect(rect);
  }, [writeRect]);

  // Undo transient DOM writes before React reconciles the store commit.
  // Otherwise unchanged VDOM style fields can retain stale inline values.
  const restoreCommittedRect = useCallback(() => {
    writeRect({ x: win.x, y: win.y, w: win.w, h: win.h });
  }, [win.h, win.w, win.x, win.y, writeRect]);

  const onFrame = useCallback(() => {
    rafRef.current = null;
    applyRect();
  }, [applyRect]);

  const queueApply = useCallback(
    (rect: Partial<OsRect>) => {
      pendingRef.current = { ...pendingRef.current, ...rect };
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(onFrame);
      }
    },
    [onFrame],
  );

  // Mid-gesture re-renders (snap preview state) reset the inline styles
  // from props — re-apply the transient rect before paint.
  useLayoutEffect(() => {
    applyRect();
  });

  /** Stop frame scheduling and return the gesture's final rect (if any). */
  const takeGestureRect = useCallback((): Partial<OsRect> | null => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    const rect = pendingRef.current;
    pendingRef.current = null;
    return rect;
  }, []);

  useEffect(
    () => () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  const onHeaderPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if ((e.target as HTMLElement).closest("button")) return;
      focus(win.id);
      if (isFull) return;
      dragRef.current = { dx: e.clientX - win.x, dy: e.clientY - win.y };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [focus, isFull, win.id, win.x, win.y],
  );

  const onHeaderPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragRef.current) return;
      const maxX = window.innerWidth - 80;
      const nx = Math.min(Math.max(0, e.clientX - dragRef.current.dx), maxX);
      const ny = clampWindowY(
        e.clientY - dragRef.current.dy,
        win.h,
        window.innerHeight,
      );
      // Transient: DOM only — the store is untouched until pointerup.
      queueApply({ x: nx, y: ny });
      const EDGE = 12;
      if (e.clientY <= MENUBAR_H + EDGE) setSnapZone("maximize");
      else if (e.clientX <= EDGE) setSnapZone("left");
      else if (e.clientX >= window.innerWidth - EDGE) setSnapZone("right");
      else setSnapZone(null);
    },
    [queueApply, win.h],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent) => {
      // Finalizes the gesture. Also bound to pointercancel and
      // lostpointercapture so system-cancelled gestures (touch, app
      // switch, OS gestures) still commit the last on-screen position;
      // idempotent, so the capture-release cascade is harmless.
      const wasDragging = dragRef.current !== null;
      dragRef.current = null;
      const rect = takeGestureRect();
      if (wasDragging) restoreCommittedRect();
      if (wasDragging && snapZone) {
        snap(win.id, snapZone);
        setSnapZone(null);
      } else if (wasDragging && rect?.x !== undefined && rect.y !== undefined) {
        // Single commit: one store update (and one persisted write) per drag.
        move(win.id, rect.x, rect.y);
      }
      try {
        (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {
        /* pointer may already be released */
      }
    },
    [snapZone, snap, move, restoreCommittedRect, takeGestureRect, win.id],
  );

  const onResizePointerDown = useCallback(
    (e: React.PointerEvent, dir: ResizeDir) => {
      e.stopPropagation();
      focus(win.id);
      resizeRef.current = {
        dir,
        sx: e.clientX,
        sy: e.clientY,
        x: win.x,
        y: win.y,
        w: win.w,
        h: win.h,
      };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [focus, win.id, win.x, win.y, win.w, win.h],
  );

  const onResizePointerMove = useCallback(
    (e: React.PointerEvent) => {
      const r = resizeRef.current;
      if (!r) return;
      const dx = e.clientX - r.sx;
      const dy = e.clientY - r.sy;
      const rect: Partial<OsRect> = {};
      if (r.dir.includes("e")) rect.w = Math.max(minW, r.w + dx);
      if (r.dir.includes("s")) rect.h = Math.max(minH, r.h + dy);
      if (r.dir.includes("w")) {
        // Left edge moves: keep the right edge anchored.
        const nw = Math.max(minW, r.w - dx);
        rect.w = nw;
        rect.x = r.x + (r.w - nw);
      }
      if (r.dir.includes("n")) {
        // Top edge moves: keep the bottom edge anchored, never cross the menu bar.
        let nh = Math.max(minH, r.h - dy);
        let ny = r.y + (r.h - nh);
        if (ny < MENUBAR_H) {
          ny = MENUBAR_H;
          nh = r.y + r.h - MENUBAR_H;
        }
        rect.h = nh;
        rect.y = ny;
      }
      // Transient: DOM only — the store is untouched until pointerup.
      queueApply(rect);
    },
    [queueApply, minW, minH],
  );

  const endResize = useCallback(
    (e: React.PointerEvent) => {
      // Same finalize-on-cancel semantics as endDrag; idempotent.
      const wasResizing = resizeRef.current !== null;
      resizeRef.current = null;
      const rect = takeGestureRect();
      if (wasResizing) restoreCommittedRect();
      if (wasResizing && rect) {
        // Single commit: one store update (and one persisted write) per
        // resize gesture.
        resize(win.id, rect);
      }
      try {
        (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {
        /* noop */
      }
    },
    [resize, restoreCommittedRect, takeGestureRect, win.id],
  );

  const handleMinimize = useCallback(() => {
    setMinimizing(true);
    window.setTimeout(() => {
      setMinimizing(false);
      minimize(win.id);
    }, 200);
  }, [minimize, win.id]);

  const geometry: React.CSSProperties = isFull
    ? {
        left: 0,
        top: MENUBAR_H,
        width: "100%",
        height: `calc(100% - ${MENUBAR_H}px)`,
        borderRadius: 0,
        zIndex: win.z,
      }
    : {
        left: win.x,
        top: win.y,
        width: win.w,
        height: win.h,
        zIndex: win.z,
      };

  // Themed surface for route-backed pages: in dark mode the existing glass
  // already matches the dark tokens; in light mode swap in the theme
  // background so light-theme pages stay readable.
  const contentStyle: React.CSSProperties | undefined = themedSurface
    ? {
        background: isDark ? undefined : token.colorBgLayout,
        color: token.colorText,
      }
    : undefined;

  if (win.minimized) return null;

  return (
    <div
      ref={frameRef}
      className={cx(
        styles.window,
        isActive && styles.windowActive,
        minimizing && styles.windowMinimizing,
      )}
      style={geometry}
      onPointerDown={() => focus(win.id)}
      onFocus={() => focus(win.id)}
      onKeyDown={onWindowKeyDown}
      role="group"
      tabIndex={0}
      aria-label={title}
      aria-keyshortcuts="Alt+ArrowLeft Alt+ArrowRight Alt+ArrowUp Alt+ArrowDown Alt+Shift+ArrowLeft Alt+Shift+ArrowRight Alt+Shift+ArrowUp Alt+Shift+ArrowDown"
    >
      {snapZone && <SnapPreview zone={snapZone} />}
      <div
        className={styles.headerMac}
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onLostPointerCapture={endDrag}
        onDoubleClick={() => !isMobile && toggleMaximize(win.id)}
        data-active={isActive ? "true" : "false"}
      >
        <div className={styles.lights}>
          <button
            className={cx(styles.light, styles.lightClose)}
            title={closeLabel}
            aria-label={closeLabel}
            onClick={() => close(win.id)}
          >
            <X size={8} strokeWidth={3} />
          </button>
          <button
            className={cx(styles.light, styles.lightMin)}
            title={minimizeLabel}
            aria-label={minimizeLabel}
            onClick={handleMinimize}
          >
            <Minus size={8} strokeWidth={3} />
          </button>
          <button
            className={cx(styles.light, styles.lightMax)}
            title={zoomLabel}
            aria-label={zoomLabel}
            disabled={isMobile}
            onClick={() => !isMobile && toggleMaximize(win.id)}
          >
            <Maximize2 size={7} strokeWidth={3} />
          </button>
        </div>
        <div className={styles.macTitle} title={title}>
          <Icon size={14} color={accent} />
          {title}
        </div>
        {/* Right spacer keeps the title visually centred. */}
        <div style={{ width: 70 }} />
      </div>

      <OsAppHost
        contentClassName={cx(styles.content, "os-window-body")}
        contentStyle={contentStyle}
      >
        {children}
      </OsAppHost>

      {!isFull && (
        <>
          {RESIZE_HANDLES.map(({ dir, style }) => (
            <div
              key={dir}
              className={styles.resizeArea}
              style={style}
              onPointerDown={(e) => onResizePointerDown(e, dir)}
              onPointerMove={onResizePointerMove}
              onPointerUp={endResize}
              onPointerCancel={endResize}
              onLostPointerCapture={endResize}
            />
          ))}
          <div
            className={styles.resizeHandle}
            onPointerDown={(e) => onResizePointerDown(e, "se")}
            onPointerMove={onResizePointerMove}
            onPointerUp={endResize}
            onPointerCancel={endResize}
            onLostPointerCapture={endResize}
          />
        </>
      )}
    </div>
  );
}

function SnapPreview({ zone }: { zone: SnapZone }) {
  const { styles } = useOsStyles();
  const r = computeSnapRect(zone, window.innerWidth, window.innerHeight);
  return (
    <div
      className={styles.snapPreview}
      style={{
        position: "fixed",
        left: r.x,
        top: r.y,
        width: r.w,
        height: r.h,
      }}
    />
  );
}
