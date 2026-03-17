import {
  Layout,
  Menu,
  Button,
  Badge,
  Modal,
  Spin,
  Tooltip,
  type MenuProps,
} from "antd";
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  MessageSquare,
  Radio,
  Zap,
  MessageCircle,
  Wifi,
  UsersRound,
  CalendarClock,
  Activity,
  Sparkles,
  Briefcase,
  Cpu,
  Box,
  Globe,
  Settings,
  Shield,
  Plug,
  Wrench,
  PanelLeftClose,
  PanelLeftOpen,
  Copy,
  Check,
  BarChart3,
  Mic,
  Bot,
} from "lucide-react";
import api from "../api";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";

const { Sider } = Layout;

const PYPI_URL = "https://pypi.org/pypi/copaw/json";

const DEFAULT_OPEN_KEYS = [
  "chat-group",
  "control-group",
  "agent-group",
  "settings-group",
];

const KEY_TO_PATH: Record<string, string> = {
  chat: "/chat",
  channels: "/channels",
  sessions: "/sessions",
  "cron-jobs": "/cron-jobs",
  heartbeat: "/heartbeat",
  skills: "/skills",
  tools: "/tools",
  mcp: "/mcp",
  workspace: "/workspace",
  agents: "/agents",
  models: "/models",
  environments: "/environments",
  "agent-config": "/agent-config",
  security: "/security",
  "token-usage": "/token-usage",
  "voice-transcription": "/voice-transcription",
};

const UPDATE_MD: Record<string, string> = {
  zh: `### CoPaw如何更新

要更新 CoPaw 到最新版本，可根据你的安装方式选择对应方法：

1. 如果你使用的是一键安装脚本，直接重新运行安装命令即可自动升级。

2. 如果你是通过 pip 安装，在终端中执行以下命令升级：

\`\`\`
pip install --upgrade copaw
\`\`\`

3. 如果你是从源码安装，进入项目目录并拉取最新代码后重新安装：

\`\`\`
cd CoPaw
git pull origin main
pip install -e .
\`\`\`

4. 如果你使用的是 Docker，拉取最新镜像并重启容器：

\`\`\`
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
\`\`\`

升级后重启服务 copaw app。`,

  ru: `### Как обновить CoPaw

Чтобы обновить CoPaw, выберите способ в зависимости от типа установки:

1. Если вы устанавливали через однострочный скрипт, повторно запустите установщик для обновления.

2. Если устанавливали через pip, выполните:

\`\`\`
pip install --upgrade copaw
\`\`\`

3. Если устанавливали из исходников, получите последние изменения и переустановите:

\`\`\`
cd CoPaw
git pull origin main
pip install -e .
\`\`\`

4. Если используете Docker, загрузите новый образ и перезапустите контейнер:

\`\`\`
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
\`\`\`

После обновления перезапустите сервис с помощью \`copaw app\`.`,

  en: `### How to update CoPaw

To update CoPaw, use the method matching your installation type:

1. If installed via one-line script, re-run the installer to upgrade.

2. If installed via pip, run:

\`\`\`
pip install --upgrade copaw
\`\`\`

3. If installed from source, pull the latest code and reinstall:

\`\`\`
cd CoPaw
git pull origin main
pip install -e .
\`\`\`

4. If using Docker, pull the latest image and restart the container:

\`\`\`
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
\`\`\`

After upgrading, restart the service with \`copaw app\`.`,
};

interface SidebarProps {
  selectedKey: string;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const { t } = useTranslation();

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <Tooltip
      title={copied ? t("common.copied", "Copied!") : t("common.copy", "Copy")}
    >
      <Button
        type="text"
        size="small"
        icon={copied ? <Check size={13} /> : <Copy size={13} />}
        onClick={handleCopy}
        className={`${styles.copyBtn} ${
          copied ? styles.copyBtnCopied : styles.copyBtnDefault
        }`}
      />
    </Tooltip>
  );
}

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [openKeys, setOpenKeys] = useState<string[]>(DEFAULT_OPEN_KEYS);
  const [version, setVersion] = useState<string>("");
  const [latestVersion, setLatestVersion] = useState<string>("");
  const [allVersions, setAllVersions] = useState<string[]>([]);
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [updateMarkdown, setUpdateMarkdown] = useState<string>("");

  useEffect(() => {
    if (!collapsed) {
      setOpenKeys(DEFAULT_OPEN_KEYS);
    }
  }, [collapsed]);

  useEffect(() => {
    api
      .getVersion()
      .then((res) => setVersion(res?.version ?? ""))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(PYPI_URL)
      .then((res) => res.json())
      .then((data) => {
        const releases = data?.releases ?? {};
        // Sort versions by upload_time (newest first)
        const versionsWithTime = Object.entries(releases).map(
          ([version, files]) => {
            const fileList = files as Array<{ upload_time_iso_8601?: string }>;
            // Get the latest upload time among all files for this version
            const latestUpload = fileList
              .map((f) => f.upload_time_iso_8601)
              .filter(Boolean)
              .sort()
              .pop();
            return { version, uploadTime: latestUpload || "" };
          },
        );
        versionsWithTime.sort(
          (a, b) =>
            new Date(b.uploadTime).getTime() - new Date(a.uploadTime).getTime(),
        );
        const versions = versionsWithTime.map((v) => v.version);
        const latest = versions[0] ?? data?.info?.version ?? "";

        // Only show update notification if the latest version was released more than 1 hour ago
        // This gives Docker images time to build and become available
        const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
        const latestVersionReleaseTime = versionsWithTime.find(
          (v) => v.version === latest,
        )?.uploadTime;

        if (
          latestVersionReleaseTime &&
          new Date(latestVersionReleaseTime) <= oneHourAgo
        ) {
          setAllVersions(versions);
          setLatestVersion(latest);
        } else {
          // If latest version is less than 1 hour old, don't show update notification
          setAllVersions([]);
          setLatestVersion("");
        }
      })
      .catch(() => {});
  }, []);

  const hasUpdate =
    version &&
    allVersions.length > 0 &&
    allVersions.includes(version) &&
    version !== latestVersion;

  const handleOpenUpdateModal = () => {
    setUpdateMarkdown("");
    setUpdateModalOpen(true);
    const lang = i18n.language?.startsWith("zh")
      ? "zh"
      : i18n.language?.startsWith("ru")
      ? "ru"
      : "en";
    const faqLang = lang === "zh" ? "zh" : "en";
    const url = `https://copaw.agentscope.io/docs/faq.${faqLang}.md`;
    fetch(url, { cache: "no-cache" })
      .then((res) => (res.ok ? res.text() : Promise.reject()))
      .then((text) => {
        const zhPattern = /###\s*CoPaw如何更新[\s\S]*?(?=\n###|$)/;
        const enPattern = /###\s*How to update CoPaw[\s\S]*?(?=\n###|$)/;
        const match = text.match(faqLang === "zh" ? zhPattern : enPattern);
        setUpdateMarkdown(
          match && lang !== "ru"
            ? match[0].trim()
            : UPDATE_MD[lang] ?? UPDATE_MD.en,
        );
      })
      .catch(() => {
        setUpdateMarkdown(UPDATE_MD[lang] ?? UPDATE_MD.en);
      });
  };

  const menuItems: MenuProps["items"] = [
    {
      key: "chat-group",
      label: t("nav.chat"),
      icon: <MessageSquare size={16} />,
      children: [
        {
          key: "chat",
          label: t("nav.chat"),
          icon: <MessageCircle size={16} />,
        },
      ],
    },
    {
      key: "control-group",
      label: t("nav.control"),
      icon: <Radio size={16} />,
      children: [
        { key: "channels", label: t("nav.channels"), icon: <Wifi size={16} /> },
        {
          key: "sessions",
          label: t("nav.sessions"),
          icon: <UsersRound size={16} />,
        },
        {
          key: "cron-jobs",
          label: t("nav.cronJobs"),
          icon: <CalendarClock size={16} />,
        },
        {
          key: "heartbeat",
          label: t("nav.heartbeat"),
          icon: <Activity size={16} />,
        },
      ],
    },
    {
      key: "agent-group",
      label: t("nav.agent"),
      icon: <Zap size={16} />,
      children: [
        {
          key: "workspace",
          label: t("nav.workspace"),
          icon: <Briefcase size={16} />,
        },
        { key: "skills", label: t("nav.skills"), icon: <Sparkles size={16} /> },
        { key: "tools", label: t("nav.tools"), icon: <Wrench size={16} /> },
        { key: "mcp", label: t("nav.mcp"), icon: <Plug size={16} /> },
        {
          key: "agent-config",
          label: t("nav.agentConfig"),
          icon: <Settings size={16} />,
        },
      ],
    },
    {
      key: "settings-group",
      label: t("nav.settings"),
      icon: <Cpu size={16} />,
      children: [
        { key: "agents", label: t("nav.agents"), icon: <Bot size={16} /> },
        { key: "models", label: t("nav.models"), icon: <Box size={16} /> },
        {
          key: "environments",
          label: t("nav.environments"),
          icon: <Globe size={16} />,
        },
        {
          key: "security",
          label: t("nav.security"),
          icon: <Shield size={16} />,
        },
        {
          key: "token-usage",
          label: t("nav.tokenUsage"),
          icon: <BarChart3 size={16} />,
        },
        {
          key: "voice-transcription",
          label: t("nav.voiceTranscription"),
          icon: <Mic size={16} />,
        },
      ],
    },
  ];

  return (
    <Sider
      collapsed={collapsed}
      onCollapse={setCollapsed}
      width={275}
      className={`${styles.sider}${isDark ? ` ${styles.siderDark}` : ""}`}
    >
      <div className={styles.siderTop}>
        {!collapsed && (
          <div className={styles.logoWrapper}>
            <img
              src={isDark ? "/dark-logo.png" : "/logo.png"}
              alt="CoPaw"
              className={styles.logoImg}
            />
            {version && (
              <Badge dot={!!hasUpdate} color="red" offset={[4, 18]}>
                <span
                  className={`${styles.versionBadge} ${
                    hasUpdate
                      ? styles.versionBadgeClickable
                      : styles.versionBadgeDefault
                  }`}
                  onClick={() => hasUpdate && handleOpenUpdateModal()}
                >
                  v{version}
                </span>
              </Badge>
            )}
          </div>
        )}
        <Button
          type="text"
          icon={
            collapsed ? (
              <PanelLeftOpen size={20} />
            ) : (
              <PanelLeftClose size={20} />
            )
          }
          onClick={() => setCollapsed(!collapsed)}
          className={styles.collapseBtn}
        />
      </div>

      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        openKeys={openKeys}
        onOpenChange={(keys) => setOpenKeys(keys as string[])}
        onClick={({ key }) => {
          const path = KEY_TO_PATH[String(key)];
          if (path) navigate(path);
        }}
        items={menuItems}
        theme={isDark ? "dark" : "light"}
      />

      <Modal
        open={updateModalOpen}
        onCancel={() => setUpdateModalOpen(false)}
        title={
          <h3 className={styles.updateModalTitle}>
            {t("sidebar.updateModal.title", { version: latestVersion })}
          </h3>
        }
        width={680}
        footer={[
          <Button
            key="releases"
            type="primary"
            onClick={() => {
              const websiteLang = i18n.language?.startsWith("zh") ? "zh" : "en";
              window.open(
                `https://copaw.agentscope.io/release-notes?lang=${websiteLang}`,
                "_blank",
              );
            }}
            className={styles.updateModalPrimaryBtn}
          >
            {t("sidebar.updateModal.viewReleases")}
          </Button>,
          <Button key="close" onClick={() => setUpdateModalOpen(false)}>
            {t("sidebar.updateModal.close")}
          </Button>,
        ]}
      >
        <div className={styles.updateModalBody}>
          {!updateMarkdown ? (
            <div className={styles.updateModalSpinWrapper}>
              <Spin />
            </div>
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children, ...props }) {
                  const isBlock =
                    className?.startsWith("language-") ||
                    String(children).includes("\n");
                  if (isBlock) {
                    return (
                      <pre className={styles.codeBlock}>
                        <CopyButton text={String(children)} />
                        <code className={styles.codeBlockInner} {...props}>
                          {children}
                        </code>
                      </pre>
                    );
                  }
                  return (
                    <code className={styles.codeInline} {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {updateMarkdown}
            </ReactMarkdown>
          )}
        </div>
      </Modal>
    </Sider>
  );
}
