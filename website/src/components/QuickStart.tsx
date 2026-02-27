import { useState, useCallback, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Terminal, Copy } from "lucide-react";
import { motion } from "motion/react";
import type { SiteConfig } from "../config";
import { t, type Lang } from "../i18n";

const COMMANDS = {
  unix: [
    "curl -fsSL https://raw.githubusercontent.com/agentscope-ai/CoPaw/master/scripts/install.sh | bash",
    "copaw init --defaults",
    "copaw app",
  ],
  windows: [
    "irm https://raw.githubusercontent.com/agentscope-ai/CoPaw/master/scripts/install.ps1 | iex",
    "copaw init --defaults",
    "copaw app",
  ],
} as const;

type OsTab = keyof typeof COMMANDS;

interface QuickStartProps {
  config: SiteConfig;
  lang: Lang;
  delay?: number;
}

export function QuickStart({ config, lang, delay = 0 }: QuickStartProps) {
  const [activeTab, setActiveTab] = useState<OsTab>("unix");
  const [copied, setCopied] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const docsBase = config.docsPath.replace(/\/$/, "") || "/docs";
  const channelsDocPath = `${docsBase}/channels`;

  const lines = COMMANDS[activeTab];
  const fullCommand = lines.join("\n");

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollLeft = 0;
    const check = () => setHasOverflow(el.scrollWidth > el.clientWidth);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [activeTab]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(fullCommand);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [fullCommand]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      style={{
        margin: "0 auto",
        maxWidth: "var(--container)",
        padding: "var(--space-6) var(--space-4) var(--space-8)",
        textAlign: "center",
      }}
    >
      <h2
        style={{
          margin: "0 0 var(--space-4)",
          fontSize: "1.375rem",
          fontWeight: 600,
          color: "var(--text)",
        }}
      >
        {t(lang, "quickstart.title")}
      </h2>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-4)",
          maxWidth: "28rem",
          margin: "0 auto",
        }}
      >
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: "0.5rem",
            padding: "var(--space-4)",
          }}
        >
          <div
            style={{
              display: "flex",
              gap: "var(--space-1)",
              marginBottom: "var(--space-3)",
            }}
          >
            {(["unix", "windows"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                aria-pressed={activeTab === tab}
                style={{
                  padding: "var(--space-1) var(--space-3)",
                  fontSize: "0.75rem",
                  fontWeight: activeTab === tab ? 600 : 400,
                  color:
                    activeTab === tab ? "var(--text)" : "var(--text-muted)",
                  background:
                    activeTab === tab ? "var(--border)" : "transparent",
                  border: "1px solid var(--border)",
                  borderRadius: "9999px",
                  cursor: "pointer",
                }}
              >
                {tab === "unix"
                  ? t(lang, "quickstart.tabUnix")
                  : t(lang, "quickstart.tabWindows")}
              </button>
            ))}
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "var(--space-2)",
              marginBottom: "var(--space-3)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-2)",
              }}
            >
              <Terminal size={18} strokeWidth={1.5} color="var(--text-muted)" />
              <span
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--text-muted)",
                }}
              >
                {t(lang, "quickstart.optionLocal")}
              </span>
            </div>
            <button
              type="button"
              onClick={handleCopy}
              aria-label={t(lang, "docs.copy")}
              title={t(lang, "docs.copy")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "var(--space-1)",
                padding: "var(--space-1) var(--space-2)",
                fontSize: "0.75rem",
                color: "var(--text-muted)",
                background: "transparent",
                border: "1px solid var(--border)",
                borderRadius: "0.375rem",
                cursor: "pointer",
              }}
            >
              <Copy size={14} strokeWidth={1.5} aria-hidden />
              <span>
                {copied ? t(lang, "docs.copied") : t(lang, "docs.copy")}
              </span>
            </button>
          </div>
          <div style={{ position: "relative" }}>
            <div
              ref={scrollRef}
              style={{
                overflowX: "auto",
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-1)",
                scrollbarGutter: "stable",
              }}
            >
              {lines.map((line) => (
                <div
                  key={line}
                  style={{
                    fontFamily: "ui-monospace, monospace",
                    fontSize: "0.8125rem",
                    color: "var(--text)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {line}
                </div>
              ))}
            </div>
            {hasOverflow && (
              <div
                aria-hidden
                style={{
                  position: "absolute",
                  top: 0,
                  right: 0,
                  bottom: 0,
                  width: "3rem",
                  background:
                    "linear-gradient(to left, var(--surface) 0%, transparent)",
                  pointerEvents: "none",
                }}
              />
            )}
          </div>
          <p
            style={{
              margin: "var(--space-3) 0 0",
              fontSize: "0.8125rem",
              color: "var(--text-muted)",
              lineHeight: 1.5,
            }}
          >
            {t(lang, "quickstart.hintBefore")}
            <Link
              to={channelsDocPath}
              style={{
                color: "inherit",
                textDecoration: "underline",
              }}
            >
              {t(lang, "quickstart.hintLink")}
            </Link>
            {t(lang, "quickstart.hintAfter")}
          </p>
        </div>
      </div>
    </motion.section>
  );
}
