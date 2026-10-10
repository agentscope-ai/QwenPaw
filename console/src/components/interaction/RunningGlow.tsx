import { useEffect, useRef, useState } from "react";
import { useInView, useReducedMotion } from "motion/react";
import { useFxTier } from "@/contexts/FxTierContext";
import styles from "./RunningGlow.module.less";

/** A decorative reflection of a real running state, paused when unseen. */
export function RunningGlow({ active }: { active: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref);
  const reduced = useReducedMotion();
  const { fxTier } = useFxTier();
  const [visible, setVisible] = useState(!document.hidden);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return (
    <span
      ref={ref}
      aria-hidden="true"
      className={styles.glow}
      data-active={active}
      data-animate={active && inView && visible && !reduced && fxTier !== "off"}
    >
      <span className={styles.edge}>
        <span />
      </span>
      <span className={styles.ambient} />
    </span>
  );
}
