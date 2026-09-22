import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";
import {
  animate,
  motion,
  useMotionValue,
  useReducedMotion,
} from "motion/react";
import { Menu, PanelLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { constrainSidebar } from "./sidebarPlacement";
import styles from "./dockableSidebar.module.less";

const MARGIN = 12;
const DOCK_EDGE = 64;
const spring = { type: "spring" as const, stiffness: 340, damping: 36 };
interface Props {
  width: number;
  mobile: boolean;
  children: ReactNode;
  onMobileDismiss?: () => void;
}

/** One stable subtree: docking only changes its presentation, never its owner. */
export default function DockableSidebar({
  width,
  mobile,
  children,
  onMobileDismiss,
}: Props) {
  const { t } = useTranslation();
  const reduced = useReducedMotion();
  const anchor = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const handle = useRef<HTMLButtonElement>(null);
  const x = useMotionValue(0),
    y = useMotionValue(0),
    height = useMotionValue(720);
  const [floating, setFloating] = useState(false);
  const [landing, setLanding] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [dockReady, setDockReady] = useState(false);
  const flight = useRef(0);
  const controls = useRef<Array<{ stop: () => void }>>([]);
  const gesture = useRef<{
    id: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    floating: boolean;
    moved: boolean;
    lastX: number;
    lastY: number;
    time: number;
    vx: number;
    vy: number;
  } | null>(null);
  const stop = useCallback(() => {
    flight.current++;
    controls.current.forEach((control) => control.stop());
    controls.current = [];
  }, []);
  const bounds = useCallback(
    (left: number, top: number) =>
      constrainSidebar(
        { x: left, y: top },
        { width, height: Math.min(720, window.innerHeight - MARGIN * 2) },
        { width: window.innerWidth, height: window.innerHeight },
      ),
    [width],
  );
  const place = useCallback(
    (left: number, top: number) => {
      const next = bounds(left, top);
      x.set(next.x);
      y.set(next.y);
    },
    [bounds, x, y],
  );
  const resetGesture = useCallback(() => {
    const current = gesture.current;
    gesture.current = null;
    if (current && handle.current?.hasPointerCapture?.(current.id))
      handle.current.releasePointerCapture(current.id);
    setDragging(false);
    setDockReady(false);
  }, []);
  const dock = (vx = 0, vy = 0) => {
    resetGesture();
    stop();
    const target = anchor.current!.getBoundingClientRect();
    if (reduced) {
      setFloating(false);
      setLanding(false);
      x.set(0);
      y.set(0);
    } else {
      setLanding(true);
      const id = flight.current;
      const animations = [
        animate(x, target.left, { ...spring, velocity: vx }),
        animate(y, target.top, { ...spring, velocity: vy }),
        animate(height, target.height, spring),
      ];
      controls.current = animations;
      void Promise.all(animations).then(() => {
        if (id !== flight.current) return;
        setFloating(false);
        setLanding(false);
        x.set(0);
        y.set(0);
      });
    }
    handle.current?.focus({ preventScroll: true });
  };
  const cancel = useCallback(() => {
    const current = gesture.current;
    if (!current) return;
    stop();
    setLanding(false);
    setFloating(current.floating);
    x.set(current.floating ? current.originX : 0);
    y.set(current.floating ? current.originY : 0);
    resetGesture();
  }, [resetGesture, stop, x, y]);
  useEffect(() => {
    if (mobile) {
      stop();
      resetGesture();
      setFloating(false);
      setLanding(false);
      x.set(0);
      y.set(0);
    }
  }, [mobile, resetGesture, stop, x, y]);
  useEffect(() => {
    const resize = () => {
      if (floating && !landing) {
        place(x.get(), y.get());
        height.set(Math.min(720, window.innerHeight - 24));
      }
    };
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && gesture.current) {
        event.preventDefault();
        cancel();
      }
    };
    window.addEventListener("resize", resize);
    window.addEventListener("blur", cancel);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("blur", cancel);
      window.removeEventListener("keydown", escape);
    };
  }, [floating, landing, place, cancel, x, y, height]);
  useEffect(() => stop, [stop]);
  const down = (event: PointerEvent<HTMLButtonElement>) => {
    if (mobile || event.button !== 0) return;
    const rect = frame.current!.getBoundingClientRect();
    stop();
    setLanding(false);
    gesture.current = {
      id: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: floating ? x.get() : rect.left,
      originY: floating ? y.get() : rect.top,
      floating,
      moved: false,
      lastX: event.clientX,
      lastY: event.clientY,
      time: event.timeStamp,
      vx: 0,
      vy: 0,
    };
    height.set(rect.height);
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: PointerEvent<HTMLButtonElement>) => {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.startX,
      dy = event.clientY - current.startY;
    if (!current.moved && Math.hypot(dx, dy) < 8) return;
    if (!current.moved) {
      controls.current.push(
        animate(
          height,
          Math.min(720, window.innerHeight - 24),
          reduced ? { duration: 0 } : spring,
        ),
      );
    }
    current.moved = true;
    const dt = event.timeStamp - current.time;
    if (dt > 0) {
      current.vx = Math.max(
        -1800,
        Math.min(1800, ((event.clientX - current.lastX) / dt) * 1000),
      );
      current.vy = Math.max(
        -1800,
        Math.min(1800, ((event.clientY - current.lastY) / dt) * 1000),
      );
    }
    current.lastX = event.clientX;
    current.lastY = event.clientY;
    current.time = event.timeStamp;
    setFloating(true);
    setDragging(true);
    place(current.originX + dx, current.originY + dy);
    setDockReady(
      current.originX + dx <=
        (anchor.current?.getBoundingClientRect().left ?? 0) + DOCK_EDGE,
    );
  };
  const up = (event: PointerEvent<HTMLButtonElement>) => {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    const vx = event.timeStamp - current.time < 100 ? current.vx : 0;
    const vy = event.timeStamp - current.time < 100 ? current.vy : 0;
    const left = current.originX + event.clientX - current.startX;
    const edge =
      (anchor.current?.getBoundingClientRect().left ?? 0) + DOCK_EDGE;
    if (current.moved && left <= edge) dock(vx, vy);
    else {
      resetGesture();
      if (current.moved && !reduced) {
        const next = bounds(
          x.get() + Math.max(-24, Math.min(24, vx * 0.025)),
          y.get() + Math.max(-24, Math.min(24, vy * 0.025)),
        );
        controls.current.push(
          animate(x, next.x, {
            ...spring,
            velocity: Math.max(-600, Math.min(600, vx)),
          }),
          animate(y, next.y, {
            ...spring,
            velocity: Math.max(-600, Math.min(600, vy)),
          }),
        );
      }
    }
  };
  const keyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (floating) dock();
      else {
        setFloating(true);
        height.set(Math.min(720, window.innerHeight - 24));
        place(width + 24, 24);
      }
    } else if (
      floating &&
      ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)
    ) {
      event.preventDefault();
      stop();
      setLanding(false);
      const step = event.shiftKey ? 40 : 10;
      place(
        x.get() +
          (event.key === "ArrowRight"
            ? step
            : event.key === "ArrowLeft"
            ? -step
            : 0),
        y.get() +
          (event.key === "ArrowDown"
            ? step
            : event.key === "ArrowUp"
            ? -step
            : 0),
      );
    }
  };
  return (
    <motion.div
      ref={anchor}
      className={styles.anchor}
      initial={false}
      animate={{ width: mobile ? 56 : floating && !landing ? 0 : width }}
      transition={reduced ? { duration: 0 } : spring}
    >
      {mobile && width > 56 && (
        <button
          type="button"
          className={styles.mobileBackdrop}
          onClick={onMobileDismiss}
          aria-label={t("sidebar.closeMobile", "Close navigation")}
        />
      )}
      <motion.div
        aria-hidden="true"
        className={styles.dockTarget}
        initial={false}
        animate={{
          opacity: dockReady || landing ? 1 : 0,
          scale: dockReady || landing ? 1 : 0.97,
        }}
        transition={spring}
        style={{ width: width - 12 }}
      />
      <motion.div
        ref={frame}
        data-sidebar-placement={floating ? "floating" : "docked"}
        data-sidebar-landing={landing || undefined}
        className={`${styles.frame} ${floating ? styles.floating : ""} ${
          dragging ? styles.dragging : ""
        } ${mobile ? styles.mobile : ""} ${
          mobile && width > 56 ? styles.mobileExpanded : ""
        } ${width <= 72 ? styles.rail : ""}`}
        initial={false}
        animate={{
          borderRadius: floating && !landing ? 24 : 0,
          boxShadow:
            floating && !landing
              ? dragging
                ? "0 28px 70px -18px rgba(40,27,15,.28), 0 4px 12px rgba(40,27,15,.08)"
                : "0 18px 50px -16px rgba(40,27,15,.22), 0 2px 8px rgba(40,27,15,.06)"
              : "0 0 0 rgba(40,27,15,0)",
        }}
        transition={reduced ? { duration: 0 } : spring}
        style={{
          width: mobile ? 56 : width,
          height: floating ? height : "100%",
          x: floating ? x : 0,
          y: floating ? y : 0,
        }}
      >
        {!mobile && (
          <div className={styles.transport}>
            <button
              ref={handle}
              type="button"
              className={styles.handle}
              aria-label={t(
                "sidebar.dragHandle",
                "Drag sidebar to float; Enter to toggle docking",
              )}
              title={t(
                "sidebar.dragHandle",
                "Drag sidebar to float; Enter to toggle docking",
              )}
              aria-pressed={floating}
              onPointerDown={down}
              onPointerMove={move}
              onPointerUp={up}
              onPointerCancel={cancel}
              onLostPointerCapture={cancel}
              onKeyDown={keyDown}
            >
              <Menu size={17} />
            </button>
            {floating && (
              <button
                type="button"
                data-press
                className={styles.dockButton}
                onClick={() => dock()}
                title={t("sidebar.dock", "Return sidebar to left edge")}
                aria-label={t("sidebar.dock", "Return sidebar to left edge")}
              >
                <PanelLeft size={17} />
              </button>
            )}
          </div>
        )}
        {children}
      </motion.div>
    </motion.div>
  );
}
