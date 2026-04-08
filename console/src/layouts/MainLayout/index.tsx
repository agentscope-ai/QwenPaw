import { lazy, Suspense } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation, Navigate } from "react-router-dom";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsoleCronBubble from "../../components/ConsoleCronBubble";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import styles from "../index.module.less";

// Chat is eagerly loaded (default landing page)
import Chat from "../../pages/Chat";

// All other pages are lazily loaded
const ChannelsPage = lazy(() => import("../../pages/Control/Channels"));
const SessionsPage = lazy(() => import("../../pages/Control/Sessions"));
const CronJobsPage = lazy(() => import("../../pages/Control/CronJobs"));
const HeartbeatPage = lazy(() => import("../../pages/Control/Heartbeat"));
const AgentConfigPage = lazy(() => import("../../pages/Agent/Config"));
const SkillsPage = lazy(() => import("../../pages/Agent/Skills"));
const SkillPoolPage = lazy(() => import("../../pages/Settings/SkillPool"));
const ToolsPage = lazy(() => import("../../pages/Agent/Tools"));
const WorkspacePage = lazy(() => import("../../pages/Agent/Workspace"));
const MCPPage = lazy(() => import("../../pages/Agent/MCP"));
const ModelsPage = lazy(() => import("../../pages/Settings/Models"));
const EnvironmentsPage = lazy(() => import("../../pages/Settings/Environments"));
const SecurityPage = lazy(() => import("../../pages/Settings/Security"));
const TokenUsagePage = lazy(() => import("../../pages/Settings/TokenUsage"));
const VoiceTranscriptionPage = lazy(() => import("../../pages/Settings/VoiceTranscription"));
const AgentsPage = lazy(() => import("../../pages/Settings/Agents"));

const { Content } = Layout;

const pathToKey: Record<string, string> = {
  "/chat": "chat",
  "/channels": "channels",
  "/sessions": "sessions",
  "/cron-jobs": "cron-jobs",
  "/heartbeat": "heartbeat",
  "/skills": "skills",
  "/skill-pool": "skill-pool",
  "/tools": "tools",
  "/mcp": "mcp",
  "/workspace": "workspace",
  "/agents": "agents",
  "/models": "models",
  "/environments": "environments",
  "/agent-config": "agent-config",
  "/security": "security",
  "/token-usage": "token-usage",
  "/voice-transcription": "voice-transcription",
};

export default function MainLayout() {
  const location = useLocation();
  const currentPath = location.pathname;
  const selectedKey = pathToKey[currentPath] || "chat";

  return (
    <Layout className={styles.mainLayout}>
      <Header />
      <Layout>
        <Sidebar selectedKey={selectedKey} />
        <Content className="page-container">
          <ConsoleCronBubble />
          <div className="page-content">
            <ChunkErrorBoundary>
            <Suspense fallback={<Spin style={{ display: "block", margin: "20vh auto" }} />}>
              <Routes>
                <Route path="/" element={<Navigate to="/chat" replace />} />
                <Route path="/chat/*" element={<Chat />} />
                <Route path="/channels" element={<ChannelsPage />} />
                <Route path="/sessions" element={<SessionsPage />} />
                <Route path="/cron-jobs" element={<CronJobsPage />} />
                <Route path="/heartbeat" element={<HeartbeatPage />} />
                <Route path="/skills" element={<SkillsPage />} />
                <Route path="/skill-pool" element={<SkillPoolPage />} />
                <Route path="/tools" element={<ToolsPage />} />
                <Route path="/mcp" element={<MCPPage />} />
                <Route path="/workspace" element={<WorkspacePage />} />
                <Route path="/agents" element={<AgentsPage />} />
                <Route path="/models" element={<ModelsPage />} />
                <Route path="/environments" element={<EnvironmentsPage />} />
                <Route path="/agent-config" element={<AgentConfigPage />} />
                <Route path="/security" element={<SecurityPage />} />
                <Route path="/token-usage" element={<TokenUsagePage />} />
                <Route
                  path="/voice-transcription"
                  element={<VoiceTranscriptionPage />}
                />
              </Routes>
            </Suspense>
            </ChunkErrorBoundary>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
