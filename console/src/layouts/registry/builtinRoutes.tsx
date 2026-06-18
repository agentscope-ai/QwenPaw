/**
 * builtinRoutes.ts — host's built-in routes as data.
 *
 * Importing self-registers all builtins into routeRegistry. MainLayout's
 * `useRoutes()` snapshot returns them. Plugin routes are registered via
 * `QwenPaw.route.add(...)` into the same registry and treated uniformly.
 *
 * Lazy components use `lazyImportWithRetry` inline; eager pages (Chat,
 * CodingPage) are passed as ComponentType directly. The `/` redirect is a
 * named route with a tiny DefaultRedirect component so routeRegistry has a
 * single uniform shape.
 *
 * Naming convention mirrors builtinMenu: `core.<key>`.
 */
import { Suspense } from "react";
import { Navigate } from "react-router-dom";
import { Spin } from "antd";
import { useTranslation } from "react-i18next";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { useCodingMode } from "../../stores/codingModeStore";
import { routeRegistry } from "../../plugins/registry/store";
import type { Route } from "../../plugins/registry/types";

// Eager pages
import Chat from "../../pages/Chat";
import CodingPage from "../../pages/Coding";

// Lazy pages
const ChannelsPage = lazyImportWithRetry("../../pages/Control/Channels");
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const InboxPage = lazyImportWithRetry("../../pages/Inbox");
const CronJobsPage = lazyImportWithRetry("../../pages/Control/CronJobs");
const HeartbeatPage = lazyImportWithRetry("../../pages/Control/Heartbeat");
const AgentConfigPage = lazyImportWithRetry("../../pages/Agent/Config");
const SkillsPage = lazyImportWithRetry("../../pages/Agent/Skills");
const SkillPoolPage = lazyImportWithRetry("../../pages/Settings/SkillPool");
const MarketPage = lazyImportWithRetry("../../pages/Settings/Market");
const ToolsPage = lazyImportWithRetry("../../pages/Agent/Tools");
const WorkspacePage = lazyImportWithRetry("../../pages/Agent/Workspace");
const MCPPage = lazyImportWithRetry("../../pages/Agent/MCP");
const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
const SecurityPage = lazyImportWithRetry("../../pages/Settings/Security");
const TokenUsagePage = lazyImportWithRetry("../../pages/Settings/TokenUsage");
const AgentStatsPage = lazyImportWithRetry("../../pages/Settings/AgentStats");
const VoiceTranscriptionPage = lazyImportWithRetry(
  "../../pages/Settings/VoiceTranscription",
);
const AgentsPage = lazyImportWithRetry("../../pages/Settings/Agents");
const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
const BackupsPage = lazyImportWithRetry("../../pages/Settings/Backups");
const PluginManagerPage = lazyImportWithRetry(
  "../../pages/Settings/PluginManager",
);

/**
 * "/" lands here. Waits for useSyncCodingMode to populate the store before
 * deciding between /coding and /chat — see MainLayout.tsx history for why.
 */
function DefaultRedirect() {
  const { t } = useTranslation();
  const { codingMode, initialized } = useCodingMode();
  if (!initialized) {
    return (
      <Spin
        tip={t("common.loading")}
        style={{ display: "block", margin: "20vh auto" }}
      />
    );
  }
  return <Navigate to={codingMode ? "/coding" : "/chat"} replace />;
}

/** Synonym for /acp. Kept for plugins / external links that reference uppercase. */
function ACPRedirect() {
  return <Navigate to="/acp" replace />;
}

export const BUILTIN_ROUTES: Route[] = [
  { id: "core.root", path: "/", component: DefaultRedirect },
  { id: "core.chat", path: "/chat/*", component: Chat },
  { id: "core.coding", path: "/coding/*", component: CodingPage },
  { id: "core.channels", path: "/channels", component: ChannelsPage },
  { id: "core.sessions", path: "/sessions", component: SessionsPage },
  { id: "core.inbox", path: "/inbox", component: InboxPage },
  { id: "core.cron-jobs", path: "/cron-jobs", component: CronJobsPage },
  { id: "core.heartbeat", path: "/heartbeat", component: HeartbeatPage },
  { id: "core.skills", path: "/skills", component: SkillsPage },
  { id: "core.skill-pool", path: "/skill-pool", component: SkillPoolPage },
  { id: "core.market", path: "/market", component: MarketPage },
  { id: "core.tools", path: "/tools", component: ToolsPage },
  { id: "core.mcp", path: "/mcp", component: MCPPage },
  { id: "core.acp", path: "/acp", component: ACPPage },
  { id: "core.acp-alias", path: "/ACP", component: ACPRedirect },
  { id: "core.workspace", path: "/workspace", component: WorkspacePage },
  { id: "core.agents", path: "/agents", component: AgentsPage },
  { id: "core.models", path: "/models", component: ModelsPage },
  {
    id: "core.environments",
    path: "/environments",
    component: EnvironmentsPage,
  },
  {
    id: "core.agent-config",
    path: "/agent-config",
    component: AgentConfigPage,
  },
  { id: "core.security", path: "/security", component: SecurityPage },
  { id: "core.token-usage", path: "/token-usage", component: TokenUsagePage },
  { id: "core.agent-stats", path: "/agent-stats", component: AgentStatsPage },
  {
    id: "core.voice-transcription",
    path: "/voice-transcription",
    component: VoiceTranscriptionPage,
  },
  { id: "core.debug", path: "/debug", component: DebugPage },
  { id: "core.backups", path: "/backups", component: BackupsPage },
  {
    id: "core.plugin-manager",
    path: "/plugin-manager",
    component: PluginManagerPage,
  },
];

routeRegistry.addBuiltin(BUILTIN_ROUTES);

// Suspense imported above is used by lazyImportWithRetry consumers; ref keeps
// TS from tree-shaking the import in older bundler configs.
void Suspense;
