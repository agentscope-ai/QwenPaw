import { motion } from "motion/react";
import { t, type Lang } from "../i18n";

interface FollowUsProps {
  lang: Lang;
}

const links = [
  {
    key: "xiaohongshu",
    icon: "🍠",
    href: "https://xhslink.com/m/4dw1MpY7Xta",
    label: "AgentScope",
  },
  {
    key: "x",
    icon: "𝕏",
    href: "https://x.com/agentscope_ai",
    label: "@agentscope_ai",
  },
] as const;

export function FollowUs({ lang }: FollowUsProps) {
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
      <motion.h2
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.1 }}
        style={{
          margin: "0 0 var(--space-3)",
          fontSize: "2rem",
          fontWeight: 600,
          color: "var(--text)",
        }}
      >
        {t(lang, "follow.title")}
      </motion.h2>
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.2 }}
        style={{
          maxWidth: "32rem",
          margin: "0 auto",
          padding: "var(--space-5)",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "0.75rem",
          boxShadow: "0 4px 16px rgba(0, 0, 0, 0.06)",
        }}
      >
        <p
          style={{
            margin: "0 0 var(--space-3)",
            fontSize: "0.9375rem",
            color: "var(--text-muted)",
            lineHeight: 1.6,
          }}
        >
          {t(lang, "follow.sub")}
        </p>
        <div
          style={{
            display: "grid",
            gap: "var(--space-2)",
            justifyItems: "center",
          }}
        >
          {links.map((item) => (
            <div
              key={item.key}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "0.25rem",
                color: "var(--text)",
                fontSize: "0.9375rem",
              }}
            >
              <span aria-hidden>{item.icon}</span>
              {item.key === "x" ? (
                <span>：</span>
              ) : (
                <span>{t(lang, `follow.${item.key}`)}</span>
              )}
              <a
                href={item.href}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  textDecoration: "underline",
                  textUnderlineOffset: "0.15em",
                }}
              >
                {item.label}
              </a>
            </div>
          ))}
        </div>
      </motion.div>
    </motion.section>
  );
}
