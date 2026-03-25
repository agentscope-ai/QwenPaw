import { Layout, Space } from "antd";
import LanguageSwitcher from "../components/LanguageSwitcher";
import ThemeToggleButton from "../components/ThemeToggleButton";
import AgentSelector from "../components/AgentSelector";
import { useTranslation } from "react-i18next";
import {
  FileTextOutlined,
  BookOutlined,
  QuestionCircleOutlined,
  GithubOutlined,
} from "@ant-design/icons";
import { Button, Tooltip } from "@agentscope-ai/design";
import styles from "./index.module.less";
import {
  GITHUB_URL,
  KEY_TO_LABEL,
  getDocsUrl,
  getFaqUrl,
  getReleaseNotesUrl,
} from "./constants";

const { Header: AntHeader } = Layout;

interface HeaderProps {
  selectedKey: string;
}

export default function Header({ selectedKey }: HeaderProps) {
  const { t, i18n } = useTranslation();

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
    <AntHeader className={styles.header}>
      <span className={styles.headerTitle}>
        {t(KEY_TO_LABEL[selectedKey] || "nav.chat")}
      </span>
      <Space size="middle">
        <AgentSelector />
        <Tooltip title={t("header.changelog")}>
          <Button
            icon={<FileTextOutlined />}
            type="text"
            onClick={() => handleNavClick(getReleaseNotesUrl(i18n.language))}
          >
            {t("header.changelog")}
          </Button>
        </Tooltip>
        <Tooltip title={t("header.docs")}>
          <Button
            icon={<BookOutlined />}
            type="text"
            onClick={() => handleNavClick(getDocsUrl(i18n.language))}
          >
            {t("header.docs")}
          </Button>
        </Tooltip>
        <Tooltip title={t("header.faq")}>
          <Button
            icon={<QuestionCircleOutlined />}
            type="text"
            onClick={() => handleNavClick(getFaqUrl(i18n.language))}
          >
            {t("header.faq")}
          </Button>
        </Tooltip>
        <Tooltip title={t("header.github")}>
          <Button
            icon={<GithubOutlined />}
            type="text"
            onClick={() => handleNavClick(GITHUB_URL)}
          >
            {t("header.github")}
          </Button>
        </Tooltip>
        <LanguageSwitcher />
        <ThemeToggleButton />
      </Space>
    </AntHeader>
  );
}
