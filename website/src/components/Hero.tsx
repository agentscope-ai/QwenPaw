import { Link } from "react-router-dom";
import { ArrowRight, ChevronDown } from "lucide-react";
import { motion } from "motion/react";
import { CopawMascot } from "./CopawMascot";
import { t, type Lang } from "../i18n";

interface HeroProps {
  projectName: string;
  tagline: string;
  lang: Lang;
  docsPath: string;
}

const container = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.1, delayChildren: 0.05 },
  },
};

const item = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0 },
};

export function Hero({
  projectName,
  tagline: _tagline,
  lang,
  docsPath,
}: HeroProps) {
  return (
    <motion.section
      className="hero-section"
      style={{
        margin: "0 auto",
        maxWidth: "var(--container)",
        padding: "var(--space-8) var(--space-4) var(--space-7)",
        textAlign: "center",
      }}
      variants={container}
      initial="hidden"
      animate="visible"
    >
      <motion.div
        variants={item}
        className="hero-brand-row"
        style={{
          marginBottom: "var(--space-4)",
          display: "grid",
          gridTemplateColumns: "1fr auto 1fr",
          alignItems: "center",
          width: "100%",
        }}
      >
        <span />
        <div
          className="hero-brand-main"
          style={{
            display: "flex",
            flexWrap: "nowrap",
            alignItems: "center",
          }}
          aria-label={projectName}
        >
          <img
            src="/copaw_ip.svg"
            alt={`${projectName} IP`}
            className="hero-brand-ip"
          />
          <span className="hero-brand-logo">
            <CopawMascot size={200} />
          </span>
        </div>
        <span />
      </motion.div>
      <motion.p
        variants={item}
        style={{
          margin: "var(--space-3) 0 var(--space-2)",
          fontSize: "clamp(1.125rem, 2.5vw, 1.375rem)",
          color: "var(--text)",
          maxWidth: "32rem",
          marginLeft: "auto",
          marginRight: "auto",
          lineHeight: 1.5,
          fontWeight: 600,
        }}
      >
        {t(lang, "hero.slogan")}
      </motion.p>
      <motion.p
        variants={item}
        style={{
          margin: "0 auto var(--space-4)",
          maxWidth: "28rem",
          fontSize: "0.9375rem",
          color: "var(--text-muted)",
          lineHeight: 1.6,
        }}
      >
        {t(lang, "hero.sub")}
      </motion.p>
      <motion.div variants={item} style={{ marginBottom: "var(--space-5)" }}>
        <Link
          to={docsPath.replace(/\/$/, "") || "/docs"}
          className="hero-cta-button"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "var(--space-2)",
            padding: "var(--space-3) var(--space-5)",
            background: "linear-gradient(135deg, #1d1d1f 0%, #2d2d2f 100%)",
            color: "var(--surface)",
            borderRadius: "0.75rem",
            fontSize: "1.0625rem",
            fontWeight: 600,
            textDecoration: "none",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.15)",
            transition: "all 0.2s ease",
            position: "relative",
            overflow: "hidden",
          }}
        >
          <span style={{ position: "relative", zIndex: 1 }}>
            {t(lang, "hero.cta")}
          </span>
          <ArrowRight
            size={20}
            strokeWidth={2}
            aria-hidden
            style={{ position: "relative", zIndex: 1 }}
          />
        </Link>
      </motion.div>
      <style>{`
        .hero-cta-button::before {
          content: '';
          position: absolute;
          top: 0;
          left: -100%;
          width: 100%;
          height: 100%;
          background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
          transition: left 0.5s ease;
        }

        .hero-cta-button:hover {
          transform: translateY(-2px) scale(1.02);
          box-shadow: 0 8px 20px rgba(0, 0, 0, 0.25);
        }

        .hero-cta-button:hover::before {
          left: 100%;
        }
      `}</style>
      <motion.div
        variants={item}
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "var(--space-2)",
          marginTop: "var(--space-6)",
        }}
      >
        <motion.div
          animate={{
            y: [0, 8, 0],
          }}
          transition={{
            duration: 1.5,
            repeat: Infinity,
            ease: "easeInOut",
          }}
          style={{
            color: "var(--text-muted)",
            opacity: 0.6,
          }}
        >
          <ChevronDown size={28} strokeWidth={2} aria-hidden />
        </motion.div>
        <p
          style={{
            fontSize: "0.875rem",
            color: "var(--text-muted)",
            margin: 0,
            fontWeight: 500,
          }}
        >
          {lang === "zh"
            ? "向下滚动查看快速开始"
            : "Scroll down for quick start"}
        </p>
      </motion.div>
    </motion.section>
  );
}
