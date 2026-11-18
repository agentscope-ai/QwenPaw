import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

/** Animate on mount; callers can suppress entrance during filtering. */
export function Cascade({
  children,
  className,
  index = 0,
  animate = true,
}: {
  children: ReactNode;
  className?: string;
  index?: number;
  animate?: boolean;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduced || !animate ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        type: "spring",
        stiffness: 380,
        damping: 36,
        delay: Math.min(index * 0.03, 0.18),
      }}
    >
      {children}
    </motion.div>
  );
}
