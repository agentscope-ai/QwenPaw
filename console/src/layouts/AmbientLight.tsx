import styles from "./index.module.less";

/**
 * Decorative background glow. The 8 s opacity breathing animation forced the
 * compositor to blend a full-screen layer every frame (~25% GPU/CPU even with
 * will-change); a static glow costs one paint and nothing afterwards.
 */
export default function AmbientLight() {
  return <div aria-hidden="true" className={styles.ambientLight} />;
}
