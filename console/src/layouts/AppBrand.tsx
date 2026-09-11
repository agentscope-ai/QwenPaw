import { Badge, message, Popover, Spin, Tooltip } from "antd";
import {
  CheckCircleOutlined,
  CheckOutlined,
  CopyOutlined,
  ExclamationCircleOutlined,
  SyncOutlined,
  TagOutlined,
} from "@ant-design/icons";
import { Button, Modal } from "@agentscope-ai/design";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api from "../api";
import { ExternalMarkdownLink } from "../components/Markdown/externalLinkComponents";
import { useDesktopUpdate } from "../contexts/DesktopUpdateContext";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import { isDesktopApp } from "../tauri/backendRuntime";
import { openExternalLink } from "../utils/openExternalLink";
import {
  compareVersions,
  getReleaseNotesUrl,
  isStableVersion,
  ONE_HOUR_MS,
  PYPI_URL,
  UPDATE_MD,
} from "./constants";
import styles from "./index.module.less";

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

interface AppBrandProps {
  action?: ReactNode;
  hidden?: boolean;
  version?: string;
}

export default function AppBrand({
  action,
  hidden = false,
  version: versionProp,
}: AppBrandProps) {
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const desktop = useDesktopUpdate();
  const onDesktop = isDesktopApp();
  const [loadedVersion, setLoadedVersion] = useState("");
  const version = versionProp ?? loadedVersion;
  const [latestVersion, setLatestVersion] = useState("");
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [updateMarkdown, setUpdateMarkdown] = useState("");
  const logoClicksRef = useRef<number[]>([]);

  useEffect(() => {
    if (versionProp !== undefined) return;
    void api
      .getVersion()
      .then((response) => setLoadedVersion(response?.version ?? ""))
      .catch(() => {});
  }, [versionProp]);

  useEffect(() => {
    if (onDesktop) return;

    fetch(PYPI_URL)
      .then((response) => response.json())
      .then((data) => {
        const releases = data?.releases ?? {};
        const versionsWithTime = Object.entries(releases)
          .filter(([candidate]) => isStableVersion(candidate))
          .map(([candidate, files]) => {
            const fileList = files as Array<{
              upload_time_iso_8601?: string;
            }>;
            const latestUpload = fileList
              .map((file) => file.upload_time_iso_8601)
              .filter(Boolean)
              .sort()
              .pop();
            return {
              version: candidate,
              uploadTime: latestUpload || "",
            };
          });

        versionsWithTime.sort((left, right) => {
          const timeDiff =
            new Date(right.uploadTime).getTime() -
            new Date(left.uploadTime).getTime();
          return timeDiff !== 0
            ? timeDiff
            : compareVersions(right.version, left.version);
        });

        const latest =
          versionsWithTime[0]?.version ?? data?.info?.version ?? "";
        const releaseTime = versionsWithTime.find(
          (item) => item.version === latest,
        )?.uploadTime;
        const isOldEnough =
          !!releaseTime &&
          new Date(releaseTime) <= new Date(Date.now() - ONE_HOUR_MS);
        setLatestVersion(isOldEnough ? latest : "");
      })
      .catch(() => {});
  }, [onDesktop]);

  const hasUpdate = onDesktop
    ? desktop.hasUpdate
    : !!version &&
      !!latestVersion &&
      compareVersions(latestVersion, version) > 0;
  const modalVersion = onDesktop ? desktop.version : latestVersion;
  const isBackgroundActive =
    onDesktop &&
    desktop.isBackground &&
    (desktop.phase === "checking" || desktop.phase === "downloading");
  const isReady = onDesktop && desktop.phase === "downloaded";
  const isApplyingDownloadedUpdate =
    onDesktop && desktop.phase === "installing";
  const isBackgroundFailed =
    onDesktop && desktop.isBackground && desktop.phase === "failed";
  const backgroundDownloadPercent =
    isBackgroundActive && desktop.phase === "downloading" && desktop.total
      ? Math.min(99, Math.round((desktop.downloaded / desktop.total) * 100))
      : undefined;
  const backgroundDownloadTitle =
    backgroundDownloadPercent !== undefined
      ? `${t(
          "sidebar.updateModal.backgroundDownloading",
        )} ${backgroundDownloadPercent}%`
      : t("sidebar.updateModal.backgroundDownloading");
  const backgroundFailureTitle = desktop.error?.message
    ? `${t("sidebar.updateModal.backgroundFailed")}: ${desktop.error.message}`
    : t("sidebar.updateModal.backgroundFailed");
  const handleOpenUpdateModal = () => {
    setUpdateMarkdown("");
    setUpdateModalOpen(true);
    const language = i18n.language?.startsWith("zh")
      ? "zh"
      : i18n.language?.startsWith("ru")
      ? "ru"
      : "en";

    if (onDesktop) {
      setUpdateMarkdown(
        desktop.body ||
          t("sidebar.updateModal.desktopInstallHint", {
            version: desktop.version,
          }),
      );
      return;
    }

    const faqLanguage = language === "zh" ? "zh" : "en";
    fetch(`https://qwenpaw.agentscope.io/docs/faq.${faqLanguage}.md`, {
      cache: "no-cache",
    })
      .then((response) => (response.ok ? response.text() : Promise.reject()))
      .then((text) => {
        const zhPattern = /###\s*QwenPaw如何更新[\s\S]*?(?=\n###|$)/;
        const enPattern = /###\s*How to update QwenPaw[\s\S]*?(?=\n###|$)/;
        const match = text.match(faqLanguage === "zh" ? zhPattern : enPattern);
        setUpdateMarkdown(
          match && language !== "ru"
            ? match[0].trim()
            : UPDATE_MD[language] ?? UPDATE_MD.en,
        );
      })
      .catch(() => {
        setUpdateMarkdown(UPDATE_MD[language] ?? UPDATE_MD.en);
      });
  };

  const handleLogoClick = () => {
    if (!onDesktop) return;
    const now = Date.now();
    logoClicksRef.current = logoClicksRef.current.filter(
      (time) => time > now - 3000,
    );
    logoClicksRef.current.push(now);
    if (logoClicksRef.current.length < 8) return;

    logoClicksRef.current = [];
    void invoke("open_devtools")
      .then(() => message.success("DevTools opened"))
      .catch((error: unknown) => {
        const detail = error instanceof Error ? error.message : String(error);
        console.error("Failed to open DevTools:", detail);
        message.error(`DevTools error: ${detail}`);
      });
  };

  const versionContent = (
    <span className={styles.appBrandVersionArea}>
      {version && (
        <Badge
          dot={hasUpdate && !isReady && !isBackgroundActive}
          color="rgba(255, 157, 77, 1)"
          offset={[3, 1]}
        >
          <span
            className={`${styles.versionBadge} ${
              hasUpdate && !isReady ? styles.versionBadgeClickable : ""
            }`}
            onClick={hasUpdate && !isReady ? handleOpenUpdateModal : undefined}
          >
            v{version}
          </span>
        </Badge>
      )}
      {isBackgroundActive && (
        <Tooltip title={backgroundDownloadTitle}>
          <SyncOutlined spin className={styles.appBrandUpdateIcon} />
        </Tooltip>
      )}
      {isReady && (
        <Popover
          content={
            <div style={{ textAlign: "center" }}>
              <p style={{ marginBottom: 12 }}>
                {t("sidebar.updateModal.readyToInstallHint", {
                  version: desktop.version,
                })}
              </p>
              <Button
                type="primary"
                size="small"
                onClick={() => void desktop.installDownloaded()}
                loading={isApplyingDownloadedUpdate}
              >
                {t("sidebar.updateModal.restartNow")}
              </Button>
            </div>
          }
          title={t("sidebar.updateModal.readyToInstall")}
          trigger="click"
        >
          <Tooltip title={t("sidebar.updateModal.readyToInstall")}>
            <CheckCircleOutlined className={styles.appBrandReadyIcon} />
          </Tooltip>
        </Popover>
      )}
      {isBackgroundFailed && (
        <Tooltip title={backgroundFailureTitle}>
          <ExclamationCircleOutlined
            className={styles.appBrandFailedIcon}
            onClick={() => void desktop.startBackgroundDownload()}
          />
        </Tooltip>
      )}
    </span>
  );

  return (
    <>
      <div className={styles.appBrand} hidden={hidden}>
        <span className={styles.appBrandLogo} onClick={handleLogoClick}>
          <Slot name="header.logo" kind="replace">
            <img
              src={isDark ? "/logo-dark.svg" : "/logo-light.svg"}
              alt="QwenPaw"
              className={styles.logoImg}
            />
          </Slot>
        </span>
        <span className={styles.logoDivider} />
        {versionContent}
        {action && <span className={styles.appBrandAction}>{action}</span>}
      </div>

      <Modal
        title={null}
        open={updateModalOpen}
        onCancel={() => setUpdateModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setUpdateModalOpen(false)}>
            {t("common.close")}
          </Button>,
          onDesktop && desktop.supportsLaterInstall ? (
            <Button
              key="later"
              onClick={() => {
                setUpdateModalOpen(false);
                void desktop.startBackgroundDownload();
              }}
            >
              {t("sidebar.updateModal.updateLater")}
            </Button>
          ) : null,
          onDesktop ? (
            <Button
              key="install"
              type="primary"
              className={styles.updateViewReleasesBtn}
              onClick={() => {
                setUpdateModalOpen(false);
                void desktop.startInstall();
              }}
            >
              {t("sidebar.updateModal.installDesktopUpdate")}
            </Button>
          ) : (
            <Button
              key="releases"
              type="primary"
              className={styles.updateViewReleasesBtn}
              onClick={() =>
                openExternalLink(getReleaseNotesUrl(i18n.language))
              }
            >
              {t("sidebar.updateModal.viewReleases")}
            </Button>
          ),
        ].filter(Boolean)}
        width={960}
        className={styles.updateModal}
      >
        <div className={styles.updateModalBanner}>
          <div className={styles.updateModalBannerLeft}>
            <span className={styles.updateModalVersionTag}>
              <TagOutlined />
              Version {modalVersion || version}
            </span>
            <div className={styles.updateModalBannerTitle}>
              {t("sidebar.updateModal.title", {
                version: modalVersion || version,
              })}
            </div>
          </div>
        </div>

        <div className={styles.updateModalBody}>
          {updateMarkdown ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ExternalMarkdownLink,
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
