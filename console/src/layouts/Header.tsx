import { Layout } from "antd";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { useTranslation } from "react-i18next";

const { Header: AntHeader } = Layout;

const keyToLabel: Record<string, string> = {
  chat: "nav.chat",
  channels: "nav.channels",
  sessions: "nav.sessions",
  "cron-jobs": "nav.cronJobs",
  heartbeat: "nav.heartbeat",
  skills: "nav.skills",
  mcp: "nav.mcp",
  "agent-config": "nav.agentConfig",
  workspace: "nav.workspace",
  models: "nav.models",
  environments: "nav.environments",
};

interface HeaderProps {
  selectedKey: string;
}

export default function Header({ selectedKey }: HeaderProps) {
  const { t } = useTranslation();

  return (
    <AntHeader
      style={{
        height: 64,
        padding: "0 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: "#fff",
        borderBottom: "1px solid #f0f0f0",
      }}
    >
      <span style={{ fontSize: 18, fontWeight: 500 }}>
        {t(keyToLabel[selectedKey] || "nav.chat")}
      </span>
      <LanguageSwitcher />
    </AntHeader>
  );
}
