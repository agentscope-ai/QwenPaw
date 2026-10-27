import { motion, useReducedMotion } from "motion/react";
import styles from "./index.module.less";

export default function AmbientLight() {
  const reduced = useReducedMotion();
  return (
    <motion.div
      aria-hidden="true"
      className={styles.ambientLight}
      initial={false}
      animate={{ opacity: reduced ? 0.55 : [0.45, 0.75, 0.45] }}
      transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
    />
  );
}
