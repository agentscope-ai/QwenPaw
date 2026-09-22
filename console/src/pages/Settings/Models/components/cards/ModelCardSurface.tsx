import { useRef, type PointerEvent, type ReactNode } from "react";
import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
  type HTMLMotionProps,
  type MotionStyle,
} from "motion/react";
import styles from "./ModelCardSurface.module.less";

const spring = { stiffness: 240, damping: 23, mass: 0.8 };
const editingControls =
  'input, textarea, select, [contenteditable="true"], [role="slider"]';

type ModelCardSurfaceProps = Omit<HTMLMotionProps<"div">, "children"> & {
  children: ReactNode;
  tilt?: number;
  as?: "div" | "section";
  frameClassName?: string;
};

export function ModelCardSurface({
  children,
  tilt = 7,
  as = "div",
  className = "",
  frameClassName = "",
  ...props
}: ModelCardSurfaceProps) {
  const reducedMotion = useReducedMotion();
  const pointer = useRef<number | null>(null);
  const editing = useRef(false);
  const controlPointer = useRef<number | null>(null);
  const rotateX = useSpring(0, spring);
  const rotateY = useSpring(0, spring);
  const reflection = useSpring(0, { stiffness: 300, damping: 30 });
  const lightX = useMotionValue(50);
  const lightY = useMotionValue(50);
  const xPercent = useMotionTemplate`${lightX}%`;
  const yPercent = useMotionTemplate`${lightY}%`;

  const reset = () => {
    pointer.current = null;
    controlPointer.current = null;
    rotateX.set(0);
    rotateY.set(0);
    reflection.set(0);
  };

  const follow = (event: PointerEvent<HTMLElement>) => {
    if (
      reducedMotion ||
      editing.current ||
      controlPointer.current !== null ||
      !event.isPrimary ||
      !event.currentTarget.contains(event.target as Node) ||
      (pointer.current !== null && pointer.current !== event.pointerId) ||
      (event.pointerType !== "mouse" && pointer.current === null)
    )
      return;
    // Tilted cards use a stationary frame to avoid coordinate feedback.
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / bounds.width),
    );
    const y = Math.max(
      0,
      Math.min(1, (event.clientY - bounds.top) / bounds.height),
    );
    rotateX.set((0.5 - y) * tilt * 2);
    rotateY.set((x - 0.5) * tilt * 2);
    lightX.set(x * 100);
    lightY.set(y * 100);
    reflection.set(1);
  };

  const handlers = {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      if (
        !event.isPrimary ||
        event.button !== 0 ||
        !event.currentTarget.contains(event.target as Node)
      )
        return;
      if (!tilt && (event.target as Element).closest(editingControls)) {
        reset();
        controlPointer.current = event.pointerId;
        return;
      }
      pointer.current = event.pointerId;
      follow(event);
    },
    onPointerMove: follow,
    onPointerUp: reset,
    onPointerLeave: reset,
    onPointerCancel: reset,
    onLostPointerCapture: reset,
  };
  const Surface = motion[as];
  const surface = (
    <Surface
      {...props}
      {...(!tilt ? handlers : {})}
      className={`${className} ${styles.surface}`}
      onFocusCapture={(event) => {
        if (!tilt && (event.target as Element).closest(editingControls)) {
          editing.current = true;
          reset();
        }
      }}
      onBlurCapture={(event) => {
        editing.current =
          !tilt &&
          event.relatedTarget instanceof Element &&
          event.currentTarget.contains(event.relatedTarget) &&
          !!event.relatedTarget.closest(editingControls);
      }}
      style={
        reducedMotion || !tilt
          ? undefined
          : { rotateX, rotateY, transformPerspective: 900 }
      }
    >
      {children}
      {!reducedMotion && (
        <motion.span
          aria-hidden="true"
          className={styles.reflection}
          style={
            {
              "--reflection-x": xPercent,
              "--reflection-y": yPercent,
              opacity: reflection,
            } as MotionStyle
          }
        />
      )}
    </Surface>
  );
  return tilt ? (
    <div className={`${styles.frame} ${frameClassName}`} {...handlers}>
      {surface}
    </div>
  ) : (
    surface
  );
}
