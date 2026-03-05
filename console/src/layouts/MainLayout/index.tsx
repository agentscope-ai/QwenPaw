import { Layout } from "antd";
import { useEffect } from "react";
import { Routes, Route, useLocation, useNavigate } from "react-router-dom";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsoleCronBubble from "../../components/ConsoleCronBubble";
import Chat from "../../pages/Chat";
import ChannelsPage from "../../pages/Control/Channels";
import SessionsPage from "../../pages/Control/Sessions";
import CronJobsPage from "../../pages/Control/CronJobs";
import HeartbeatPage from "../../pages/Control/Heartbeat";
import AgentConfigPage from "../../pages/Agent/Config";
import SkillsPage from "../../pages/Agent/Skills";
import WorkspacePage from "../../pages/Agent/Workspace";
import MCPPage from "../../pages/Agent/MCP";
import ModelsPage from "../../pages/Settings/Models";
import EnvironmentsPage from "../../pages/Settings/Environments";

const { Content } = Layout;

const pathToKey: Record<string, string> = {
  "/chat": "chat",
  "/channels": "channels",
  "/sessions": "sessions",
  "/cron-jobs": "cron-jobs",
  "/heartbeat": "heartbeat",
  "/skills": "skills",
  "/mcp": "mcp",
  "/workspace": "workspace",
  "/agents": "agents",
  "/models": "models",
  "/environments": "environments",
  "/agent-config": "agent-config",
};

export default function MainLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const selectedKey = pathToKey[currentPath] || "chat";

  useEffect(() => {
    if (currentPath === "/") {
      navigate("/chat", { replace: true });
    }
  }, [currentPath, navigate]);

  // Use location.pathname as key so each page remounts on navigation,
  // triggering useEffect data fetches automatically.
  const pageKey = location.pathname;

  return (
    <Layout style={{ height: "100vh" }}>
      <Sidebar selectedKey={selectedKey} />
      <Layout>
        <Header selectedKey={selectedKey} />
        <Content className="page-container">
          <ConsoleCronBubble />
          <div className="page-content">
            <Routes>
              <Route path="/chat" element={<Chat key={pageKey} />} />
              <Route path="/channels" element={<ChannelsPage key={pageKey} />} />
              <Route path="/sessions" element={<SessionsPage key={pageKey} />} />
              <Route path="/cron-jobs" element={<CronJobsPage key={pageKey} />} />
              <Route path="/heartbeat" element={<HeartbeatPage key={pageKey} />} />
              <Route path="/skills" element={<SkillsPage key={pageKey} />} />
              <Route path="/mcp" element={<MCPPage key={pageKey} />} />
              <Route path="/workspace" element={<WorkspacePage key={pageKey} />} />
              <Route path="/models" element={<ModelsPage key={pageKey} />} />
              <Route path="/environments" element={<EnvironmentsPage key={pageKey} />} />
              <Route path="/agent-config" element={<AgentConfigPage key={pageKey} />} />
              <Route path="/" element={<Chat key={pageKey} />} />
            </Routes>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
