import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
  type ReactNode,
} from "react";
import { Modal, type ModalProps } from "antd";
import { motion, useReducedMotion } from "motion/react";
import { usagePanelPosition } from "./sidebarPlacement";
import { useOverlayContainer } from "../os/osWindowContainer";

/** Position from live geometry; never scale chart/text across the workspace. */
function Surface({
  origin,
  open,
  onExit,
  onMeasure,
  children,
  ready,
  anchor,
}: {
  origin: RefObject<HTMLElement>;
  open: boolean;
  onExit: () => void;
  onMeasure: (source: DOMRect, size: DOMRect) => void;
  children: ReactNode;
  ready: boolean;
  anchor: { x: number; y: number; side: number; fold: string };
}) {
  const surface = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  useLayoutEffect(() => {
    const element = surface.current;
    if (!element) return;
    const measure = () => {
      const source = origin.current?.getBoundingClientRect();
      const dialog = element.closest('[role="dialog"]') ?? element;
      const size = dialog.getBoundingClientRect();
      if (source && size.width && size.height) onMeasure(source, size);
    };
    if (open) measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [open, origin, onMeasure]);
  const hidden = {
    opacity: 0,
    scale: reduced ? 1 : 0.985,
    clipPath: reduced ? "inset(0% 0% 0% 0% round 24px)" : anchor.fold,
    x: reduced ? 0 : anchor.side * 14,
    y: reduced ? 0 : 4,
  };
  return (
    <motion.div
      ref={surface}
      initial={hidden}
      animate={
        open && ready
          ? {
              opacity: 1,
              scale: 1,
              x: 0,
              y: 0,
              clipPath: "inset(0% 0% 0% 0% round 24px)",
            }
          : hidden
      }
      transition={{
        type: "spring",
        duration: reduced ? 0 : open ? 0.34 : 0.24,
        bounce: 0,
        opacity: { duration: reduced ? 0 : open ? 0.16 : 0.14 },
      }}
      style={{ transformOrigin: `${anchor.x}px ${anchor.y}px` }}
      onAnimationComplete={() => {
        if (!open) onExit();
      }}
    >
      {children}
    </motion.div>
  );
}

export default function SidebarUsageDialog({
  origin,
  open,
  ...props
}: ModalProps & { origin: RefObject<HTMLElement> }) {
  const container = useOverlayContainer();
  const [visible, setVisible] = useState(!!open);
  const [position, setPosition] = useState({ left: 12, top: 12 });
  const [anchor, setAnchor] = useState({
    x: 0,
    y: 0,
    side: -1,
    fold: "inset(90% 55% 0% 0% round 22px)",
  });
  const [positionReady, setPositionReady] = useState(false);
  useEffect(() => {
    if (open) setVisible(true);
  }, [open]);
  const onExit = useCallback(() => setVisible(false), []);
  const onMeasure = useCallback(
    (source: DOMRect, size: DOMRect) => {
      const box = container?.getBoundingClientRect();
      const offset = { left: box?.left ?? 0, top: box?.top ?? 0 };
      setPositionReady(true);
      const next = usagePanelPosition(
        {
          left: source.left - offset.left,
          right: source.right - offset.left,
          bottom: source.bottom - offset.top,
        },
        size,
        {
          width: box?.width ?? window.innerWidth,
          height: box?.height ?? window.innerHeight,
        },
      );
      setPosition(next);
      const sourceX = (source.left + source.right) / 2 - offset.left;
      const fromLeft = sourceX < next.left + size.width / 2;
      const fromBottom =
        source.bottom - offset.top > next.top + size.height / 2;
      const horizontal = Math.max(0, 100 - (source.width / size.width) * 100);
      const vertical = Math.max(0, 100 - (source.height / size.height) * 100);
      setAnchor({
        x: Math.max(0, Math.min(size.width, sourceX - next.left)),
        y: Math.max(
          0,
          Math.min(size.height, source.bottom - offset.top - next.top),
        ),
        side: fromLeft ? -1 : 1,
        fold: `inset(${fromBottom ? vertical : 0}% ${
          fromLeft ? horizontal : 0
        }% ${fromBottom ? 0 : vertical}% ${
          fromLeft ? 0 : horizontal
        }% round 22px)`,
      });
    },
    [container],
  );
  return (
    <Modal
      {...props}
      getContainer={container}
      open={!!open || visible}
      centered={false}
      style={{
        position: "absolute",
        margin: 0,
        ...position,
        visibility: positionReady ? "visible" : "hidden",
      }}
      afterClose={() => {
        setPositionReady(false);
        props.afterClose?.();
      }}
      styles={{
        body: {
          height: "min(450px, calc(100dvh - 140px))",
          overflow: "hidden",
        },
        mask: { background: "rgb(0 0 0 / 12%)" },
      }}
      transitionName=""
      maskTransitionName=""
      modalRender={(node) => (
        <Surface
          origin={origin}
          ready={positionReady}
          anchor={anchor}
          open={!!open}
          onExit={onExit}
          onMeasure={onMeasure}
        >
          {node}
        </Surface>
      )}
    />
  );
}
