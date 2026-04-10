import type { LucideProps } from "lucide-react";
import { MessageSquare, Lock, Puzzle, Users } from "lucide-react";
import { motion } from "motion/react";
import { t, type Lang } from "../i18n";

const items: Array<{
  key: string;
  icon: React.ComponentType<LucideProps>;
}> = [
  { key: "channels", icon: MessageSquare },
  { key: "private", icon: Lock },
  { key: "multiagent", icon: Users },
  { key: "skills", icon: Puzzle },
];

interface FeaturesProps {
  lang: Lang;
}

export function Features({ lang }: FeaturesProps) {
  return (
    <>
      <style>{`
        .features-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: var(--space-4);
        }
        @media (max-width: 1024px) {
          .features-grid {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 640px) {
          .features-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
      <motion.section
        initial={{ opacity: 0, y: 40 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-100px" }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        style={{
          margin: "0 auto",
          width: "90%",
          maxWidth: "1400px",
          padding: "var(--space-8) var(--space-4)",
          textAlign: "center",
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
          }}
        >
          {t(lang, "features.title")}
        </motion.h2>
        <div className="features-grid">
          {items.map(({ key, icon: Icon }, index) => (
            <motion.div
              key={key}
              initial={{ opacity: 0, y: 30 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: 0.1 + index * 0.1 }}
              whileHover={{ y: -4, transition: { duration: 0.2 } }}
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "0.75rem",
                padding: "var(--space-5)",
                boxShadow: "0 2px 8px rgba(0, 0, 0, 0.04)",
                transition: "box-shadow 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow =
                  "0 8px 24px rgba(0, 0, 0, 0.1)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow =
                  "0 2px 8px rgba(0, 0, 0, 0.04)";
              }}
            >
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "3rem",
                  height: "3rem",
                  marginBottom: "var(--space-3)",
                  background:
                    "linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%)",
                  borderRadius: "0.75rem",
                  color: "#667eea",
                }}
              >
                <Icon size={24} strokeWidth={1.5} aria-hidden />
              </div>
              <h3
                style={{
                  margin: "0 0 var(--space-2)",
                  fontSize: "1.0625rem",
                  fontWeight: 600,
                  color: "var(--text)",
                }}
              >
                {t(lang, `features.${key}.title`)}
              </h3>
              <p
                style={{
                  margin: 0,
                  fontSize: "0.9375rem",
                  lineHeight: 1.6,
                  color: "var(--text-muted)",
                }}
              >
                {t(lang, `features.${key}.desc`)}
              </p>
            </motion.div>
          ))}
        </div>
      </motion.section>
    </>
  );
}
