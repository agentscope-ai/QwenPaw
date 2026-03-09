import { useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Terminal,
  Copy,
  Check,
  Download,
  Cloud,
  Boxes,
  Package,
  Monitor,
  ExternalLink,
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
  delay?: number;
}

type InstallMethod = "pip" | "script" | "docker" | "desktop";
type ScriptPlatform = "mac" | "windows";
type ScriptWindowsVariant = "cmd" | "ps";
type DockerVariant = "docker" | "aliyun" | "modelscope";

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

export function QuickStart({ config, lang, delay = 0 }: QuickStartProps) {
  const [selectedMethod, setSelectedMethod] = useState<InstallMethod>("pip");
  const [scriptPlatform, setScriptPlatform] = useState<ScriptPlatform>("mac");
  const [scriptWinVariant, setScriptWinVariant] =
    useState<ScriptWindowsVariant>("cmd");
  const [dockerVariant, setDockerVariant] = useState<DockerVariant>("docker");
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
      label: "pip",
      desc:
        lang === "zh"
          ? "适合自行管理 Python 环境的用户"
          : "If you prefer managing Python yourself",
    },
    script: {
      icon: Terminal,
      label: lang === "zh" ? "脚本安装" : "Script",
      desc:
        lang === "zh"
          ? "无需手动配置 Python，一行命令自动完成安装。脚本会自动下载 uv（Python 包管理器）、创建虚拟环境、安装 CoPaw 及其依赖（含 Node.js 和前端资源）。注意：部分网络环境或企业权限管控下可能无法使用。"
          : "No Python setup required, one command installs everything. The script will automatically download uv (Python package manager), create a virtual environment, and install CoPaw with all dependencies (including Node.js and frontend assets). Note: May not work in restricted network environments or corporate firewalls.",
    },
    docker: {
      icon: Boxes,
      label: "Docker",
      desc:
        lang === "zh"
          ? "使用官方镜像，支持 Docker Hub / 阿里云 / 魔搭"
          : "Official images on Docker Hub / ACR / ModelScope",
    },
    desktop: {
      icon: Monitor,
      label: lang === "zh" ? "桌面应用" : "Desktop",
      desc:
        lang === "zh"
          ? "下载即用的桌面应用，无需命令行操作"
          : "Download and run, no command line required",
      badge: "Beta",
    },
  };

  return (
    <motion.section
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay }}
      style={{
        margin: "0 auto",
        maxWidth: "var(--container)",
        width: "100%",
        padding: "var(--space-8) var(--space-4)",
      }}
    >
      <div style={{ textAlign: "center", marginBottom: "var(--space-6)" }}>
        <h2
          style={{
            margin: "0 0 var(--space-3)",
            fontSize: "2rem",
            fontWeight: 600,
            color: "var(--text)",
          }}
        >
          {t(lang, "quickstart.title")}
        </h2>
        <p
          style={{
            margin: 0,
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
        </p>
      </div>

      <div
        style={{
          maxWidth: "52rem",
          margin: "0 auto",
          background: "var(--surface)",
          border: "1px solid var(--border)",
          borderRadius: "0.75rem",
          overflow: "hidden",
        }}
      >
        {/* 顶部方法选择 tabs */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(8rem, 1fr))",
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
                style={{
                  position: "relative",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "var(--space-2)",
                  padding: "var(--space-3)",
                  fontSize: "0.875rem",
                  fontWeight: 500,
                  color: isActive ? "var(--text)" : "var(--text-muted)",
                  background: isActive ? "var(--surface)" : "transparent",
                  border: "none",
                  borderBottom: isActive
                    ? "2px solid var(--text)"
                    : "2px solid transparent",
                  cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                <Icon size={16} strokeWidth={1.5} />
                <span>{label}</span>
                {badge && (
                  <span
                    style={{
                      padding: "0.125rem 0.375rem",
                      background: "var(--border)",
                      borderRadius: "0.25rem",
                      fontSize: "0.625rem",
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
                    style={{
                      flex: 1,
                      padding: "var(--space-2)",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      color:
                        scriptPlatform === platform
                          ? "var(--text)"
                          : "var(--text-muted)",
                      background:
                        scriptPlatform === platform
                          ? "var(--surface)"
                          : "transparent",
                      border: "none",
                      borderRadius: "0.375rem",
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                      boxShadow:
                        scriptPlatform === platform
                          ? "0 1px 3px rgba(0,0,0,0.1)"
                          : "none",
                    }}
                  >
                    {platform === "mac" ? "macOS / Linux" : "Windows"}
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
                      style={{
                        flex: 1,
                        padding: "var(--space-2)",
                        fontSize: "0.8125rem",
                        fontWeight: 500,
                        color:
                          scriptWinVariant === variant
                            ? "var(--text)"
                            : "var(--text-muted)",
                        background:
                          scriptWinVariant === variant
                            ? "var(--surface)"
                            : "transparent",
                        border: "none",
                        borderRadius: "0.375rem",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                        boxShadow:
                          scriptWinVariant === variant
                            ? "0 1px 3px rgba(0,0,0,0.1)"
                            : "none",
                      }}
                    >
                      {variant === "cmd" ? "CMD" : "PowerShell"}
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
                {(["docker", "aliyun", "modelscope"] as const).map(
                  (variant) => (
                    <button
                      key={variant}
                      type="button"
                      onClick={() => setDockerVariant(variant)}
                      aria-pressed={dockerVariant === variant}
                      style={{
                        flex: 1,
                        padding: "var(--space-2)",
                        fontSize: "0.8125rem",
                        fontWeight: 500,
                        color:
                          dockerVariant === variant
                            ? "var(--text)"
                            : "var(--text-muted)",
                        background:
                          dockerVariant === variant
                            ? "var(--surface)"
                            : "transparent",
                        border: "none",
                        borderRadius: "0.375rem",
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                        boxShadow:
                          dockerVariant === variant
                            ? "0 1px 3px rgba(0,0,0,0.1)"
                            : "none",
                      }}
                    >
                      {variant === "docker"
                        ? "Docker Hub"
                        : variant === "aliyun"
                        ? lang === "zh"
                          ? "阿里云"
                          : "Aliyun"
                        : lang === "zh"
                        ? "魔搭"
                        : "ModelScope"}
                    </button>
                  ),
                )}
              </div>
              {dockerVariant === "docker" ? (
                <CodeBlock
                  lines={COMMANDS.docker}
                  copied={copiedId === "docker-hub"}
                  onCopy={() =>
                    handleCopy(COMMANDS.docker.join("\n"), "docker-hub")
                  }
                  lang={lang}
                />
              ) : dockerVariant === "aliyun" ? (
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
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "var(--space-2)",
                      padding: "var(--space-3)",
                      background: "var(--bg)",
                      border: "1px solid var(--border)",
                      borderRadius: "0.5rem",
                      color: "var(--text)",
                      textDecoration: "none",
                      fontWeight: 500,
                      fontSize: "0.875rem",
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.borderColor = "var(--text-muted)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.borderColor = "var(--border)")
                    }
                  >
                    <Cloud size={16} strokeWidth={1.5} />
                    {lang === "zh"
                      ? "前往阿里云一键部署"
                      : "Deploy on Aliyun ECS"}
                    <ExternalLink size={14} strokeWidth={1.5} />
                  </a>
                  <a
                    href={ALIYUN_DOC_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "var(--space-2)",
                      padding: "var(--space-3)",
                      background: "var(--bg)",
                      border: "1px solid var(--border)",
                      borderRadius: "0.5rem",
                      color: "var(--text-muted)",
                      textDecoration: "none",
                      fontWeight: 500,
                      fontSize: "0.875rem",
                      transition: "all 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = "var(--text-muted)";
                      e.currentTarget.style.color = "var(--text)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = "var(--border)";
                      e.currentTarget.style.color = "var(--text-muted)";
                    }}
                  >
                    <ExternalLink size={14} strokeWidth={1.5} />
                    {lang === "zh" ? "查看说明文档" : "View Documentation"}
                  </a>
                </div>
              ) : (
                <a
                  href={MODELSCOPE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: "var(--space-2)",
                    padding: "var(--space-3)",
                    background: "var(--bg)",
                    border: "1px solid var(--border)",
                    borderRadius: "0.5rem",
                    color: "var(--text)",
                    textDecoration: "none",
                    fontWeight: 500,
                    fontSize: "0.875rem",
                    transition: "all 0.15s ease",
                  }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.borderColor = "var(--text-muted)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.borderColor = "var(--border)")
                  }
                >
                  <Cloud size={16} strokeWidth={1.5} />
                  {lang === "zh" ? "前往魔搭创空间" : "Go to ModelScope Studio"}
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
                  {lang === "zh" ? "支持平台" : "Supported Platforms"}
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
                    {lang === "zh" ? "推荐" : "recommended"})
                  </span>
                </div>
              </div>
              <a
                href={DESKTOP_RELEASES_URL}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "var(--space-2)",
                  padding: "var(--space-3)",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "0.5rem",
                  color: "var(--text)",
                  textDecoration: "none",
                  fontWeight: 500,
                  fontSize: "0.875rem",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) =>
                  (e.currentTarget.style.borderColor = "var(--text-muted)")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.borderColor = "var(--border)")
                }
              >
                <Download size={16} strokeWidth={1.5} />
                {lang === "zh" ? "前往 GitHub 下载" : "Download from GitHub"}
                <ExternalLink size={14} strokeWidth={1.5} />
              </a>
              <Link
                to={`${docsBase}/desktop`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "var(--space-2)",
                  padding: "var(--space-3)",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "0.5rem",
                  color: "var(--text-muted)",
                  textDecoration: "none",
                  fontWeight: 500,
                  fontSize: "0.875rem",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "var(--text-muted)";
                  e.currentTarget.style.color = "var(--text)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--border)";
                  e.currentTarget.style.color = "var(--text-muted)";
                }}
              >
                <ExternalLink size={14} strokeWidth={1.5} />
                {lang === "zh" ? "查看使用指南" : "View User Guide"}
              </Link>
            </div>
          )}
        </div>
      </div>
    </motion.section>
  );
}
