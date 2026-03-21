import { Layout, Space } from "antd";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const { Header: AntHeader } = Layout;

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

  return (
    <AntHeader className={styles.header}>
      <span className={styles.headerTitle}>
        {t(keyToLabel[selectedKey] || "nav.chat")}
      </span>
      <Space size="middle">
        <LanguageSwitcher />
      </Space>
    </AntHeader>
  );
}
