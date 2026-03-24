import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AnimatePresence, motion } from "motion/react";
import {
  Check,
  Cloud,
  Container,
  Copy,
  ExternalLink,
  FileText,
  Github,
  Monitor,
  Package,
  Terminal,
} from "lucide-react";

type InstallMethod = "pip" | "script" | "docker" | "cloud" | "desktop";
type ScriptPlatform = "mac" | "windows";
type ScriptWindowsVariant = "cmd" | "ps";

type CopawQuickStartProps = {
  docsBase: string;
};

const DOCKER_IMAGE = "agentscope/copaw:latest";
const MODELSCOPE_URL =
  "https://modelscope.cn/studios/fork?target=AgentScope/CoPaw";
const ALIYUN_ECS_URL =
  "https://computenest.console.aliyun.com/service/instance/create/cn-hangzhou?type=user&ServiceId=service-1ed84201799f40879884";
const ALIYUN_DOC_URL = "https://developer.aliyun.com/article/1713682";
const DESKTOP_RELEASES_URL = "https://github.com/agentscope-ai/CoPaw/releases";

const METHOD_ORDER: InstallMethod[] = [
  "pip",
  "script",
  "docker",
  "cloud",
  "desktop",
];

const METHOD_ICON: Record<InstallMethod, typeof Package> = {
  pip: Package,
  script: Terminal,
  docker: Container,
  cloud: Cloud,
  desktop: Monitor,
};

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
    `docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working -v copaw-secrets:/app/working.secret ${DOCKER_IMAGE}`,
  ],
} as const;

const sectionVariants = {
  hidden: { opacity: 0, y: 20 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.45, ease: "easeOut", staggerChildren: 0.08 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: "easeOut" } },
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
  return (
    <div
      className={`relative flex h-full min-h-0 flex-col rounded-xl border border-[#ececec] bg-[#fafafa] p-4 md:p-5 ${className ?? ""}`}
    >
      {headerLeft ? <div className="mb-2">{headerLeft}</div> : null}
      <button
        type="button"
        onClick={onCopy}
        className="absolute right-4 top-4 z-10 inline-flex items-center gap-1.5 rounded-xl border border-[#e6e6e6] bg-white px-3 py-1.5 text-xs font-medium text-[#666] hover:bg-[#f8f8f8]"
      >
        {copied ? <Check size={12} aria-hidden /> : <Copy size={12} aria-hidden />}
        {copied ? t("docs.copied") : t("docs.copy")}
      </button>
      <pre className="min-h-0 flex-1 overflow-x-auto whitespace-pre-wrap break-all pr-20 text-left font-mono text-sm leading-6 text-[#2c2c2c] md:pr-24 md:text-[0.92rem] md:leading-7">
        {lines.join("\n")}
      </pre>
    </div>
  );
}

export function CopawQuickStart({ docsBase }: CopawQuickStartProps) {
  const { t } = useTranslation();
  const [selectedMethod, setSelectedMethod] = useState<InstallMethod>("pip");
  const [scriptPlatform, setScriptPlatform] = useState<ScriptPlatform>("mac");
  const [scriptWinVariant, setScriptWinVariant] =
    useState<ScriptWindowsVariant>("cmd");
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
    <motion.section
      className="relative"
      variants={sectionVariants}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: "-60px" }}
      id="copaw-quickstart"
    >
      <div
        className="pointer-events-none absolute left-1/2 top-0 h-px w-screen -translate-x-1/2"
        style={{
          background:
            "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
        }}
      />
      <div
        className="pointer-events-none absolute left-1/2 top-full h-px w-screen -translate-x-1/2 -translate-y-px"
        style={{
          background:
            "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
        }}
      />
      <div className="relative mx-auto max-w-5xl">
        <div
          className="pointer-events-none absolute bottom-0 left-4 top-0 w-px md:left-0"
          style={{
            background:
              "repeating-linear-gradient(to bottom, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
          }}
        />
        <div
          className="pointer-events-none absolute bottom-0 right-4 top-0 w-px md:right-0"
          style={{
            background:
              "repeating-linear-gradient(to bottom, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
          }}
        />
        <div className="px-4 py-10 md:px-0 md:py-19">
          <motion.div className="text-center" variants={itemVariants}>
            <motion.h2
              variants={itemVariants}
              className="font-newsreader text-[1.9rem] font-semibold leading-[1.2] text-(--color-text) md:text-[3rem]"
            >
              Do it yourself, done easily.
            </motion.h2>
            <motion.p
              variants={itemVariants}
              className="font-inter mx-auto mt-3 max-w-2xl px-2 text-[13px] font-medium leading-[1.55] text-(--color-text-tertiary) sm:px-0 sm:text-[14px] md:mb-16 md:mt-4 md:text-[16px]"
            >
              Memory and personalization under your control. Memory and
              personalization under your control.Memory and personalization
              under your control.
            </motion.p>
          </motion.div>
          <div className="relative mx-auto max-w-5xl">
            <div
              className="pointer-events-none absolute left-1/2 top-0 h-px w-screen -translate-x-1/2"
              style={{
                background:
                  "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              }}
            />
            <motion.div
              className="mt-6 overflow-hidden rounded-2xl border border-(--color-primary) bg-white shadow-[0_10px_26px_rgba(28,28,28,0.06)] md:mt-8"
              variants={itemVariants}
            >
              <div className="grid grid-cols-2 border-b border-[#efe3d8] sm:grid-cols-5">
                {METHOD_ORDER.map((method) => {
                  const Icon = METHOD_ICON[method];
                  const active = method === selectedMethod;
                  return (
                    <button
                      key={method}
                      type="button"
                      onClick={() => setSelectedMethod(method)}
                      className={`inline-flex h-10 items-center justify-center gap-1 border-r border-[#efe3d8] px-2 text-xs font-medium transition last:border-r-0 sm:h-11 sm:gap-1.5 sm:text-sm ${
                        active
                          ? "bg-(--color-primary) text-white"
                          : "bg-[#fbf1e8] text-[#4a4a4a] hover:bg-[#f7e8db]"
                      }`}
                    >
                      <Icon size={14} strokeWidth={2} aria-hidden />
                      <span>{t(`quickstart.method.${method}`)}</span>
                      {method === "desktop" ? (
                        <span className="ml-1 rounded bg-[#f6c48f] px-1 py-px text-[9px] text-[#8b4b07] sm:px-1.5 sm:text-[10px]">
                          {t("quickstart.badgeBeta")}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>

              <div className="flex h-90 flex-col p-3 md:h-105 md:p-7">
                <p className="mb-4 mt-2 text-sm leading-relaxed text-(--color-text-secondary) md:mb-6 md:mt-4 md:text-[1.02rem]">
                  {t(`quickstart.desc.${selectedMethod}`)}
                </p>

                <div className="min-h-0 flex-1 overflow-y-auto">
                  <AnimatePresence mode="wait" initial={false}>
                  {selectedMethod === "pip" ? (
                    <motion.div
                      key="pip"
                      className="h-full"
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
                        className="h-full"
                      />
                    </motion.div>
                  ) : null}

                  {selectedMethod === "script" ? (
                    <motion.div
                      key="script"
                      className="flex h-full min-h-0 flex-col gap-3"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.2 }}
                    >
                      <div className="flex justify-center">
                        <div className="inline-flex rounded-xl border border-[#ebe5df] bg-[#f6f2ee] p-1">
                          {(["mac", "windows"] as const).map((platform) => (
                            <button
                              key={platform}
                              type="button"
                              onClick={() => setScriptPlatform(platform)}
                              className={`rounded-lg px-4 py-1.5 text-sm font-semibold sm:px-6 sm:py-2 sm:text-[1.05rem] ${
                                scriptPlatform === platform
                                  ? "bg-white text-(--color-text) shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                                  : "text-(--color-text-secondary)"
                              }`}
                            >
                              {t(`quickstart.platform.${platform}`)}
                            </button>
                          ))}
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
                        className="flex-1"
                        headerLeft={
                          scriptPlatform === "windows" ? (
                            <div className="inline-flex rounded-lg border border-[#e8e8e8] bg-[#f3f4f6] p-1">
                              {(["cmd", "ps"] as const).map((variant) => (
                                <button
                                  key={variant}
                                  type="button"
                                  onClick={() => setScriptWinVariant(variant)}
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
                      className="h-full"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.2 }}
                    >
                      <CodeBlock
                        lines={COMMANDS.docker}
                        copied={copiedId === "docker"}
                        onCopy={() => copyLines("docker", COMMANDS.docker)}
                        t={t}
                        className="h-full"
                      />
                    </motion.div>
                  ) : null}

                  {selectedMethod === "cloud" ? (
                    <motion.div
                      key="cloud"
                      className="space-y-3"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.2 }}
                    >
                    <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
                      <a
                        href={ALIYUN_ECS_URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex w-fit items-center justify-center gap-2 rounded-xl border border-[#dfc2a2] bg-(--color-primary) px-4 py-2 text-sm font-semibold text-[#5e3d1e] shadow-[0_1px_1px_rgba(0,0,0,0.08)] hover:brightness-105 md:px-5 md:py-2.5 md:text-[1.08rem]"
                      >
                        <Cloud size={16} aria-hidden />
                        {t("quickstart.cloud.aliyunDeploy")}
                      </a>
                      <a
                        href={ALIYUN_DOC_URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex w-fit items-center justify-center gap-2 rounded-xl border border-[#d9d9d9] bg-white px-4 py-2 text-sm font-semibold text-[#6a6a6a] hover:bg-[#fafafa] md:px-5 md:py-2.5 md:text-[1.08rem]"
                      >
                        <ExternalLink size={16} aria-hidden />
                        {t("quickstart.cloud.aliyunDoc")}
                      </a>
                      <div className="basis-full">
                        <a
                          href={MODELSCOPE_URL}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex w-fit items-center justify-center gap-2 rounded-xl border border-[#dfc2a2] bg-(--color-primary) px-4 py-2 text-sm font-semibold text-[#5e3d1e] shadow-[0_1px_1px_rgba(0,0,0,0.08)] hover:brightness-105 md:px-5 md:py-2.5 md:text-[1.08rem]"
                        >
                          <Cloud size={16} aria-hidden />
                          {t("quickstart.cloud.modelscopeGo")}
                        </a>
                      </div>
                    </div>
                    </motion.div>
                  ) : null}

                  {selectedMethod === "desktop" ? (
                    <motion.div
                      key="desktop"
                      className="space-y-5"
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.2 }}
                    >
                      <div className="rounded-2xl border border-[#ececec] bg-[#fafafa] p-4 md:p-6">
                        <div className="mb-2 font-mono text-sm font-semibold tracking-[0.01em] text-(--color-text) md:mb-3 md:text-[1.02rem]">
                          {t("quickstart.desktop.platforms")}
                        </div>
                        <ul className="space-y-1 font-mono text-sm leading-6 text-(--color-text-secondary) md:space-y-1.5 md:text-[1.02rem] md:leading-8">
                          <li>Windows 10+</li>
                          <li>
                            macOS 14+ (Apple Silicon{" "}
                            {t("quickstart.desktop.recommended")})
                          </li>
                        </ul>
                      </div>

                      <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
                        <a
                          href={DESKTOP_RELEASES_URL}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#dfc2a2] bg-(--color-primary) px-4 py-2 text-sm font-semibold text-[#5e3d1e] shadow-[0_1px_1px_rgba(0,0,0,0.08)] hover:brightness-105 md:px-5 md:py-2.5 md:text-[1.08rem]"
                        >
                          <Github size={16} aria-hidden />
                          {t("quickstart.desktop.downloadGithub")}
                        </a>
                        <Link
                          to={`${docsBase}/desktop`}
                          className="inline-flex items-center justify-center gap-2 rounded-xl border border-[#d9d9d9] bg-white px-4 py-2 text-sm font-semibold text-[#6a6a6a] hover:bg-[#fafafa] md:px-5 md:py-2.5 md:text-[1.08rem]"
                        >
                          <FileText size={16} aria-hidden />
                          {t("quickstart.desktop.viewGuide")}
                        </Link>
                      </div>
                    </motion.div>
                  ) : null}
                  </AnimatePresence>
                </div>
              </div>
            </motion.div>
            <div
              className="pointer-events-none absolute bottom-0 left-1/2 h-px w-screen -translate-x-1/2"
              style={{
                background:
                  "repeating-linear-gradient(to right, rgba(255,157,77,0.45) 0 8px, transparent 8px 16px)",
              }}
            />
          </div>
        </div>
      </div>
    </motion.section>
  );
}
