import { useEffect, useRef } from "react";
import { Bell } from "lucide-react";
import {
  AnimatePresence,
  motion,
  useAnimationControls,
  useReducedMotion,
} from "motion/react";
import NumberFlow from "@number-flow/react";
import styles from "./NotificationBell.module.less";

/** Decorative icon inside the existing accessible inbox navigation button. */
export function NotificationBell({
  count,
  attention = false,
  animate = true,
  ring = false,
}: {
  count: number;
  attention?: boolean;
  animate?: boolean;
  ring?: boolean;
}) {
  const reduced = useReducedMotion();
  const controls = useAnimationControls();
  const previous = useRef(count);
  const previousAttention = useRef(attention);
  const previousRing = useRef(false);
  useEffect(() => {
    if (
      (count > previous.current ||
        (attention && !previousAttention.current) ||
        (ring && !previousRing.current)) &&
      animate &&
      !reduced
    ) {
      void controls.start({
        rotate: [0, -18, 14, -8, 4, 0],
        transition: { duration: 0.55 },
      });
    }
    previous.current = count;
    previousAttention.current = attention;
    previousRing.current = ring;
  }, [count, attention, ring, animate, reduced, controls]);
  return (
    <span className={styles.root} aria-hidden="true">
      <motion.span className={styles.bell} animate={controls}>
        <Bell size={19} />
      </motion.span>
      <AnimatePresence>
        {(count > 0 || attention) && (
          <motion.span
            className={`${styles.badge} ${count ? "" : styles.dot}`}
            initial={{ scale: reduced ? 1 : 0 }}
            animate={{ scale: 1 }}
            exit={{ scale: reduced ? 1 : 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 420, damping: 28 }}
          >
            {count > 0 && (
              <NumberFlow
                value={Math.min(count, 99)}
                suffix={count > 99 ? "+" : undefined}
                animated={!reduced}
              />
            )}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}
