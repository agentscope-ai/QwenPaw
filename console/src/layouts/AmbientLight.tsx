import { motion, useReducedMotion } from "motion/react";
import { useFxTier } from "../contexts/FxTierContext";
import styles from "./index.module.less";

export default function AmbientLight() {
  const reduced = useReducedMotion();
  const { fxTier } = useFxTier();
  // Off tier (and OS reduced motion) freezes the 8s opacity breathing at a
  // static value instead of animating it.
  const frozen = (reduced ?? false) || fxTier === "off";
  return (
    <motion.div
      aria-hidden="true"
      className={styles.ambientLight}
      initial={false}
      animate={{ opacity: frozen ? 0.55 : [0.45, 0.75, 0.45] }}
      transition={
        frozen
          ? { duration: 0 }
          : { duration: 8, repeat: Infinity, ease: "easeInOut" }
      }
    />
  );
}
