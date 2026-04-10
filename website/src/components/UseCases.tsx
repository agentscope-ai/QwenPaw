import {
  Share2,
  Lightbulb,
  CheckSquare,
  BookOpen,
  LayoutDashboard,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { motion } from "motion/react";
import { t, type Lang } from "../i18n";

const CATEGORIES: Array<{
  key:
    | "social"
    | "creative"
    | "productivity"
    | "research"
    | "assistant"
    | "explore";
  icon: LucideIcon;
  items: number;
}> = [
  { key: "social", icon: Share2, items: 3 },
  { key: "creative", icon: Lightbulb, items: 2 },
  { key: "productivity", icon: CheckSquare, items: 3 },
  { key: "research", icon: BookOpen, items: 2 },
  { key: "assistant", icon: LayoutDashboard, items: 1 },
  { key: "explore", icon: Sparkles, items: 1 },
];

interface UseCasesProps {
  lang: Lang;
}

export function UseCases({ lang }: UseCasesProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 40 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-100px" }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      className="usecases-section"
      style={{
        margin: "0 auto",
        width: "90%",
        maxWidth: "1400px",
        padding: "var(--space-8) var(--space-4)",
      }}
    >
      <motion.h2
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.1 }}
        style={{
          margin: "0 0 var(--space-6)",
          fontSize: "2rem",
          fontWeight: 600,
          color: "var(--text)",
          textAlign: "center",
        }}
      >
        {t(lang, "usecases.title")}
      </motion.h2>
      <div className="usecases-grid">
        {CATEGORIES.map(({ key, icon: Icon, items }, index) => (
          <motion.div
            key={key}
            className="usecases-card"
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.5, delay: 0.1 + index * 0.08 }}
            whileHover={{ y: -4, transition: { duration: 0.2 } }}
          >
            <div className="usecases-card-header">
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "2.5rem",
                  height: "2.5rem",
                  background:
                    "linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%)",
                  borderRadius: "0.625rem",
                  flexShrink: 0,
                }}
              >
                <Icon
                  size={20}
                  strokeWidth={1.5}
                  style={{ color: "#667eea" }}
                  aria-hidden
                />
              </div>
              <span className="usecases-card-title">
                {t(lang, `usecases.category.${key}`)}
              </span>
            </div>
            <ul className="usecases-list">
              {Array.from({ length: items }, (_, i) => i + 1).map((i) => (
                <li key={i}>{t(lang, `usecases.${key}.${i}`)}</li>
              ))}
            </ul>
          </motion.div>
        ))}
      </div>
      {t(lang, "usecases.sub") ? (
        <p className="usecases-sub">{t(lang, "usecases.sub")}</p>
      ) : null}
    </motion.section>
  );
}
