/**
 * Brand story: Why CoPaw? Name explanation in a quiet, emotional corner.
 */
import { motion } from "motion/react";
import { t, type Lang } from "../i18n";

interface BrandStoryProps {
  lang: Lang;
}

export function BrandStory({ lang }: BrandStoryProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 40 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-100px" }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      style={{
        margin: "0 auto",
        maxWidth: "var(--container)",
        padding: "var(--space-8) var(--space-4)",
        textAlign: "center",
      }}
    >
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.1 }}
        style={{
          maxWidth: "32rem",
          margin: "0 auto",
          padding: "var(--space-5)",
          borderTop: "1px solid var(--border)",
        }}
      >
        <h2
          style={{
            margin: "0 0 var(--space-4)",
            fontSize: "1.125rem",
            fontWeight: 600,
            color: "var(--text-muted)",
            letterSpacing: "0.02em",
          }}
        >
          {t(lang, "brandstory.title")}
        </h2>
        <p
          style={{
            margin: "0 0 var(--space-2)",
            fontSize: "0.9375rem",
            color: "var(--text)",
            lineHeight: 1.7,
          }}
        >
          {t(lang, "brandstory.para1")}
        </p>
        <p
          style={{
            margin: 0,
            fontSize: "0.9375rem",
            color: "var(--text-muted)",
            lineHeight: 1.7,
          }}
        >
          {t(lang, "brandstory.para2")}
        </p>
      </motion.div>
    </motion.section>
  );
}
