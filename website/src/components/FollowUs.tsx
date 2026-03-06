import { motion } from "motion/react";
import { t, type Lang } from "../i18n";

interface FollowUsProps {
  lang: Lang;
  delay?: number;
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

export function FollowUs({ lang, delay = 0 }: FollowUsProps) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay }}
      style={{
        margin: "0 auto",
        maxWidth: "var(--container)",
        padding: "0 var(--space-4) var(--space-6)",
        textAlign: "center",
      }}
    >
      <div
        style={{
          maxWidth: "32rem",
          margin: "0 auto",
          padding: "var(--space-4)",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "0.75rem",
        }}
      >
        <h2
          style={{
            margin: "0 0 var(--space-2)",
            fontSize: "1.125rem",
            fontWeight: 600,
            color: "var(--text)",
          }}
        >
          {t(lang, "follow.title")}
        </h2>
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
      </div>
    </motion.section>
  );
}
