import { Layout, Space } from "antd";
import LanguageSwitcher from "../components/LanguageSwitcher";
import ThemeToggleButton from "../components/ThemeToggleButton";
import { useTranslation } from "react-i18next";
import {
  // BookOutlined,
  LogoutOutlined,
  // QuestionCircleOutlined,
} from "@ant-design/icons";
import { Button, Tooltip } from "@agentscope-ai/design";
import styles from "./index.module.less";
import { useAuth } from "../auth/useAuth";
import { useNavigate } from "react-router-dom";

const { Header: AntHeader } = Layout;

// Navigation URLs
//const NAV_URLS = {
//  docs: "https://copaw.agentscope.io/docs/intro",
//  faq: "https://copaw.agentscope.io/docs/faq",
//  changelog: "https://github.com/aimentorai/boostclaw/releases",
//  github: "https://github.com/aimentorai/boostclaw",
//} as const;


const keyToLabel: Record<string, string> = {
  chat: "nav.chat",
  channels: "nav.channels",
  sessions: "nav.sessions",
  "cron-jobs": "nav.cronJobs",
  heartbeat: "nav.heartbeat",
  skills: "nav.skills",
  tools: "nav.tools",
  mcp: "nav.mcp",
  "agent-config": "nav.agentConfig",
  workspace: "nav.workspace",
  models: "nav.models",
  environments: "nav.environments",
  security: "nav.security",
  "token-usage": "nav.tokenUsage",
};

interface HeaderProps {
  selectedKey: string;
}

export default function Header({ selectedKey }: HeaderProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  //const handleNavClick = (url: string) => {
  //  if (url) {
  //    // Check if running in pywebview environment
  //    const pywebview = window.pywebview;
  //    if (pywebview && pywebview.api) {
  //      // Use pywebview API to open external link in system browser
  //      pywebview.api.open_external_link(url);
  //    } else {
  //      // Normal browser environment
  //      window.open(url, "_blank");
  //    }
  //  }
  //};

  return (
    <AntHeader className={styles.header}>
      <span className={styles.headerTitle}>
        {t(keyToLabel[selectedKey] || "nav.chat")}
      </span>
      <Space size="middle">
        {/* 暂时隐藏 DOC 按钮 */}
        {/* <Tooltip title={t("header.docs")}>
          <Button
            icon={<BookOutlined />}
            type="text"
            onClick={() => handleNavClick(NAV_URLS.docs)}
          >
            {t("header.docs")}
          </Button>
        </Tooltip> */}
        {/* 暂时隐藏 FAQ 按钮 */}
        {/* <Tooltip title={t("header.faq")}>
          <Button
            icon={<QuestionCircleOutlined />}
            type="text"
            onClick={() => handleNavClick(NAV_URLS.faq)}
          >
            {t("header.faq")}
          </Button>
        </Tooltip> */}
        <Tooltip title={t("header.logout")}>
          <Button icon={<LogoutOutlined />} type="text" onClick={handleLogout}>
            {t("header.logout")}
          </Button>
        </Tooltip>
        <LanguageSwitcher />
        <ThemeToggleButton />
      </Space>
    </AntHeader>
  );
}
