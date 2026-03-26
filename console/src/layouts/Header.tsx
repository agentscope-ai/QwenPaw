import { Layout, Space, Badge, Spin } from "antd";
import LanguageSwitcher from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import { useTranslation } from "react-i18next";
import { Button, Tooltip, Modal } from "@agentscope-ai/design";
import styles from "./index.module.less";
import api from "../api";
import {
  GITHUB_URL,
  getDocsUrl,
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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const { Header: AntHeader } = Layout;

export default function Header() {
  const { t, i18n } = useTranslation();
  const { isDark } = useTheme();
  const [version, setVersion] = useState<string>("");
  const [latestVersion, setLatestVersion] = useState<string>("");
  const [updateModalOpen, setUpdateModalOpen] = useState(false);
  const [updateMarkdown, setUpdateMarkdown] = useState<string>("");

  useEffect(() => {
    api
      .getVersion()
      .then((res) => setVersion(res?.version ?? ""))
      .catch(() => { });
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
      .catch(() => { });
  }, []);

  const hasUpdate =
    !!version && !!latestVersion && compareVersions(latestVersion, version) > 0;

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

  const handleNavClick = (url: string) => {
    if (url) {
      const pywebview = (window as any).pywebview;
      if (pywebview?.api) {
        pywebview.api.open_external_link(url);
      } else {
        window.open(url, "_blank");
      }
    }
  };

  return (
    <>
      <AntHeader className={styles.header}>
        <div className={styles.logoWrapper}>
          <img
            src={
              isDark
                ? `${import.meta.env.BASE_URL}dark-logo.png`
                : `${import.meta.env.BASE_URL}logo.png`
            }
            alt="CoPaw"
            className={styles.logoImg}
          />
          <div className={styles.logoDivider} />
          {version && (
            <Badge dot={!!hasUpdate} color="rgba(255, 157, 77, 1)" offset={[4, 28]}>
              <span
                className={`${styles.versionBadge} ${hasUpdate
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
        <Space size="middle">
          <Tooltip title={t("header.changelog")}>
            <Button
              type="text"
              onClick={() => handleNavClick(getReleaseNotesUrl(i18n.language))}
            >
              {t("header.changelog")}
            </Button>
          </Tooltip>
          <Tooltip title={t("header.docs")}>
            <Button
              type="text"
              onClick={() => handleNavClick(getDocsUrl(i18n.language))}
            >
              {t("header.docs")}
            </Button>
          </Tooltip>
          <Tooltip title={t("header.faq")}>
            <Button
              type="text"
              onClick={() => handleNavClick(getFaqUrl(i18n.language))}
            >
              {t("header.faq")}
            </Button>
          </Tooltip>
          <Tooltip title={t("header.github")}>
            <Button
              type="text"
              onClick={() => handleNavClick(GITHUB_URL)}
            >
              {t("header.github")}
            </Button>
          </Tooltip>
          <div className={styles.headerDivider} />
          <LanguageSwitcher />
          <ThemeToggleButton />
        </Space>
      </AntHeader>

      <Modal
        title={<span className={styles.updateModalTitle}>{t("header.updateAvailable")}</span>}
        open={updateModalOpen}
        onCancel={() => setUpdateModalOpen(false)}
        footer={[
          <Button key="close" onClick={() => setUpdateModalOpen(false)}>
            {t("common.close")}
          </Button>,
        ]}
        width={600}
      >
        <div className={styles.updateModalBody}>
          {updateMarkdown ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
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
