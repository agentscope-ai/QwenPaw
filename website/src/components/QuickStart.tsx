import { useState, useCallback, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import { Terminal, Copy, Cloud, Star, TriangleAlert } from "lucide-react";
import { motion } from "motion/react";
import type { SiteConfig } from "../config";
import { t, type Lang } from "../i18n";

const COMMANDS = {
  pip: ["pip install copaw", "copaw init --defaults", "copaw app"],
  unix: [
    "curl -fsSL https://copaw.agentscope.io/install.sh | bash",
    "copaw init --defaults",
    "copaw app",
  ],
  windows: [
    "irm https://copaw.agentscope.io/install.ps1 | iex",
    "copaw init --defaults",
    "copaw app",
  ],
} as const;

const ECS_DEPLOY_URL =
  "https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884";
const ECS_DOC_URL = "https://developer.aliyun.com/article/1713682";

const TABS = ["pip", "unix", "windows", "aliyun"] as const;
type OsTab = (typeof TABS)[number];

interface QuickStartProps {
  config: SiteConfig;
  lang: Lang;
  delay?: number;
}

export function QuickStart({ config, lang, delay = 0 }: QuickStartProps) {
  const [activeTab, setActiveTab] = useState<OsTab>("pip");
  const [copied, setCopied] = useState(false);
  const [hasOverflow, setHasOverflow] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const docsBase = config.docsPath.replace(/\/$/, "") || "/docs";
  const channelsDocPath = `${docsBase}/channels`;

  const isAliyun = activeTab === "aliyun";
  const lines = isAliyun ? [] : COMMANDS[activeTab];
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
        width: "100%",
        minWidth: 0,
        padding: "var(--space-6) var(--space-4) var(--space-8)",
        textAlign: "center",
        overflow: "hidden",
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
          minWidth: 0,
        }}
      >
        <div className="quickstart-card">
          <div className="quickstart-tabs">
            {TABS.map((tab) => {
              const fullTitle =
                tab === "pip"
                  ? t(lang, "quickstart.tabPip")
                  : tab === "unix"
                  ? t(lang, "quickstart.tabUnix")
                  : tab === "windows"
                  ? t(lang, "quickstart.tabWindows")
                  : t(lang, "quickstart.tabAliyun");
              const shortLabel =
                tab === "pip"
                  ? t(lang, "quickstart.tabPipShort")
                  : tab === "unix"
                  ? t(lang, "quickstart.tabUnixShort")
                  : tab === "windows"
                  ? t(lang, "quickstart.tabWindowsShort")
                  : t(lang, "quickstart.tabAliyunShort");
              const BadgeIcon =
                tab === "pip"
                  ? Star
                  : tab === "unix" || tab === "windows"
                  ? TriangleAlert
                  : null;
              return (
                <button
                  key={tab}
                  type="button"
                  className={`quickstart-tab${
                    tab === "aliyun" ? " quickstart-tab--cloud" : ""
                  }`}
                  onClick={() => setActiveTab(tab)}
                  aria-pressed={activeTab === tab}
                  title={fullTitle}
                >
                  <span className="quickstart-tab-label">{shortLabel}</span>
                  {BadgeIcon ? (
                    <BadgeIcon
                      className="quickstart-tab-icon"
                      size={12}
                      strokeWidth={2}
                      aria-hidden
                    />
                  ) : null}
                </button>
              );
            })}
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "var(--space-2)",
              marginBottom: "var(--space-3)",
              minWidth: 0,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-2)",
                minWidth: 0,
                flex: "1 1 0",
                overflow: "hidden",
              }}
            >
              <span style={{ flexShrink: 0 }}>
                {isAliyun ? (
                  <Cloud
                    size={18}
                    strokeWidth={1.5}
                    color="var(--text-muted)"
                  />
                ) : (
                  <Terminal
                    size={18}
                    strokeWidth={1.5}
                    color="var(--text-muted)"
                  />
                )}
              </span>
              <span
                className="quickstart-option-desc"
                title={
                  activeTab === "unix" || activeTab === "windows"
                    ? t(lang, "quickstart.optionLocal")
                    : undefined
                }
                style={{
                  fontSize: "0.8125rem",
                  color: "var(--text-muted)",
                }}
              >
                {isAliyun
                  ? t(lang, "quickstart.optionAliyun")
                  : activeTab === "pip"
                  ? t(lang, "quickstart.optionPip")
                  : t(lang, "quickstart.optionLocal")}
              </span>
            </div>
            {!isAliyun && (
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
                  flexShrink: 0,
                }}
              >
                <Copy size={14} strokeWidth={1.5} aria-hidden />
                <span>
                  {copied ? t(lang, "docs.copied") : t(lang, "docs.copy")}
                </span>
              </button>
            )}
          </div>
          <div style={{ position: "relative", minWidth: 0 }}>
            {isAliyun ? (
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "var(--space-2)",
                  justifyContent: "center",
                }}
              >
                <a
                  href={ECS_DEPLOY_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="quickstart-ecs-btn"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "var(--space-2) var(--space-4)",
                    fontSize: "0.8125rem",
                    fontWeight: 500,
                    color: "var(--text)",
                    background: "var(--border)",
                    border: "1px solid var(--border)",
                    borderRadius: "0.375rem",
                    cursor: "pointer",
                    textDecoration: "none",
                  }}
                >
                  {t(lang, "quickstart.aliyunDeployLink")}
                </a>
                <a
                  href={ECS_DOC_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="quickstart-ecs-btn"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "var(--space-2) var(--space-4)",
                    fontSize: "0.8125rem",
                    fontWeight: 500,
                    color: "var(--text)",
                    background: "var(--border)",
                    border: "1px solid var(--border)",
                    borderRadius: "0.375rem",
                    cursor: "pointer",
                    textDecoration: "none",
                  }}
                >
                  {t(lang, "quickstart.aliyunDocLink")}
                </a>
              </div>
            ) : (
              <>
                <div
                  ref={scrollRef}
                  style={{
                    overflowX: "auto",
                    display: "flex",
                    flexDirection: "column",
                    gap: "var(--space-1)",
                    scrollbarGutter: "stable",
                    minWidth: 0,
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
              </>
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
