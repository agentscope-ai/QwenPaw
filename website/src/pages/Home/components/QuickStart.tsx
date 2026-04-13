import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "motion/react";
import {
  Check,
  Cloud,
  Container,
  Copy,
  FileText,
  Monitor,
  Terminal,
} from "lucide-react";
import {
  VectorIcon,
  FileCodeIcon,
  DddSubLevelIcon,
  AistorageIcon,
  GitHubIcon,
  ModelIcon,
  AliyunIcon,
} from "@/components/Icon";
import { sectionStyles } from "@/lib/utils";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";

type InstallMethod = "pip" | "script" | "docker" | "cloud" | "desktop";
type ScriptPlatform = "mac" | "windows";
type ScriptWindowsVariant = "cmd" | "ps";
type CloudPlatform = "aliyun" | "modelscope";

type QuickStartProps = {
  docsBase: string;
};

const DOCKER_IMAGE = "agentscope/qwenpaw:latest";
const MODELSCOPE_URL =
  "https://modelscope.cn/studios/fork?target=AgentScope/QwenPaw";
const ALIYUN_ECS_URL =
  "https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884";
const ALIYUN_DOC_URL = "https://developer.aliyun.com/article/1713682";
const DESKTOP_RELEASES_URL =
  "https://github.com/agentscope-ai/QwenPaw/releases";

const METHOD_ORDER: InstallMethod[] = [
  "pip",
  "script",
  "docker",
  "cloud",
  "desktop",
];

const METHOD_LUCIDE_ICON: Record<
  Exclude<InstallMethod, "pip">,
  typeof Terminal
> = {
  script: Terminal,
  docker: Container,
  cloud: Cloud,
  desktop: Monitor,
};

function MethodTabIcon({ method }: { method: InstallMethod }) {
  if (method === "pip") return <VectorIcon />;
  if (method === "script") return <FileCodeIcon />;
  if (method === "docker") return <DddSubLevelIcon />;
  if (method === "cloud") return <AistorageIcon />;
  const Icon = METHOD_LUCIDE_ICON[method];
  return <Icon size={14} strokeWidth={2} className="shrink-0" aria-hidden />;
}

export const PIP_INSTALL_COMMANDS = [
  "pip install qwenpaw",
  "qwenpaw init --defaults",
  "qwenpaw app",
] as const;

const COMMANDS = {
  pip: [...PIP_INSTALL_COMMANDS],
  scriptMac: [
    "curl -fsSL https://qwenpaw.agentscope.io/install.sh | bash",
    "qwenpaw init --defaults",
    "qwenpaw app",
  ],
  scriptWinCmd: [
    "curl -fsSL https://qwenpaw.agentscope.io/install.bat -o install.bat && install.bat",
    "qwenpaw init --defaults",
    "qwenpaw app",
  ],
  scriptWinPs: [
    "irm https://qwenpaw.agentscope.io/install.ps1 | iex",
    "qwenpaw init --defaults",
    "qwenpaw app",
  ],
  docker: [
    `docker pull ${DOCKER_IMAGE}`,
    `docker run -p 127.0.0.1:8088:8088 \\
  -v qwenpaw-data:/app/working \\
  -v qwenpaw-secrets:/app/working.secret \\
  ${DOCKER_IMAGE}`,
  ],
} as const;

const sectionVariants = {
  hidden: { opacity: 0, y: 20 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: "easeOut", staggerChildren: 0.08 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" } },
};

function CodeBlock({
  lines,
  copied,
  onCopy,
  t,
  headerLeft,
  className,
}: {
  lines: readonly string[];
  copied: boolean;
  onCopy: () => void;
  t: (key: string) => string;
  headerLeft?: JSX.Element | null;
  className?: string;
}) {
  const code = lines.join("\n");

  return (
    <div
      className={`relative flex h-full min-h-0 flex-col rounded-xl border border-[#ececec] bg-[#fafafa] ${
        className ?? ""
      }`}
    >
      <div className="flex items-center justify-between border-b border-[#e8e8e8] px-4 py-2.5 md:px-5">
        {headerLeft ? <div>{headerLeft}</div> : <div />}
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[#e6e6e6] bg-white px-2.5 py-1 text-xs font-medium text-[#666] hover:bg-[#f8f8f8]"
        >
          {copied ? (
            <Check size={12} aria-hidden />
          ) : (
            <Copy size={12} aria-hidden />
          )}
          {copied ? t("docs.copied") : t("docs.copy")}
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-x-auto px-4 py-4 text-center font-mono md:px-5 md:py-5">
        <SyntaxHighlighter
          language="bash"
          style={{
            'code[class*="language-"]': {
              color: "#1A1716",
              background: "transparent",
              fontFamily: "inherit",
              fontSize: "inherit",
              lineHeight: "inherit",
              textAlign: "left",
            },
            'pre[class*="language-"]': {
              background: "transparent",
              margin: 0,
              padding: 0,
            },
            comment: { color: "#6a737d", fontStyle: "italic" },
            prolog: { color: "#6a737d" },
            doctype: { color: "#6a737d" },
            cdata: { color: "#6a737d" },
            punctuation: { color: "#393A34" },
            property: { color: "#d73a49" },
            tag: { color: "#d73a49" },
            boolean: { color: "#d73a49" },
            number: { color: "#005cc5" },
            constant: { color: "#d73a49" },
            symbol: { color: "#d73a49" },
            deleted: { color: "#d73a49" },
            selector: { color: "#6f42c1" },
            "attr-name": { color: "#6f42c1" },
            string: { color: "#032f62" },
            char: { color: "#032f62" },
            builtin: { color: "#d73a49", fontWeight: "600" },
            inserted: { color: "#22863a" },
            operator: { color: "#d73a49" },
            entity: { color: "#6f42c1" },
            url: { color: "#032f62" },
            variable: { color: "#e36209" },
            atrule: { color: "#d73a49" },
            "attr-value": { color: "#032f62" },
            function: { color: "#6f42c1" },
            keyword: { color: "#d73a49", fontWeight: "600" },
            regex: { color: "#22863a" },
            important: { color: "#d73a49", fontWeight: "bold" },
            bold: { fontWeight: "bold" },
            italic: { fontStyle: "italic" },
          }}
          customStyle={{
            margin: 0,
            padding: 0,
            background: "transparent",
            fontSize: "inherit",
            lineHeight: "inherit",
          }}
          codeTagProps={{
            style: {
              fontFamily: "inherit",
              background: "transparent",
            },
          }}
          PreTag="div"
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}

export function QuickStart({ docsBase }: QuickStartProps) {
  const { t } = useTranslation();
  const [selectedMethod, setSelectedMethod] = useState<InstallMethod>("pip");
  const [scriptPlatform, setScriptPlatform] = useState<ScriptPlatform>("mac");
  const [scriptWinVariant, setScriptWinVariant] =
    useState<ScriptWindowsVariant>("cmd");
  const [cloudPlatform, setCloudPlatform] = useState<CloudPlatform>("aliyun");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const currentScriptCommands = useMemo(() => {
    if (scriptPlatform === "mac") {
      return COMMANDS.scriptMac;
    }
    return scriptWinVariant === "cmd"
      ? COMMANDS.scriptWinCmd
      : COMMANDS.scriptWinPs;
  }, [scriptPlatform, scriptWinVariant]);

  const copyLines = async (id: string, lines: readonly string[]) => {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 1600);
    } catch {
      setCopiedId(null);
    }
  };

  return (
    <>
      <motion.section
        className="relative"
        variants={sectionVariants}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-60px" }}
        id="qwenpaw-quickstart"
      >
        <div
          className="pointer-events-none absolute left-1/2 top-0 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-right_1s_linear_infinite]"
          style={{
            background:
              "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
            backgroundSize: "16px 100%",
          }}
        />
        <div
          className="pointer-events-none absolute left-1/2 top-full h-px w-screen -translate-x-1/2 -translate-y-px animate-[qwenpaw-dash-move-left_1s_linear_infinite]"
          style={{
            background:
              "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
            backgroundSize: "16px 100%",
          }}
        />
        <div className="relative mx-auto max-w-4xl">
          <div
            className="pointer-events-none absolute bottom-0 left-4 top-0 w-px md:left-0 animate-[qwenpaw-dash-move-down_1s_linear_infinite]"
            style={{
              background:
                "repeating-linear-gradient(to bottom, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              backgroundSize: "100% 16px",
            }}
          />
          <div
            className="pointer-events-none absolute bottom-0 right-4 top-0 w-px md:right-0 animate-[qwenpaw-dash-move-up_1s_linear_infinite]"
            style={{
              background:
                "repeating-linear-gradient(to bottom, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              backgroundSize: "100% 16px",
            }}
          />
          <div className="px-4 py-10 md:px-0 md:py-19">
            <motion.div className="text-center" variants={itemVariants}>
              <motion.h2
                variants={itemVariants}
                className={sectionStyles.title}
              >
                {t("quickstart.heroTitle")}
              </motion.h2>
              <motion.p
                variants={itemVariants}
                className={`${sectionStyles.subtitle} mx-auto mt-3 max-w-2xl px-2 sm:px-0 md:mb-16 md:mt-4`}
              >
                {t("quickstart.heroSub")}
              </motion.p>
            </motion.div>
            <div className="relative isolate mx-auto max-w-4xl">
              <div
                className="pointer-events-none absolute left-1/2 top-0 z-20 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-left_1s_linear_infinite]"
                style={{
                  background:
                    "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
                  backgroundSize: "16px 100%",
                }}
              />
              <div
                className="relative z-10 mt-6 rounded-2xl p-[2px] shadow-[0px_8px_32px_0px_rgba(212,212,212,0.25)] md:mt-8"
                style={{
                  background:
                    "linear-gradient(to bottom, var(--color-primary), #F0E6DF)",
                }}
              >
                <motion.div
                  className="overflow-hidden rounded-[16px] bg-white"
                  variants={itemVariants}
                  layout
                  transition={{ duration: 0.3, ease: "easeInOut" }}
                >
                  <div className="grid grid-cols-2 gap-px bg-(--bg) pb-px sm:grid-cols-5">
                    {METHOD_ORDER.map((method) => {
                      const active = method === selectedMethod;
                      return (
                        <button
                          key={method}
                          type="button"
                          onClick={() => setSelectedMethod(method)}
                          className={`inline-flex h-10 items-center justify-center gap-1 px-2 text-xs font-medium leading-none transition sm:h-12 sm:gap-1.5 sm:text-sm ${
                            active
                              ? "bg-(--color-primary)"
                              : "bg-(--color-secondary) text-[#4a4a4a] hover:bg-(--color-primary)"
                          }`}
                        >
                          <MethodTabIcon method={method} />
                          <span>{t(`quickstart.method.${method}`)}</span>
                          {method === "desktop" ? (
                            <span className="ml-1 h-4 rounded-xs bg-[#FFD8B8] px-1 py-px text-[9px] text-[#F46F02] sm:px-1 sm:text-[12px]">
                              {t("quickstart.badgeBeta")}
                            </span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>

                  <motion.div
                    className="flex min-h-[420px] flex-col p-3 md:min-h-[400px] md:p-7"
                    layout
                    transition={{ duration: 0.3, ease: "easeInOut" }}
                  >
                    <p className="font-inter mb-4 mt-2 text-sm leading-relaxed text-(--color-text-secondary) md:mb-4 md:mt-3 md:text-base">
                      {t(`quickstart.desc.${selectedMethod}`)}
                    </p>

                    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                      <AnimatePresence mode="wait" initial={false}>
                        {selectedMethod === "pip" ? (
                          <motion.div
                            key="pip"
                            className="flex min-h-0 flex-1 flex-col"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            transition={{ duration: 0.2 }}
                          >
                            <CodeBlock
                              lines={COMMANDS.pip}
                              copied={copiedId === "pip"}
                              onCopy={() => copyLines("pip", COMMANDS.pip)}
                              t={t}
                              className="min-h-0 flex-1"
                            />
                          </motion.div>
                        ) : null}

                        {selectedMethod === "script" ? (
                          <motion.div
                            key="script"
                            className="flex min-h-0 flex-1 flex-col gap-3"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            transition={{ duration: 0.2 }}
                          >
                            <div className="flex justify-center">
                              <div className="inline-flex rounded-xl border border-[#ebe5df] bg-(--color-fill-tertiary) p-1">
                                {(["mac", "windows"] as const).map(
                                  (platform) => (
                                    <button
                                      key={platform}
                                      type="button"
                                      onClick={() =>
                                        setScriptPlatform(platform)
                                      }
                                      className={`rounded-lg px-4 py-1.5 text-sm font-semibold sm:px-6 sm:py-2 sm:text-[1.05rem] ${
                                        scriptPlatform === platform
                                          ? "bg-white text-(--color-text) shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                                          : "text-(--color-text-secondary)"
                                      }`}
                                    >
                                      {t(`quickstart.platform.${platform}`)}
                                    </button>
                                  ),
                                )}
                              </div>
                            </div>

                            <CodeBlock
                              lines={currentScriptCommands}
                              copied={
                                copiedId ===
                                `script-${scriptPlatform}-${scriptWinVariant}`
                              }
                              onCopy={() =>
                                copyLines(
                                  `script-${scriptPlatform}-${scriptWinVariant}`,
                                  currentScriptCommands,
                                )
                              }
                              t={t}
                              className="min-h-0 flex-1"
                              headerLeft={
                                scriptPlatform === "windows" ? (
                                  <div className="inline-flex rounded-lg border border-[#e8e8e8] bg-(--color-fill-tertiary) p-1">
                                    {(["cmd", "ps"] as const).map((variant) => (
                                      <button
                                        key={variant}
                                        type="button"
                                        onClick={() =>
                                          setScriptWinVariant(variant)
                                        }
                                        className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                                          scriptWinVariant === variant
                                            ? "bg-white text-[#535b72] shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                                            : "text-[#8a90a3]"
                                        }`}
                                      >
                                        {t(`quickstart.shell.${variant}`)}
                                      </button>
                                    ))}
                                  </div>
                                ) : null
                              }
                            />
                          </motion.div>
                        ) : null}

                        {selectedMethod === "docker" ? (
                          <motion.div
                            key="docker"
                            className="flex min-h-0 flex-1 flex-col"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            transition={{ duration: 0.2 }}
                          >
                            <CodeBlock
                              lines={COMMANDS.docker}
                              copied={copiedId === "docker"}
                              onCopy={() =>
                                copyLines("docker", COMMANDS.docker)
                              }
                              t={t}
                              className="min-h-0 flex-1"
                            />
                          </motion.div>
                        ) : null}

                        {selectedMethod === "cloud" ? (
                          <motion.div
                            key="cloud"
                            className="grid min-h-[140px] gap-3"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            transition={{ duration: 0.2 }}
                          >
                            <div className="flex justify-center">
                              <div className="inline-flex h-11 items-center rounded-xl border border-[#ebe5df] bg-(--color-fill-tertiary) p-1 sm:h-11">
                                {(["aliyun", "modelscope"] as const).map(
                                  (platform) => (
                                    <button
                                      key={platform}
                                      type="button"
                                      onClick={() => setCloudPlatform(platform)}
                                      className={`inline-flex h-9 items-center justify-center whitespace-nowrap rounded-lg px-4 text-sm font-semibold leading-none sm:h-10 sm:px-6 sm:text-[1.05rem] ${
                                        cloudPlatform === platform
                                          ? "bg-white text-(--color-text) shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                                          : "text-(--color-text-secondary)"
                                      }`}
                                    >
                                      {t(`quickstart.cloud.${platform}`)}
                                    </button>
                                  ),
                                )}
                              </div>
                            </div>

                            <a
                              href={
                                cloudPlatform === "aliyun"
                                  ? ALIYUN_ECS_URL
                                  : MODELSCOPE_URL
                              }
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center justify-center gap-2 rounded-xl bg-(--color-secondary) px-4 py-3 text-sm font-medium text-(--color-text) hover:brightness-105 md:px-5 md:py-3.5 md:text-[1.08rem]"
                            >
                              {cloudPlatform === "aliyun" ? (
                                <>
                                  <AliyunIcon size={20} />
                                  {t("quickstart.cloud.aliyunDeploy")}
                                </>
                              ) : (
                                <>
                                  <ModelIcon size={20} />
                                  {t("quickstart.cloud.modelscopeGo")}
                                </>
                              )}
                            </a>

                            {cloudPlatform === "aliyun" ? (
                              <a
                                href={ALIYUN_DOC_URL}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d9d9d9] bg-white px-4 py-2.5 text-sm font-medium text-[#6a6a6a] hover:bg-[#fafafa] md:px-5 md:py-3 md:text-[1.08rem]"
                              >
                                <FileText size={16} aria-hidden />
                                {t("quickstart.cloud.aliyunDoc")}
                              </a>
                            ) : null}
                          </motion.div>
                        ) : null}

                        {selectedMethod === "desktop" ? (
                          <motion.div
                            key="desktop"
                            className="grid min-h-[220px] gap-3"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                            transition={{ duration: 0.2 }}
                          >
                            <div className="rounded-xl border border-[#ececec] bg-[#fafafa] p-4 md:p-5">
                              <div className="mb-2 font-mono text-sm font-semibold tracking-[0.01em] text-(--color-text) md:text-[0.95rem]">
                                {t("quickstart.desktop.platforms")}
                              </div>
                              <ul className="space-y-0.5 font-mono text-sm leading-6 text-(--color-text-secondary) md:text-[0.95rem] md:leading-7">
                                <li>Windows 10+</li>
                                <li>
                                  macOS 14+ (Apple Silicon{" "}
                                  {t("quickstart.desktop.recommended")})
                                </li>
                              </ul>
                            </div>

                            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                              <a
                                href={DESKTOP_RELEASES_URL}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center justify-center gap-2 rounded-xl bg-(--color-secondary) px-4 py-3 text-sm font-medium text-(--color-text) hover:brightness-105 md:px-5 md:py-3.5 md:text-[1.08rem]"
                              >
                                <GitHubIcon size={20} />
                                <span>
                                  {t("quickstart.desktop.downloadGithub")}
                                </span>
                                <span className="ml-0.5 rounded-xs bg-[#FFD8B8] px-1.5 py-0.5 text-[10px] font-semibold text-[#F46F02] sm:text-[11px]">
                                  {t("quickstart.desktop.recommended")}
                                </span>
                              </a>
                              <Link
                                to="/downloads"
                                className="inline-flex items-center justify-center gap-2 rounded-xl bg-(--color-secondary) px-4 py-3 text-sm font-medium text-(--color-text) hover:brightness-105 md:px-5 md:py-3.5 md:text-[1.08rem]"
                              >
                                <Monitor size={20} aria-hidden />
                                {t("quickstart.desktop.viewDownloads")}
                              </Link>
                            </div>
                            <Link
                              to={`${docsBase}/desktop`}
                              className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d9d9d9] bg-white px-4 py-2.5 text-sm font-medium text-[#6a6a6a] hover:bg-[#fafafa] md:px-5 md:py-3 md:text-[1.08rem]"
                            >
                              <FileText size={16} aria-hidden />
                              {t("quickstart.desktop.viewGuide")}
                            </Link>
                          </motion.div>
                        ) : null}
                      </AnimatePresence>
                    </div>
                  </motion.div>
                </motion.div>
              </div>
              <div
                className="pointer-events-none absolute bottom-0 left-1/2 h-px w-screen -translate-x-1/2 animate-[qwenpaw-dash-move-right_1s_linear_infinite]"
                style={{
                  background:
                    "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
                  backgroundSize: "16px 100%",
                }}
              />
            </div>
          </div>
        </div>
      </motion.section>
    </>
  );
}
