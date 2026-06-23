import { Layout, Space, Badge, Spin, Tooltip, Dropdown } from "antd";
import type { MenuProps } from "antd";
import LanguageSwitcher, {
  LANGUAGE_LIST,
} from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import CodingModeToggle from "../components/CodingModeToggle";
import { useTranslation } from "react-i18next";
import { Button, Modal } from "@agentscope-ai/design";
import styles from "./index.module.less";
import api from "../api";
import { openExternalLink } from "../utils/openExternalLink";
import {
  GITHUB_URL,
  getDocsUrl,
  getFeatureDemosUrl,
  getFaqUrl,
  getReleaseNotesUrl,
  PYPI_URL,
  ONE_HOUR_MS,
  UPDATE_MD,
  isStableVersion,
  compareVersions,
} from "./constants";
import { useTheme } from "../contexts/ThemeContext";
import { useState, useEffect } from "react";
import { Slot } from "../plugins/registry/Slot";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  CopyOutlined,
  CheckOutlined,
  TagOutlined,
  GithubOutlined,
  FileTextOutlined,
  ReadOutlined,
  PlayCircleOutlined,
  InfoCircleOutlined,
  DownOutlined,
} from "@ant-design/icons";

const { Header: AntHeader } = Layout;

// ── Code block with copy button ───────────────────────────────────────────
function UpdateCodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <div className={styles.codeBlock}>
      <code className={styles.codeBlockInner}>{code}</code>
      <button
        className={`${styles.copyBtn} ${
          copied ? styles.copyBtnCopied : styles.copyBtnDefault
        }`}
        onClick={handleCopy}
        title="Copy"
      >
        {copied ? <CheckOutlined /> : <CopyOutlined />}
      </button>
    </div>
  );
}

export default function Header() {
  const { t, i18n } = useTranslation();
  const { isDark, setThemeMode } = useTheme();
  const [version, setVersion] = useState<string>("");
  const [latestVersion, setLatestVersion] = useState<string>("");
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [updateMarkdown, setUpdateMarkdown] = useState<string>("");

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

        const versionsWithTime = Object.entries(releases)
          .filter(([v]) => isStableVersion(v))
          .map(([v, files]) => {
            const fileList = files as Array<{ upload_time_iso_8601?: string }>;
            const latestUpload = fileList
              .map((f) => f.upload_time_iso_8601)
              .filter(Boolean)
              .sort()
              .pop();
            return { version: v, uploadTime: latestUpload || "" };
          });

        versionsWithTime.sort((a, b) => {
          const timeDiff =
            new Date(b.uploadTime).getTime() - new Date(a.uploadTime).getTime();
          return timeDiff !== 0
            ? timeDiff
            : compareVersions(b.version, a.version);
        });

        const versions = versionsWithTime.map((v) => v.version);
        const latest = versions[0] ?? data?.info?.version ?? "";

        const releaseTime = versionsWithTime.find((v) => v.version === latest)
          ?.uploadTime;
        const isOldEnough =
          !!releaseTime &&
          new Date(releaseTime) <= new Date(Date.now() - ONE_HOUR_MS);

        if (isOldEnough) {
          setLatestVersion(latest);
        } else {
          setLatestVersion("");
        }
      })
      .catch(() => {});
  }, []);

  const hasUpdate =
    !!version && !!latestVersion && compareVersions(latestVersion, version) > 0;

  const resourcesMenuItems: MenuProps["items"] = [
    {
      key: "tutorial",
      icon: <ReadOutlined />,
      label: t("header.tutorial"),
      onClick: () => handleNavClick(getDocsUrl(i18n.language)),
    },
    {
      key: "featureDemos",
      icon: <PlayCircleOutlined />,
      label: t("header.featureDemos"),
      onClick: () => handleNavClick(getFeatureDemosUrl(i18n.language)),
    },
    {
      key: "changelog",
      icon: <FileTextOutlined />,
      label: t("header.changelog"),
      onClick: () => handleNavClick(getReleaseNotesUrl(i18n.language)),
    },
    {
      key: "faq",
      icon: <InfoCircleOutlined />,
      label: t("header.faq"),
      onClick: () => handleNavClick(getFaqUrl(i18n.language)),
    },
    {
      key: "github",
      icon: <GithubOutlined />,
      label: t("header.github"),
      onClick: () => handleNavClick(GITHUB_URL),
    },
  ];

  const mobileMenuItems: MenuProps["items"] = [
    {
      key: "language",
      label: t("sidebar.settings.language"),
      children: LANGUAGE_LIST.map(({ key, label }) => ({
        key,
        label,
        onClick: () => {
          i18n.changeLanguage(key);
          localStorage.setItem("language", key);
        },
      })),
    },
    {
      key: "theme",
      label: t("sidebar.settings.theme"),
      children: [
        {
          key: "light",
          label: t("theme.light"),
          onClick: () => setThemeMode("light"),
        },
        {
          key: "dark",
          label: t("theme.dark"),
          onClick: () => setThemeMode("dark"),
        },
        {
          key: "system",
          label: t("theme.system"),
          onClick: () => setThemeMode("system"),
        },
      ],
    },
    { type: "divider" },
    ...resourcesMenuItems,
  ];

  const handleOpenUpdateModal = () => {
    setUpdateMarkdown("");
    setUpdateModalOpen(true);
    const lang = i18n.language?.startsWith("zh")
      ? "zh"
      : i18n.language?.startsWith("ru")
      ? "ru"
      : "en";
    const faqLang = lang === "zh" ? "zh" : "en";
    const url = `https://qwenpaw.agentscope.io/docs/faq.${faqLang}.md`;
    fetch(url, { cache: "no-cache" })
      .then((res) => (res.ok ? res.text() : Promise.reject()))
      .then((text) => {
        const zhPattern = /###\s*QwenPaw如何更新[\s\S]*?(?=\n###|$)/;
        const enPattern = /###\s*How to update QwenPaw[\s\S]*?(?=\n###|$)/;
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

  const handleNavClick = (url: string) => {
    openExternalLink(url);
  };

  return (
    <>
      <AntHeader className={styles.header}>
        <div className={styles.logoWrapper}>
          {/*
            Slot lets a plugin replace the brand logo (e.g. a per-agent
            branding override). When no plugin registers a replacement —
            or when the registered render returns null — the host default
            <img> below paints.
          */}
          <Slot name="header.logo" kind="replace">
            <img
              src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
              alt="QwenPaw"
              className={styles.logoImg}
            />
          </Slot>
          <div className={styles.logoDivider} />
          {version && (
            <Badge
              dot={!!hasUpdate}
              color="rgba(255, 157, 77, 1)"
              offset={[4, 28]}
            >
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
        <Slot name="header.left" kind="fill" />
        <Space size="middle">
          <Slot name="header.right" kind="fill" />
          {resourcesMenuItems.length > 0 && (
            <Dropdown menu={{ items: resourcesMenuItems }}>
              <Button type="text" className={styles.hideOnMobile}>
                {t("header.resources")} <DownOutlined />
              </Button>
            </Dropdown>
          )}
          <Tooltip title={t("header.github")}>
            <Button
              type="text"
              icon={<GithubOutlined />}
              onClick={() => handleNavClick(GITHUB_URL)}
              className={styles.hideOnMobile}
            >
              {t("header.github")}
            </Button>
          </Tooltip>
          <div className={styles.headerDivider} />
          <span className={styles.hideOnMobile}>
            <CodingModeToggle />
          </span>
          <div className={styles.headerDivider} />
          <span className={styles.hideOnMobile}>
            <LanguageSwitcher />
          </span>
          <span className={styles.hideOnMobile}>
            <ThemeToggleButton />
          </span>
          <Dropdown menu={{ items: mobileMenuItems }} placement="bottomRight">
            <Button
              type="text"
              icon={<InfoCircleOutlined />}
              className={styles.showOnMobile}
              title={t("header.resources")}
            />
          </Dropdown>
        </Space>
      </AntHeader>

      <Modal
        title={null}
        open={updateModalOpen}
        onCancel={() => setUpdateModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setUpdateModalOpen(false)}>
            {t("common.close")}
          </Button>,
          <Button
            key="releases"
            type="primary"
            className={styles.updateViewReleasesBtn}
            onClick={() => handleNavClick(getReleaseNotesUrl(i18n.language))}
          >
            {t("sidebar.updateModal.viewReleases")}
          </Button>,
        ]}
        width={960}
        className={styles.updateModal}
      >
        {/* Banner area */}
        <div className={styles.updateModalBanner}>
          <div className={styles.updateModalBannerLeft}>
            <span className={styles.updateModalVersionTag}>
              <TagOutlined />
              Version {latestVersion || version}
            </span>
            <div className={styles.updateModalBannerTitle}>
              {t("sidebar.updateModal.title", {
                version: latestVersion || version,
              })}
            </div>
          </div>
        </div>

        {/* Markdown content */}
        <div className={styles.updateModalBody}>
          {updateMarkdown ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a({ href, children, ...props }: any) {
                  return (
                    <a
                      {...props}
                      href={href}
                      onClick={(e) => {
                        e.preventDefault();
                        if (href) handleNavClick(href);
                      }}
                      style={{ cursor: "pointer" }}
                    >
                      {children}
                    </a>
                  );
                },
                code({ node, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || "");
                  const isBlock =
                    node?.position?.start?.line !== node?.position?.end?.line ||
                    match;
                  return isBlock ? (
                    <UpdateCodeBlock
                      code={String(children).replace(/\n$/, "")}
                    />
                  ) : (
                    <code className={styles.codeInline} {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {updateMarkdown}
            </ReactMarkdown>
          ) : (
            <div className={styles.updateModalSpinWrapper}>
              <Spin />
            </div>
          )}
        </div>
      </Modal>
    </>
  );
}
