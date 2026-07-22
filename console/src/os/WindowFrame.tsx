/**
 * WindowFrame.tsx — A single draggable / resizable OS window.
 *
 * Reads geometry from osWindowStore and renders app content passed as
 * children. Dragging uses pointer events on the header; resizing works from
 * every edge and corner (8 directions), with a visible grip at the
 * bottom-right. Maximise fills the desktop minus the taskbar.
 * On small viewports windows are forced full-screen and drag is disabled.
 */
import { useCallback, useRef, useState } from "react";
import { theme as antdTheme } from "antd";
import { Minus, X, Maximize2, type LucideIcon } from "lucide-react";
import { useTheme } from "../contexts/ThemeContext";
import { useOsWindows, type OsWindow, type OsRect } from "./osWindowStore";
import { computeSnapRect, type SnapZone } from "./snap";
import { OsWindowContainerContext } from "./osWindowContainer";
import { useOsStyles, MENUBAR_H, DOCK_H } from "./useOsStyles";

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
  children,
}: WindowFrameProps) {
  const { styles, cx } = useOsStyles();
  const { isDark } = useTheme();
  const { token } = antdTheme.useToken();
  const {
    focus,
    close,
    minimize,
    toggleMaximize,
    move,
    resize,
    snap,
    activeId,
  } = useOsWindows();
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<
    ({ dir: ResizeDir; sx: number; sy: number } & OsRect) | null
  >(null);
  // Exposed to descendant overlays (Drawer/Modal) as their render container so
  // they stay within this window instead of covering the whole desktop.
  const [contentEl, setContentEl] = useState<HTMLElement | null>(null);
  // Live edge-snap zone while dragging the header; drives the preview overlay.
  const [snapZone, setSnapZone] = useState<SnapZone | null>(null);
  // Minimize animation: keep the frame mounted briefly to play the transition.
  const [minimizing, setMinimizing] = useState(false);

  const isActive = activeId === win.id;
  const isFull = win.maximized || isMobile;

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
      const maxY = window.innerHeight - DOCK_H - 40;
      const nx = Math.min(Math.max(0, e.clientX - dragRef.current.dx), maxX);
      const ny = Math.min(
        Math.max(MENUBAR_H, e.clientY - dragRef.current.dy),
        maxY,
      );
      move(win.id, nx, ny);
      const EDGE = 12;
      if (e.clientY <= MENUBAR_H + EDGE) setSnapZone("maximize");
      else if (e.clientX <= EDGE) setSnapZone("left");
      else if (e.clientX >= window.innerWidth - EDGE) setSnapZone("right");
      else setSnapZone(null);
    },
    [move, win.id],
  );

  const endDrag = useCallback(
    (e: React.PointerEvent) => {
      dragRef.current = null;
      if (snapZone) {
        snap(win.id, snapZone);
        setSnapZone(null);
      }
      try {
        (e.target as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {
        /* pointer may already be released */
      }
    },
    [snapZone, snap, win.id],
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
      if (r.dir.includes("e")) rect.w = Math.max(MIN_W, r.w + dx);
      if (r.dir.includes("s")) rect.h = Math.max(MIN_H, r.h + dy);
      if (r.dir.includes("w")) {
        // Left edge moves: keep the right edge anchored.
        const nw = Math.max(MIN_W, r.w - dx);
        rect.w = nw;
        rect.x = r.x + (r.w - nw);
      }
      if (r.dir.includes("n")) {
        // Top edge moves: keep the bottom edge anchored, never cross the menu bar.
        let nh = Math.max(MIN_H, r.h - dy);
        let ny = r.y + (r.h - nh);
        if (ny < MENUBAR_H) {
          ny = MENUBAR_H;
          nh = r.y + r.h - MENUBAR_H;
        }
        rect.h = nh;
        rect.y = ny;
      }
      resize(win.id, rect);
    },
    [resize, win.id],
  );

  const endResize = useCallback((e: React.PointerEvent) => {
    resizeRef.current = null;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* noop */
    }
  }, []);

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
      className={cx(
        styles.window,
        isActive && styles.windowActive,
        minimizing && styles.windowMinimizing,
      )}
      style={geometry}
      onPointerDown={() => focus(win.id)}
    >
      {snapZone && <SnapPreview zone={snapZone} />}
      <div
        className={styles.headerMac}
        onPointerDown={onHeaderPointerDown}
        onPointerMove={onHeaderPointerMove}
        onPointerUp={endDrag}
        onDoubleClick={() => !isMobile && toggleMaximize(win.id)}
      >
        <div className={styles.lights}>
          <button
            className={cx(styles.light, styles.lightClose)}
            title="Close"
            onClick={() => close(win.id)}
          >
            <X size={8} strokeWidth={3} />
          </button>
          <button
            className={cx(styles.light, styles.lightMin)}
            title="Minimize"
            onClick={handleMinimize}
          >
            <Minus size={8} strokeWidth={3} />
          </button>
          <button
            className={cx(styles.light, styles.lightMax)}
            title="Zoom"
            onClick={() => !isMobile && toggleMaximize(win.id)}
          >
            <Maximize2 size={7} strokeWidth={3} />
          </button>
        </div>
        <div className={styles.macTitle}>
          <Icon size={14} color={accent} />
          {title}
        </div>
        {/* Right spacer keeps the title visually centred. */}
        <div style={{ width: 70 }} />
      </div>

      <div className={styles.content} style={contentStyle} ref={setContentEl}>
        <OsWindowContainerContext.Provider value={contentEl}>
          {children}
        </OsWindowContainerContext.Provider>
      </div>

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
            />
          ))}
          <div
            className={styles.resizeHandle}
            onPointerDown={(e) => onResizePointerDown(e, "se")}
            onPointerMove={onResizePointerMove}
            onPointerUp={endResize}
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
