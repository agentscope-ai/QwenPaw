/**
 * builtinRoutes.ts — host's built-in routes as data.
 *
 * Importing self-registers all builtins into routeRegistry. MainLayout's
 * `useRoutes()` snapshot returns them. Plugin routes are registered via
 * `QwenPaw.route.add(...)` into the same registry and treated uniformly.
 *
 * Lazy components use `lazyImportWithRetry` inline; the eager Chat page is
 * passed as ComponentType directly. The `/` redirect is a
 * named route with a tiny DefaultRedirect component so routeRegistry has a
 * single uniform shape.
 *
 * Naming convention mirrors builtinMenu: `core.<key>`.
 */
import { Suspense } from "react";
import { Navigate } from "react-router-dom";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { routeRegistry } from "../../plugins/registry/store";
import type { Route } from "../../plugins/registry/types";

// Eager pages
import Chat from "../../pages/Chat";

// Lazy pages
const ChannelsPage = lazyImportWithRetry("../../pages/Control/Channels");
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const InboxPage = lazyImportWithRetry("../../pages/Inbox");
const CronJobsPage = lazyImportWithRetry("../../pages/Control/CronJobs");
const HeartbeatPage = lazyImportWithRetry("../../pages/Control/Heartbeat");
const AgentConfigPage = lazyImportWithRetry("../../pages/Agent/Config");
const SkillsPage = lazyImportWithRetry("../../pages/Agent/Skills");
const SkillPoolPage = lazyImportWithRetry("../../pages/Settings/SkillPool");
const ToolsPage = lazyImportWithRetry("../../pages/Agent/Tools");
const CheckpointsPage = lazyImportWithRetry("../../pages/Agent/Checkpoints");
const MCPPage = lazyImportWithRetry("../../pages/Agent/MCP");
const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
const OffloadPolicyPage = lazyImportWithRetry(
  "../../pages/Settings/OffloadPolicy",
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
const AppCenterPage = lazyImportWithRetry("../../pages/AppCenter");
const FilesPage = lazyImportWithRetry("../../pages/Files");

/**
 * "/" always lands on the canonical Chat workspace.
 */
function DefaultRedirect() {
  return <Navigate to="/chat" replace />;
}

/** Synonym for /acp. Kept for plugins / external links that reference uppercase. */
function ACPRedirect() {
  return <Navigate to="/acp" replace />;
}

export const BUILTIN_ROUTES: Route[] = [
  { id: "core.root", path: "/", component: DefaultRedirect },
  { id: "core.chat", path: "/chat/*", component: Chat },
  { id: "core.files", path: "/files", component: FilesPage },
  { id: "core.channels", path: "/channels", component: ChannelsPage },
  { id: "core.sessions", path: "/sessions", component: SessionsPage },
  { id: "core.inbox", path: "/inbox", component: InboxPage },
  { id: "core.cron-jobs", path: "/cron-jobs", component: CronJobsPage },
  { id: "core.heartbeat", path: "/heartbeat", component: HeartbeatPage },
  { id: "core.skills", path: "/skills", component: SkillsPage },
  { id: "core.skill-pool", path: "/skill-pool", component: SkillPoolPage },
  { id: "core.tools", path: "/tools", component: ToolsPage },
  { id: "core.mcp", path: "/mcp", component: MCPPage },
  { id: "core.acp", path: "/acp", component: ACPPage },
  { id: "core.acp-alias", path: "/ACP", component: ACPRedirect },
  { id: "core.checkpoints", path: "/checkpoints", component: CheckpointsPage },
  { id: "core.agents", path: "/agents", component: AgentsPage },
  { id: "core.models", path: "/models", component: ModelsPage },
  {
    id: "core.environments",
    path: "/environments",
    component: EnvironmentsPage,
  },
  {
    id: "core.offload-policy",
    path: "/offload-policy",
    component: OffloadPolicyPage,
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
  { id: "core.app-center", path: "/apps", component: AppCenterPage },
  // Deep-link / refresh target: `/apps/<id>` also lands on the App Center,
  // which opens the app inline (with the “← App Center” bar) from the URL.
  {
    id: "core.app-center.embed",
    path: "/apps/:appId",
    component: AppCenterPage,
  },
];

routeRegistry.addBuiltin(BUILTIN_ROUTES);

// Suspense imported above is used by lazyImportWithRetry consumers; ref keeps
// TS from tree-shaking the import in older bundler configs.
void Suspense;
