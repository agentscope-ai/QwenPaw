import { useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Terminal,
  Copy,
  Check,
  Download,
  Cloud,
  Container,
  Package,
  Monitor,
  ExternalLink,
  Sparkles,
} from "lucide-react";
import { motion } from "motion/react";
import type { SiteConfig } from "../config";
import { t, type Lang } from "../i18n";

const DOCKER_IMAGE = "agentscope/copaw:latest";
const MODELSCOPE_URL =
  "https://modelscope.cn/studios/fork?target=AgentScope/CoPaw";
const ALIYUN_ECS_URL =
  "https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884";
const ALIYUN_DOC_URL = "https://developer.aliyun.com/article/1713682";
const DESKTOP_RELEASES_URL = "https://github.com/agentscope-ai/CoPaw/releases";

const COMMANDS = {
  pip: ["pip install copaw", "copaw init --defaults", "copaw app"],
  scriptMac: [
    "curl -fsSL https://copaw.agentscope.io/install.sh | bash",
    "copaw init --defaults",
    "copaw app",
  ],
  scriptWinCmd: [
    "curl -fsSL https://copaw.agentscope.io/install.bat -o install.bat && install.bat",
    "copaw init --defaults",
    "copaw app",
  ],
  scriptWinPs: [
    "irm https://copaw.agentscope.io/install.ps1 | iex",
    "copaw init --defaults",
    "copaw app",
  ],
  docker: [
    `docker pull ${DOCKER_IMAGE}`,
    `docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working ${DOCKER_IMAGE}`,
  ],
} as const;

interface QuickStartProps {
  config: SiteConfig;
  lang: Lang;
}

type InstallMethod = "pip" | "script" | "docker" | "cloud" | "desktop";
type ScriptPlatform = "mac" | "windows";
type ScriptWindowsVariant = "cmd" | "ps";
type CloudVariant = "aliyun" | "modelscope";

interface CodeBlockProps {
  lines: readonly string[];
  copied: boolean;
  onCopy: () => void;
  lang: Lang;
}

function CodeBlock({ lines, copied, onCopy, lang }: CodeBlockProps) {
  return (
    <div
      style={{
        position: "relative",
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: "0.5rem",
        padding: "var(--space-3)",
        overflow: "auto",
      }}
    >
      <button
        type="button"
        onClick={onCopy}
        aria-label={t(lang, "docs.copy")}
        style={{
          position: "absolute",
          top: "var(--space-2)",
          right: "var(--space-2)",
          display: "inline-flex",
          alignItems: "center",
          gap: "var(--space-1)",
          padding: "var(--space-1) var(--space-2)",
          fontSize: "0.75rem",
          color: copied ? "var(--text)" : "var(--text-muted)",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "0.375rem",
          cursor: "pointer",
          transition: "all 0.15s ease",
        }}
      >
        {copied ? (
          <>
            <Check size={12} strokeWidth={2} aria-hidden />
            <span>{t(lang, "docs.copied")}</span>
          </>
        ) : (
          <>
            <Copy size={12} strokeWidth={2} aria-hidden />
            <span>{t(lang, "docs.copy")}</span>
          </>
        )}
      </button>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-1)",
          fontFamily: "ui-monospace, monospace",
          fontSize: "0.8125rem",
          color: "var(--text)",
        }}
      >
        {lines.map((line, idx) => (
          <div
            key={idx}
            style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }}
          >
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}

export function QuickStart({ config, lang }: QuickStartProps) {
  const [selectedMethod, setSelectedMethod] = useState<InstallMethod>("pip");
  const [scriptPlatform, setScriptPlatform] = useState<ScriptPlatform>("mac");
  const [scriptWinVariant, setScriptWinVariant] =
    useState<ScriptWindowsVariant>("cmd");
  const [cloudVariant, setCloudVariant] = useState<CloudVariant>("aliyun");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const docsBase = config.docsPath.replace(/\/$/, "") || "/docs";
  const channelsDocPath = `${docsBase}/channels`;

  const handleCopy = useCallback(async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch {
      setCopiedId(null);
    }
  }, []);

  const methodConfig: Record<
    InstallMethod,
    { icon: typeof Package; label: string; desc: string; badge?: string }
  > = {
    pip: {
      icon: Package,
      label: t(lang, "quickstart.method.pip"),
      desc: t(lang, "quickstart.desc.pip"),
    },
    script: {
      icon: Terminal,
      label: t(lang, "quickstart.method.script"),
      desc: t(lang, "quickstart.desc.script"),
    },
    docker: {
      icon: Container,
      label: t(lang, "quickstart.method.docker"),
      desc: t(lang, "quickstart.desc.docker"),
    },
    cloud: {
      icon: Cloud,
      label: t(lang, "quickstart.method.cloud"),
      desc: t(lang, "quickstart.desc.cloud"),
    },
    desktop: {
      icon: Monitor,
      label: t(lang, "quickstart.method.desktop"),
      desc: t(lang, "quickstart.desc.desktop"),
      badge: t(lang, "quickstart.badgeBeta"),
    },
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 40 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-100px" }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      style={{
        margin: "0 auto",
        maxWidth: "var(--container)",
        width: "100%",
        padding: "var(--space-8) var(--space-4)",
      }}
    >
      <div style={{ textAlign: "center", marginBottom: "var(--space-6)" }}>
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
          {t(lang, "quickstart.title")}
        </motion.h2>
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.2 }}
          style={{
            position: "relative",
            display: "inline-block",
            padding: "var(--space-4) var(--space-5)",
            marginBottom: "var(--space-4)",
            background:
              "linear-gradient(135deg, rgba(102, 126, 234, 0.08) 0%, rgba(118, 75, 162, 0.08) 100%)",
            border: "2px solid transparent",
            backgroundImage:
              "linear-gradient(white, white), linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            backgroundOrigin: "border-box",
            backgroundClip: "padding-box, border-box",
            borderRadius: "0.75rem",
            maxWidth: "48rem",
            boxShadow:
              "0 4px 16px rgba(102, 126, 234, 0.15), 0 0 0 1px rgba(102, 126, 234, 0.1)",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "center",
              gap: "var(--space-2)",
            }}
          >
            <Sparkles
              size={18}
              strokeWidth={2}
              style={{
                color: "#667eea",
                flexShrink: 0,
                marginTop: "0.125rem",
              }}
              aria-hidden
            />
            <p
              style={{
                margin: 0,
                fontSize: "1.0625rem",
                fontWeight: 600,
                background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
                lineHeight: 1.4,
                textAlign: "left",
              }}
            >
              {t(lang, "quickstart.serviceNotice")}
            </p>
          </div>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.6, delay: 0.3 }}
        style={{
          maxWidth: "52rem",
          margin: "0 auto",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "0.75rem",
          overflow: "hidden",
          boxShadow:
            "0 4px 16px rgba(0, 0, 0, 0.06), 0 0 0 1px rgba(0, 0, 0, 0.02)",
        }}
      >
        {/* 顶部方法选择 tabs */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))",
            borderBottom: "1px solid var(--border)",
            background: "var(--bg)",
          }}
        >
          {(Object.keys(methodConfig) as InstallMethod[]).map((method) => {
            const { icon: Icon, label, badge } = methodConfig[method];
            const isActive = selectedMethod === method;
            return (
              <button
                key={method}
                type="button"
                onClick={() => setSelectedMethod(method)}
                aria-pressed={isActive}
                className={`quickstart-main-tab ${isActive ? "active" : ""}`}
              >
                <Icon size={16} strokeWidth={1.5} />
                <span>{label}</span>
                {badge && (
                  <span
                    style={{
                      position: "absolute",
                      top: "0.25rem",
                      right: "0.25rem",
                      padding: "0.125rem 0.3rem",
                      background: "var(--border)",
                      borderRadius: "0.25rem",
                      fontSize: "0.5625rem",
                      fontWeight: 600,
                      color: "var(--text-muted)",
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                    }}
                  >
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* 内容区域 */}
        <div style={{ padding: "var(--space-5)" }}>
          {/* 描述 */}
          <p
            style={{
              margin: "0 0 var(--space-4)",
              fontSize: "0.875rem",
              color: "var(--text-muted)",
              lineHeight: 1.5,
            }}
          >
            {methodConfig[selectedMethod].desc}
          </p>

          {/* pip 内容 */}
          {selectedMethod === "pip" && (
            <CodeBlock
              lines={COMMANDS.pip}
              copied={copiedId === "pip"}
              onCopy={() => handleCopy(COMMANDS.pip.join("\n"), "pip")}
              lang={lang}
            />
          )}

          {/* 脚本安装内容 */}
          {selectedMethod === "script" && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-3)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  gap: "var(--space-2)",
                  padding: "var(--space-1)",
                  background: "var(--bg)",
                  borderRadius: "0.5rem",
                }}
              >
                {(["mac", "windows"] as const).map((platform) => (
                  <button
                    key={platform}
                    type="button"
                    onClick={() => setScriptPlatform(platform)}
                    aria-pressed={scriptPlatform === platform}
                    className={`quickstart-tab ${
                      scriptPlatform === platform ? "active" : ""
                    }`}
                  >
                    {t(lang, `quickstart.platform.${platform}`)}
                  </button>
                ))}
              </div>

              {scriptPlatform === "windows" && (
                <div
                  style={{
                    display: "flex",
                    gap: "var(--space-2)",
                    padding: "var(--space-1)",
                    background: "var(--bg)",
                    borderRadius: "0.5rem",
                  }}
                >
                  {(["cmd", "ps"] as const).map((variant) => (
                    <button
                      key={variant}
                      type="button"
                      onClick={() => setScriptWinVariant(variant)}
                      aria-pressed={scriptWinVariant === variant}
                      className={`quickstart-tab quickstart-tab-small ${
                        scriptWinVariant === variant ? "active" : ""
                      }`}
                    >
                      {t(lang, `quickstart.shell.${variant}`)}
                    </button>
                  ))}
                </div>
              )}

              <CodeBlock
                lines={
                  scriptPlatform === "mac"
                    ? COMMANDS.scriptMac
                    : scriptWinVariant === "cmd"
                    ? COMMANDS.scriptWinCmd
                    : COMMANDS.scriptWinPs
                }
                copied={
                  copiedId === `script-${scriptPlatform}-${scriptWinVariant}`
                }
                onCopy={() =>
                  handleCopy(
                    (scriptPlatform === "mac"
                      ? COMMANDS.scriptMac
                      : scriptWinVariant === "cmd"
                      ? COMMANDS.scriptWinCmd
                      : COMMANDS.scriptWinPs
                    ).join("\n"),
                    `script-${scriptPlatform}-${scriptWinVariant}`,
                  )
                }
                lang={lang}
              />
            </div>
          )}

          {/* Docker 内容 */}
          {selectedMethod === "docker" && (
            <CodeBlock
              lines={COMMANDS.docker}
              copied={copiedId === "docker"}
              onCopy={() => handleCopy(COMMANDS.docker.join("\n"), "docker")}
              lang={lang}
            />
          )}

          {/* 云部署内容 */}
          {selectedMethod === "cloud" && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-3)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  gap: "var(--space-2)",
                  padding: "var(--space-1)",
                  background: "var(--bg)",
                  borderRadius: "0.5rem",
                }}
              >
                {(["aliyun", "modelscope"] as const).map((variant) => (
                  <button
                    key={variant}
                    type="button"
                    onClick={() => setCloudVariant(variant)}
                    aria-pressed={cloudVariant === variant}
                    className={`quickstart-tab quickstart-tab-small ${
                      cloudVariant === variant ? "active" : ""
                    }`}
                  >
                    {t(lang, `quickstart.cloud.${variant}`)}
                  </button>
                ))}
              </div>
              {cloudVariant === "aliyun" ? (
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: "var(--space-2)",
                  }}
                >
                  <a
                    href={ALIYUN_ECS_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="quickstart-link quickstart-link-primary"
                  >
                    <Cloud size={16} strokeWidth={1.5} />
                    {t(lang, "quickstart.cloud.aliyunDeploy")}
                    <ExternalLink size={14} strokeWidth={1.5} />
                  </a>
                  <a
                    href={ALIYUN_DOC_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="quickstart-link quickstart-link-secondary"
                  >
                    <ExternalLink size={14} strokeWidth={1.5} />
                    {t(lang, "quickstart.cloud.aliyunDoc")}
                  </a>
                </div>
              ) : (
                <a
                  href={MODELSCOPE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="quickstart-link quickstart-link-primary"
                >
                  <Cloud size={16} strokeWidth={1.5} />
                  {t(lang, "quickstart.cloud.modelscopeGo")}
                  <ExternalLink size={14} strokeWidth={1.5} />
                </a>
              )}
            </div>
          )}

          {/* 桌面应用内容 */}
          {selectedMethod === "desktop" && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-3)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-2)",
                  padding: "var(--space-3)",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "0.5rem",
                }}
              >
                <div
                  style={{
                    fontSize: "0.8125rem",
                    fontWeight: 600,
                    color: "var(--text)",
                    marginBottom: "var(--space-1)",
                  }}
                >
                  {t(lang, "quickstart.desktop.platforms")}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                  }}
                >
                  <div
                    style={{
                      width: "0.375rem",
                      height: "0.375rem",
                      borderRadius: "50%",
                      background: "var(--text-muted)",
                    }}
                  />
                  <span
                    style={{
                      fontSize: "0.8125rem",
                      color: "var(--text-muted)",
                    }}
                  >
                    Windows 10+
                  </span>
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                  }}
                >
                  <div
                    style={{
                      width: "0.375rem",
                      height: "0.375rem",
                      borderRadius: "50%",
                      background: "var(--text-muted)",
                    }}
                  />
                  <span
                    style={{
                      fontSize: "0.8125rem",
                      color: "var(--text-muted)",
                    }}
                  >
                    macOS 14+ (Apple Silicon{" "}
                    {t(lang, "quickstart.desktop.recommended")})
                  </span>
                </div>
              </div>
              <a
                href={DESKTOP_RELEASES_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="quickstart-link quickstart-link-primary"
              >
                <Download size={16} strokeWidth={1.5} />
                {t(lang, "quickstart.desktop.downloadGithub")}
                <ExternalLink size={14} strokeWidth={1.5} />
              </a>
              <Link
                to={`${docsBase}/desktop`}
                className="quickstart-link quickstart-link-secondary"
              >
                <ExternalLink size={14} strokeWidth={1.5} />
                {t(lang, "quickstart.desktop.viewGuide")}
              </Link>
            </div>
          )}
        </div>
      </motion.div>

      <motion.p
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.5, delay: 0.5 }}
        style={{
          margin: "var(--space-4) 0 0",
          textAlign: "center",
          fontSize: "1rem",
          color: "var(--text-muted)",
          maxWidth: "40rem",
          marginLeft: "auto",
          marginRight: "auto",
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
      </motion.p>

      <style>{`
        @keyframes shimmer {
          0% {
            background-position: -200% 0;
          }
          100% {
            background-position: 200% 0;
          }
        }

        .quickstart-main-tab {
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: var(--space-2);
          padding: var(--space-3);
          font-size: 0.875rem;
          font-weight: 500;
          color: var(--text-muted);
          background: transparent;
          border: none;
          border-bottom: 2px solid transparent;
          cursor: pointer;
          transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .quickstart-main-tab.active {
          color: #1d1d1f;
          background: linear-gradient(to bottom, #f5f5f7, #fafafa);
          border-bottom-color: #667eea;
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
        }

        .quickstart-main-tab:not(.active):hover,
        .quickstart-main-tab:not(.active):focus-visible {
          color: var(--text);
          background: rgba(229, 229, 231, 0.5);
          transform: translateY(-1px);
        }

        .quickstart-main-tab:focus-visible {
          outline: 2px solid #d2d2d7;
          outline-offset: -2px;
        }

        .quickstart-link {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: var(--space-2);
          padding: var(--space-3) var(--space-4);
          border-radius: 0.5rem;
          text-decoration: none;
          font-weight: 500;
          font-size: 0.875rem;
          transition: all 0.2s ease;
          outline-offset: 2px;
        }

        .quickstart-link-primary {
          background: linear-gradient(135deg, #1d1d1f 0%, #2d2d2f 100%);
          color: var(--surface);
          border: none;
          position: relative;
          overflow: hidden;
        }

        .quickstart-link-primary::before {
          content: '';
          position: absolute;
          top: 0;
          left: -100%;
          width: 100%;
          height: 100%;
          background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
          transition: left 0.5s ease;
        }

        .quickstart-link-primary:hover::before {
          left: 100%;
        }

        .quickstart-link-primary:hover {
          background: var(--text);
          opacity: 0.85;
          transform: translateY(-2px) scale(1.02);
          box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
        }

        .quickstart-link-primary:focus-visible {
          outline: 2px solid var(--text);
          background: var(--text);
          opacity: 0.85;
        }

        .quickstart-link-secondary {
          background: transparent;
          color: var(--text-muted);
          border: 1px solid var(--border);
        }

        .quickstart-link-secondary:hover,
        .quickstart-link-secondary:focus-visible {
          color: var(--text);
          border-color: var(--text-muted);
          background: var(--bg);
        }

        .quickstart-link-secondary:focus-visible {
          outline: 2px solid #d2d2d7;
        }

        .quickstart-tab {
          flex: 1;
          padding: var(--space-2);
          font-size: 0.875rem;
          font-weight: 500;
          color: var(--text-muted);
          background: transparent;
          border: none;
          border-radius: 0.375rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .quickstart-tab-small {
          font-size: 0.8125rem;
        }

        .quickstart-tab.active {
          background: #d2d2d7;
          color: #1d1d1f;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
        }

        .quickstart-tab:not(.active):hover,
        .quickstart-tab:not(.active):focus-visible {
          background: #e5e5e7;
          color: #1d1d1f;
        }

        .quickstart-tab:focus-visible {
          outline: 2px solid #d2d2d7;
          outline-offset: 2px;
        }
      `}</style>
    </motion.section>
  );
}
